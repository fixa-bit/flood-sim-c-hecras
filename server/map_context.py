"""Render real source terrain/river context. These heights never compute water."""
from functools import lru_cache
import base64
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.ops import nearest_points, transform

from .acquire import BASE
from .store import checked_asset, file_hash, read_json

SIZE = 65


@lru_cache(maxsize=4)
def _source_metadata(fingerprint):
    records = []
    for filename, _, _ in fingerprint:
        with rasterio.open(filename) as src:
            if str(src.crs) != "EPSG:4326":
                raise ValueError("Viewer terrain source requires WGS84 coordinates.")
            records.append({"path": filename, "sha256": file_hash(Path(filename)), "bounds": list(src.bounds)})
    digest = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    bounds = [min(r["bounds"][0] for r in records), min(r["bounds"][1] for r in records), max(r["bounds"][2] for r in records), max(r["bounds"][3] for r in records)]
    return {"available": True, "tile_size": SIZE, "maximum_level": 14, "bounds": bounds, "sha256": digest,
            "product": "FABDEM v1.2 ~30 m", "source": "https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/",
            "license": "CC BY-NC-SA 4.0", "tiles": records,
            "notes": "Source heights for visual context. Native EGM2008 heights; no geoid conversion. Outside source coverage the viewer uses an ellipsoid. Hydraulic results use their own hash-bound terrain clip."}


def terrain_metadata():
    paths = sorted((BASE / "raw" / "fabdem").glob("*.tif"))
    if not paths:
        try:
            _, path = checked_asset("dem")
            paths = [path]
        except ValueError:
            return {"available": False}
    fingerprint = tuple((str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in paths)
    return _source_metadata(fingerprint)


def tile_bounds(level, x, y):
    if not 0 <= level <= 14 or not 0 <= x < 2 ** (level + 1) or not 0 <= y < 2 ** level:
        raise ValueError("Terrain tile coordinates are outside the supported geographic tile scheme.")
    width, height = 180 / 2 ** level, 180 / 2 ** level
    west, north = -180 + x * width, 90 - y * height
    return west, north - height, west + width, north


@lru_cache(maxsize=256)
def height_tile(digest, paths, level, x, y):
    west, south, east, north = tile_bounds(level, x, y)
    dx, dy = (east - west) / (SIZE - 1), (north - south) / (SIZE - 1)
    # Heightmap vertices include all four tile edges. Neighbouring tiles sample
    # identical edge coordinates; these are not pixel-centre image coordinates.
    affine = from_bounds(west - dx / 2, south - dy / 2, east + dx / 2, north + dy / 2, SIZE, SIZE)
    heights = np.zeros((SIZE, SIZE), dtype="float32")
    for path in paths:
        with rasterio.open(path) as src:
            b = src.bounds
            if east < b.left or west > b.right or north < b.bottom or south > b.top:
                continue
            if level <= 6:
                # Coarse globe tiles need a few actual source samples. Warping
                # their enormous footprint would read every 30 m source cell.
                lons, lats = np.meshgrid(np.linspace(west, east, SIZE), np.linspace(north, south, SIZE))
                valid = (lons >= b.left) & (lons < b.right) & (lats > b.bottom) & (lats <= b.top)
                if valid.any():
                    samples = list(src.sample(zip(lons[valid], lats[valid]), masked=True))
                    heights[valid] = [0 if np.ma.is_masked(value[0]) else float(value[0]) for value in samples]
                continue
            reproject(rasterio.band(src, 1), heights, src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata,
                      dst_transform=affine, dst_crs="EPSG:4326", dst_nodata=0, init_dest_nodata=False,
                      resampling=Resampling.bilinear, num_threads=1)
    if not np.isfinite(heights).all():
        raise ValueError("Terrain source yielded nonfinite heights.")
    return heights.astype("<f4").tobytes()


def terrain_tile(level, x, y):
    meta = terrain_metadata()
    if not meta["available"]:
        raise ValueError("Download or register real FABDEM before requesting terrain.")
    return height_tile(meta["sha256"], tuple(row["path"] for row in meta["tiles"]), level, x, y)


@lru_cache(maxsize=2)
def coarse_tiles(digest, paths, bounds):
    tiles = {}
    for level in range(7):
        width = 180 / 2 ** level
        left, right = math.floor((bounds[0] + 180) / width), math.floor((bounds[2] + 180) / width)
        top, bottom = math.floor((90 - bounds[3]) / width), math.floor((90 - bounds[1]) / width)
        for x in range(max(0, left), min(2 ** (level + 1) - 1, right) + 1):
            for y in range(max(0, top), min(2 ** level - 1, bottom) + 1):
                tiles[f"{level}/{x}/{y}"] = base64.b64encode(height_tile(digest, paths, level, x, y)).decode("ascii")
    return tiles


def viewer_terrain_metadata():
    meta = terrain_metadata()
    if not meta["available"]:
        return meta
    return {**meta, "coarse_heights": coarse_tiles(meta["sha256"], tuple(row["path"] for row in meta["tiles"]), tuple(meta["bounds"]))}


def river_context(lon, lat):
    asset, path = checked_asset("hydrography")
    data = read_json(path)
    major = [f for f in data["features"] if float(f["properties"].get("UPLAND_SKM", 0)) >= 500]
    if not major:
        major = data["features"]
    forward = Transformer.from_crs(4326, 32642 if lon < 72 else 32643, always_xy=True).transform
    reverse = Transformer.from_crs(32642 if lon < 72 else 32643, 4326, always_xy=True).transform
    target = transform(forward, Point(lon, lat))
    channels = [transform(forward, shape(f["geometry"])) for f in major]
    channel = min(channels, key=target.distance)
    nearest = nearest_points(target, channel)[1]
    if target.distance(nearest) > 3000:
        return {"available": False, "reason": "No downloaded major river within 3 km of this planning point."}
    focus_lon, focus_lat = reverse(nearest.x, nearest.y)
    focus_source = "HydroRIVERS major channel"
    # Centre the camera on mapped water, rather than the approximate gauge's
    # town coordinate or a coarse HydroRIVERS segment offset from the channel.
    try:
        _, cover = checked_asset("landcover")
        with rasterio.open(cover) as src:
            window = rasterio.windows.from_bounds(lon - .015, lat - .015, lon + .015, lat + .015, src.transform)
            values = src.read(1, window=window, boundless=True, fill_value=0)
            rows, cols = np.where(values == 80)
            if len(rows):
                xs, ys = rasterio.transform.xy(src.window_transform(window), rows, cols)
                mx, my = forward(np.asarray(xs), np.asarray(ys))
                distances = np.hypot(mx - target.x, my - target.y)
                eligible = [i for i in np.argsort(distances) if distances[i] <= 1500 and channel.distance(Point(mx[i], my[i])) <= 600]
                if eligible:
                    index = eligible[0]
                    focus_lon, focus_lat = float(xs[index]), float(ys[index])
                    focus_source = "ESA WorldCover 2021 mapped water near the major HydroRIVERS channel"
    except ValueError:
        pass
    elevation = 0.0
    meta = terrain_metadata()
    for record in meta.get("tiles", []):
        with rasterio.open(record["path"]) as src:
            if src.bounds.left <= focus_lon <= src.bounds.right and src.bounds.bottom <= focus_lat <= src.bounds.top:
                height = next(src.sample([(focus_lon, focus_lat)], masked=True))[0]
                if not np.ma.is_masked(height) and np.isfinite(height):
                    elevation = float(height)
                    break
    return {"available": True, "source": asset["source"], "product": asset["product"], "sha256": asset["sha256"],
            "focus": {"lon": focus_lon, "lat": focus_lat, "height_m": elevation, "source": focus_source},
            "rivers": {"type": "FeatureCollection", "features": major},
            "note": "River and mapped-water context; not a simulated or observed 2022 flood extent."}
