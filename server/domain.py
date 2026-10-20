"""Clip documented rasters and snap to supplied hydrography; never computes water."""
import json
from pathlib import Path
import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.warp import transform_bounds, transform_geom
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import nearest_points, transform
from pyproj import Transformer
from .models import Scenario
from .store import ROOT, assets, checked_asset, file_hash, read_json, scenario_hash, write_json


def bounds_for(s: Scenario):
    dy = s.domain.radius_km / 111.32
    dx = dy / np.cos(np.radians(s.outlet.lat))
    return [s.outlet.lon - dx, s.outlet.lat - dy, s.outlet.lon + dx, s.outlet.lat + dy]


def geojson_geometry(path: Path, allowed):
    data = read_json(path)
    if data.get("type") != "FeatureCollection" or data.get("crs"):
        raise ValueError("Vectors must be RFC 7946 WGS84 FeatureCollections without a crs member.")
    geometries = [shape(f["geometry"]) for f in data["features"]]
    if not geometries or any(g.geom_type not in allowed or g.is_empty or not g.is_valid for g in geometries):
        raise ValueError(f"Invalid geometry. Expected {allowed}.")
    if any(not (-180 <= g.bounds[0] <= g.bounds[2] <= 180 and -90 <= g.bounds[1] <= g.bounds[3] <= 90) for g in geometries):
        raise ValueError("GeoJSON coordinates must be WGS84 longitude/latitude.")
    return data, geometries


def snap_outlet(s: Scenario):
    _, path = checked_asset("hydrography")
    _, geometries = geojson_geometry(path, {"LineString", "MultiLineString"})
    forward = Transformer.from_crs("EPSG:4326", s.domain.model_crs, always_xy=True).transform
    reverse = Transformer.from_crs(s.domain.model_crs, "EPSG:4326", always_xy=True).transform
    point = transform(forward, Point(s.outlet.lon, s.outlet.lat))
    channels = [transform(forward, g) for g in geometries]
    channel = min(channels, key=lambda line: point.distance(line))
    snapped = nearest_points(point, channel)[1]
    distance = point.distance(snapped)
    if distance > 2000:
        raise ValueError(f"Nearest supplied channel is {distance:.0f} m away; maximum snap tolerance is 2,000 m.")
    lon, lat = reverse(snapped.x, snapped.y)
    return {"lon": lon, "lat": lat, "distance_m": round(distance, 2), "source": "registered hydrography", "verified": False}


def clip_raster(source: Path, destination: Path, wgs84_bounds):
    with rasterio.open(source) as src:
        if not src.crs:
            raise ValueError("Raster requires a declared CRS.")
        b = transform_bounds("EPSG:4326", src.crs, *wgs84_bounds, densify_pts=21)
        # Require complete coverage; a partial terrain silently truncates inundation.
        if not box(*src.bounds).covers(box(*b)):
            raise ValueError(f"{Path(str(source)).name} does not cover the complete requested domain.")
        window = rasterio.windows.from_bounds(*b, transform=src.transform)
        if window.width * window.height * src.count > 16_000_000:
            raise ValueError("Clip exceeds 16 million values. Reduce the domain or prepare tiles offline.")
        image, affine = mask(src, [mapping(box(*b))], crop=True)
        profile = src.profile.copy()
        profile.update(driver="GTiff", height=image.shape[1], width=image.shape[2], transform=affine, compress="deflate")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(destination, "w", **profile) as dst:
            dst.write(image)
        return {"sha256": file_hash(destination), "crs": str(src.crs), "width": image.shape[2], "height": image.shape[1]}


def prepare_domain(s: Scenario):
    dem, dem_path = checked_asset("dem")
    if s.domain.dem_sha256 and s.domain.dem_sha256 != dem["sha256"]:
        raise ValueError("Scenario DEM hash differs from the registered source.")
    bounds = bounds_for(s)
    key = scenario_hash(s)
    folder = ROOT / "domains" / key
    cached = read_json(folder / "domain.json")
    input_hashes = {key: asset["sha256"] for key, asset in assets().items() if key in {"dem", "soil", "moisture", "rainfall", "landcover", "hydrography", "catchment"}}
    for kind in input_hashes:
        checked_asset(kind)
    if cached and cached.get("input_hashes") == input_hashes and all((folder / item["file"]).is_file() and file_hash(folder / item["file"]) == item["sha256"] for item in cached["clips"].values()):
        return cached
    snapped = snap_outlet(s)
    clips = {}
    for kind in ["dem", "soil", "moisture", "rainfall", "landcover"]:
        if kind not in assets():
            continue
        asset, path = checked_asset(kind)
        output = folder / f"{kind}.tif"
        clips[kind] = {**clip_raster(path, output, bounds), "file": output.name, "source_sha256": asset["sha256"], "source": asset["source"], "license": asset["license"]}
    basin = None
    if "catchment" in assets():
        asset, path = checked_asset("catchment")
        data, polygons = geojson_geometry(path, {"Polygon", "MultiPolygon"})
        outlet = Point(snapped["lon"], snapped["lat"])
        matches = [g for g in polygons if g.covers(outlet)]
        if not matches:
            raise ValueError("Registered catchment does not contain the snapped outlet.")
        selected = min(matches, key=lambda g: g.area)
        basin = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": mapping(selected), "properties": {"source": asset["source"]}}]}
        write_json(folder / "catchment.geojson", basin)
    result = {"scenario_sha256": key, "input_hashes": input_hashes, "bounds": bounds, "snapped_outlet": snapped, "clips": clips,
              "catchment": basin, "catchment_status": "supplied delineation; hydrologic review required" if basin else "missing; domain rectangle is not a catchment",
              "note": "Hydraulic domain clip; catchment rainfall/runoff must cover the full upstream basin. No water depth computed."}
    write_json(folder / "domain.json", result)
    return result
