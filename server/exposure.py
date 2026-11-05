"""Exposure context: population and critical facilities against published model depth.

Run `python -m server.exposure --help`.

These layers never enter a hydraulic model and are kept out of `assets.json`,
so model bindings and their input hashes are unaffected. Exposure numbers are
arithmetic on published depth rasters: people living in cells the model shows
under water. They are not casualty, displacement or damage estimates, and they
inherit every limitation of the (uncalibrated) model output they are read from.
"""
import argparse
from datetime import datetime, timezone
import json
import time
from pathlib import Path

import httpx
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from PIL import Image
from pyproj import Transformer

from .acquire import HTTP_TIMEOUT, download
from .store import ROOT, file_hash, read_json, write_json

EXPOSURE = ROOT / "exposure"
# Both hydraulic sites: the Nowshera pilot clip (71.72-72.24 E) and the Warsak
# window (71.10-71.62 E), joined into one rectangle.
EXPOSURE_BOUNDS = [71.10, 33.79, 72.24, 34.38]
RAW = ROOT / "downloads" / "exposure" / "raw"
LAYERS = EXPOSURE / "layers.json"
POPULATION_URL = (
    "https://data.worldpop.org/GIS/Population/Global_2015_2030/R2024B/2022/PAK/v1/100m/"
    "constrained/pak_pop_2022_CN_100m_R2024B_v1.tif"
)
POPULATION_PRODUCT = "WorldPop Global2 R2024B, Pakistan 2022, constrained ~100 m population counts"
POPULATION_LICENSE = "CC BY 4.0; cite WorldPop (www.worldpop.org)"
OVERPASS_URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
                 "https://overpass.kumi.systems/api/interpreter"]
FACILITY_KINDS = {
    "hospital": "health", "clinic": "health", "doctors": "health",
    "school": "education", "college": "education", "university": "education",
    "police": "emergency", "fire_station": "emergency",
}
# People per km². Population is a context layer, so it uses a warm scale that
# cannot be confused with the blue water classes.
DENSITY_EDGES = [250, 1000, 5000, 20000]
DENSITY_COLORS = np.array(
    [[255, 237, 160, 120], [254, 196, 79, 150], [253, 141, 60, 175], [227, 74, 51, 195], [158, 1, 66, 215]],
    dtype=np.uint8,
)
# Match the first two depth legend edges so map colours and counts agree.
DEPTH_THRESHOLDS = [0.3, 1.0]
METHOD_VERSION = "v5"
# Flood hazard to people (Defra/EA FD2321): HR = d (v + 0.5) + DF, with debris
# factor DF = 0.5 where d >= 0.25 m (pasture/arable) and 0 below. HR >= 0.75 is
# "danger for some"; computed only for results that publish cell speed.
HAZARD_DANGER = .75


def hazard_rating(depth, speed):
    depth, speed = np.asarray(depth, float), np.asarray(speed, float)
    return depth * (speed + .5) + np.where(depth >= .25, .5, 0.0)
FACILITY_FLOOD_M = 0.3
FACILITY_SERIES_MIN_M = 0.05
# 3D columns aggregate this many WorldPop cells per side: 6 x 3 arcsec = 0.005°
# (about 460 m east-west by 555 m north-south at Nowshera).
COLUMN_BLOCK = 6
# Columns start this far below the lowest sampled ground point so they never
# float above terrain on a slope.
COLUMN_SINK_M = 3.0


def _layers():
    return read_json(LAYERS, {})


def _save_layer(key, record):
    layers = _layers()
    layers[key] = record
    write_json(LAYERS, layers)


def pixel_area_km2(transform, rows):
    """Area of each row of a geographic (degree) grid at its centre latitude."""
    lat = transform.f + (np.arange(rows) + 0.5) * transform.e
    km_per_degree = 111.32
    return abs(transform.a * transform.e) * km_per_degree**2 * np.cos(np.radians(lat))


def population_overlay(values, transform, output: Path):
    density = values / pixel_area_km2(transform, values.shape[0])[:, None]
    rgba = DENSITY_COLORS[np.digitize(np.nan_to_num(density), DENSITY_EDGES)].copy()
    rgba[~(np.isfinite(values) & (values > 0))] = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba).save(output)
    height, width = values.shape
    west, south, east, north = rasterio.transform.array_bounds(height, width, transform)
    return [west, south, east, north]


def acquire_population(bounds=EXPOSURE_BOUNDS):
    raw = download(POPULATION_URL, RAW / Path(POPULATION_URL).name, max_bytes=200_000_000)
    output = EXPOSURE / "population-worldpop-2022.tif"
    with rasterio.open(raw) as src:
        if str(src.crs) != "EPSG:4326":
            raise ValueError("WorldPop source is expected in WGS84.")
        window = from_bounds(*bounds, transform=src.transform).round_offsets().round_lengths()
        values = src.read(1, window=window, masked=True).astype(np.float32).filled(np.nan)
        transform = src.window_transform(window)
        profile = src.profile.copy()
    values[values < 0] = np.nan
    if not np.isfinite(values).any():
        raise ValueError("The population clip contains no valid cells.")
    profile.update(driver="GTiff", width=values.shape[1], height=values.shape[0], transform=transform,
                   dtype="float32", nodata=np.nan, compress="deflate", tiled=False)
    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(values, 1)
    overlay = EXPOSURE / "population.png"
    overlay_bounds = population_overlay(values, transform, overlay)
    record = {
        "product": POPULATION_PRODUCT, "source": POPULATION_URL, "license": POPULATION_LICENSE,
        "source_sha256": file_hash(raw), "path": output.relative_to(ROOT).as_posix(), "sha256": file_hash(output),
        "bounds": list(rasterio.transform.array_bounds(values.shape[0], values.shape[1], transform)),
        "resolution_deg": [transform.a, -transform.e], "total_population": float(np.nansum(values)),
        "overlay": {"path": overlay.relative_to(ROOT).as_posix(), "sha256": file_hash(overlay), "bounds": overlay_bounds},
        "density_edges_per_km2": DENSITY_EDGES, "acquired_at": datetime.now(timezone.utc).isoformat(),
        "notes": "Modelled residential population counts (census-based, constrained to mapped settlements). "
                 "Night-time residence, not daytime location; no 2022 flood displacement is represented.",
    }
    _save_layer("population", record)
    return record


def overpass_query(bounds):
    west, south, east, north = bounds
    kinds = "|".join(FACILITY_KINDS)
    return f'[out:json][timeout:90];nwr["amenity"~"^({kinds})$"]({south},{west},{north},{east});out center tags;'


def facility_features(response):
    features = []
    for element in response.get("elements", []):
        tags = element.get("tags", {})
        amenity = tags.get("amenity")
        lon = element.get("lon", element.get("center", {}).get("lon"))
        lat = element.get("lat", element.get("center", {}).get("lat"))
        if amenity not in FACILITY_KINDS or lon is None or lat is None:
            continue
        features.append({
            "type": "Feature",
            "id": f"osm:{element['type']}/{element['id']}",
            "geometry": {"type": "Point", "coordinates": [round(float(lon), 7), round(float(lat), 7)]},
            "properties": {"kind": FACILITY_KINDS[amenity], "amenity": amenity,
                           "name": tags.get("name:en") or tags.get("name") or None},
        })
    features.sort(key=lambda feature: feature["id"])
    return features


def _overpass(query):
    """POST a query, retrying transient gateway errors and trying a public mirror."""
    error = None
    for url in OVERPASS_URLS:
        for attempt in range(3):
            try:
                response = httpx.post(url, data={"data": query}, timeout=HTTP_TIMEOUT,
                                      headers={"User-Agent": "IndusLabResearch/1.0 (public scientific input acquisition)"})
                response.raise_for_status()
                return url, response
            except httpx.HTTPError as exc:
                error = exc
                time.sleep(2 + 3 * attempt)
    raise ValueError(f"Overpass API unavailable: {error}")


def acquire_facilities(bounds=EXPOSURE_BOUNDS):
    source, response = _overpass(overpass_query(bounds))
    data = response.json()
    raw = RAW / "osm-facilities.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(response.content)
    features = facility_features(data)
    output = EXPOSURE / "facilities.geojson"
    write_json(output, {"type": "FeatureCollection", "features": features})
    counts = {}
    for feature in features:
        counts[feature["properties"]["kind"]] = counts.get(feature["properties"]["kind"], 0) + 1
    record = {
        "product": "OpenStreetMap health, education and emergency amenities (Overpass API)",
        "source": source, "query": overpass_query(bounds), "license": "ODbL 1.0; © OpenStreetMap contributors",
        "osm_timestamp": data.get("osm3s", {}).get("timestamp_osm_base"), "source_sha256": file_hash(raw),
        "path": output.relative_to(ROOT).as_posix(), "sha256": file_hash(output), "count": len(features),
        "counts": counts, "acquired_at": datetime.now(timezone.utc).isoformat(),
        "notes": "Volunteered mapping: coverage is incomplete and some points are approximate. "
                 "Facilities mapped as areas are represented by their centre.",
    }
    _save_layer("facilities", record)
    return record


def _checked(key):
    record = _layers().get(key)
    if not record:
        return None, None
    path = ROOT / record["path"]
    if not path.is_file() or file_hash(path) != record["sha256"]:
        raise ValueError(f"The {key} exposure layer is missing or changed; acquire it again.")
    return record, path


def layer_summary():
    """Public description of the exposure layers, without local file paths."""
    summary = {}
    for key, record in _layers().items():
        item = {k: v for k, v in record.items() if k not in {"path", "query"}}
        if "overlay" in item:
            item["overlay"] = {"url": "/api/exposure/population.png", "bounds": item["overlay"]["bounds"],
                               "sha256": item["overlay"]["sha256"]}
        summary[key] = item
    return summary


def overlay_path():
    record = _layers().get("population")
    if not record:
        return None
    path = ROOT / record["overlay"]["path"]
    return path if path.is_file() and file_hash(path) == record["overlay"]["sha256"] else None


def facilities_geojson():
    _, path = _checked("facilities")
    return read_json(path) if path else {"type": "FeatureCollection", "features": []}


def _grid_index(transform, crs, width, height, lons, lats):
    """Depth-grid row/column of each WGS84 point, and whether it lies inside."""
    x, y = Transformer.from_crs(4326, crs.to_wkt(), always_xy=True).transform(lons, lats)
    rows, cols = rasterio.transform.rowcol(transform, np.asarray(x), np.asarray(y), op=np.floor)
    rows, cols = np.asarray(rows, dtype=int), np.asarray(cols, dtype=int)
    inside = (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
    return rows, cols, inside


def _depth(frame_field, folder):
    path = folder / Path(frame_field["raster_url"]).name
    if file_hash(path) != frame_field["sha256"]:
        raise ValueError(f"{path.name} no longer matches its published SHA-256.")
    with rasterio.open(path) as src:
        values = src.read(1, masked=True).astype(np.float64).filled(0.0)
        grid = (src.transform, src.crs, src.width, src.height)
    values[~np.isfinite(values)] = 0.0
    return values, grid


def _ground_heights(lons, lats):
    """Viewer terrain (FABDEM) height at each point, or None without local terrain.

    These are the same source heights the globe draws, so columns sit on the
    rendered ground. They are for display only and never enter a calculation.
    """
    from .map_context import terrain_metadata
    meta = terrain_metadata()
    if not meta.get("available"):
        return None, None
    heights = np.full(len(lons), np.nan)
    for tile in meta["tiles"]:
        west, south, east, north = tile["bounds"]
        inside = (lons >= west) & (lons < east) & (lats > south) & (lats <= north) & np.isnan(heights)
        if not inside.any():
            continue
        with rasterio.open(tile["path"]) as src:
            for index, value in zip(np.nonzero(inside)[0], src.sample(zip(lons[inside], lats[inside]), masked=True)):
                if not np.ma.is_masked(value[0]):
                    heights[index] = float(value[0])
    return heights, meta["product"]


def _trimmed(values):
    """Per-frame counts without leading and trailing zeros: (first frame, counts)."""
    nonzero = np.nonzero(values)[0]
    if not nonzero.size:
        return None
    return int(nonzero[0]), [int(v) for v in values[nonzero[0]: nonzero[-1] + 1]]


def population_columns(pop_transform, pop_rows, pop_cols, people, flooded, frame_count):
    """Aggregate residents into COLUMN_BLOCK-square columns with per-frame flooded counts.

    `flooded[t]` is a (frames, residents) boolean array for each depth threshold.
    """
    keys = np.stack([pop_rows // COLUMN_BLOCK, pop_cols // COLUMN_BLOCK], axis=1)
    blocks, column = np.unique(keys, axis=0, return_inverse=True)
    column = column.ravel()
    totals = np.bincount(column, weights=people, minlength=len(blocks))
    counts = [np.stack([np.bincount(column, weights=people * wet, minlength=len(blocks)) for wet in by_frame])
              for by_frame in flooded]
    size = COLUMN_BLOCK * pop_transform.a
    west = pop_transform.c + blocks[:, 1] * size
    north = pop_transform.f + blocks[:, 0] * COLUMN_BLOCK * pop_transform.e
    south = north + COLUMN_BLOCK * pop_transform.e
    corner_lons = np.concatenate([west, west + size, west, west + size, west + size / 2])
    corner_lats = np.concatenate([north, north, south, south, (north + south) / 2])
    sampled, ground_source = _ground_heights(corner_lons, corner_lats)
    ground = None if sampled is None else np.nanmin(sampled.reshape(5, -1), axis=0)
    items = []
    for index in range(len(blocks)):
        item = {"bounds": [round(float(west[index]), 6), round(float(south[index]), 6),
                           round(float(west[index] + size), 6), round(float(north[index]), 6)],
                "people": round(float(totals[index]))}
        if ground is not None:
            item["ground_m"] = round(float(ground[index]) - COLUMN_SINK_M, 1) if np.isfinite(ground[index]) else 0.0
        series = [_trimmed(np.rint(by_threshold[:, index])) for by_threshold in counts]
        if series[0]:
            item["flooded"] = [{"from": s[0], "people": s[1]} if s else None for s in series]
        if item["people"] > 0:
            items.append(item)
    return {
        "cell_deg": size, "frames": frame_count, "thresholds_m": DEPTH_THRESHOLDS,
        "ground_source": ground_source, "columns": items,
        "notes": "Residents of each column, excluding cells wet at the start of the event. flooded[i].people[k] "
                 "is the count in water at or above thresholds_m[i] at frame flooded[i].from + k; outside that "
                 "range it is zero. Ground heights are viewer terrain for display only.",
    }


def _cache_key(result_id, population, facilities):
    return f"{METHOD_VERSION}-{result_id}-{population['sha256'][:12]}-{(facilities or {}).get('sha256', 'none')[:12]}"


def exposure_columns(result_id: str):
    """3D population columns for a published result, computed with its exposure."""
    compute_exposure(result_id)
    population, _ = _checked("population")
    facilities, _ = _checked("facilities")
    path = EXPOSURE / "results" / f"{_cache_key(result_id, population, facilities)}-columns.json"
    if not path.is_file():
        compute_exposure(result_id, refresh=True)
    return read_json(path)


def compute_exposure(result_id: str, refresh: bool = False):
    """People and facilities in modelled water for every frame of a published result."""
    folder = (ROOT / "results" / result_id).resolve()
    if not folder.is_relative_to((ROOT / "results").resolve()):
        raise ValueError("Unknown result.")
    result = read_json(folder / "manifest.json")
    if not result:
        raise ValueError(f"No published result named {result_id}.")
    frames = [frame for frame in result["frames"] if "depth" in frame["fields"]]
    if not frames:
        raise ValueError("This result has no published depth rasters.")
    population, population_path = _checked("population")
    facilities, facilities_path = _checked("facilities")
    if not population:
        raise ValueError("Acquire the population layer first: python -m server.exposure acquire")
    key = _cache_key(result_id, population, facilities)
    cache = EXPOSURE / "results" / f"{key}.json"
    if not refresh and (cached := read_json(cache)):
        return cached

    first, (transform, crs, width, height) = _depth(frames[0]["fields"]["depth"], folder)
    with rasterio.open(population_path) as src:
        people = src.read(1).astype(np.float64)
        pop_rows, pop_cols = np.nonzero(np.isfinite(people) & (people > 0))
        lons, lats = rasterio.transform.xy(src.transform, pop_rows, pop_cols)
        pop_transform = src.transform
    people = people[pop_rows, pop_cols]
    rows, cols, inside = _grid_index(transform, crs, width, height, np.asarray(lons), np.asarray(lats))
    rows, cols, people = rows[inside], cols[inside], people[inside]
    pop_rows, pop_cols = pop_rows[inside], pop_cols[inside]
    # Cells already wet in the first published frame are the river at the start
    # of the event (and bank cells where the grids do not line up). Leave them
    # out so the counts measure flooding rather than the channel itself. A
    # steady snapshot starts already flooded, so it names its mapped river
    # channel as the baseline instead.
    baseline = result.get("provenance", {}).get("configuration", {}).get("exposure_baseline")
    if baseline:
        path = ROOT / baseline["path"]
        if not path.is_file() or file_hash(path) != baseline["sha256"]:
            raise ValueError("The result's river-channel baseline is missing or changed.")
        with rasterio.open(path) as src:
            if (src.transform, src.crs, src.width, src.height) != (transform, crs, width, height):
                raise ValueError("The river-channel baseline must share the depth grid.")
            start_wet = src.read(1)[rows, cols] > 0
        baseline_note = baseline["kind"]
    else:
        start_wet = first[rows, cols] > 0
        baseline_note = "cells wet in the first published frame"
    start_wet_people = float(people[start_wet].sum())
    rows, cols, people = rows[~start_wet], cols[~start_wet], people[~start_wet]
    pop_rows, pop_cols = pop_rows[~start_wet], pop_cols[~start_wet]
    wet_people = [np.zeros((len(frames), len(people)), dtype=bool) for _ in DEPTH_THRESHOLDS]

    points = facilities_geojson()["features"] if facilities else []
    if points:
        f_lon = np.array([p["geometry"]["coordinates"][0] for p in points])
        f_lat = np.array([p["geometry"]["coordinates"][1] for p in points])
        f_rows, f_cols, f_inside = _grid_index(transform, crs, width, height, f_lon, f_lat)
        points = [p for p, keep in zip(points, f_inside) if keep]
        f_rows, f_cols = f_rows[f_inside], f_cols[f_inside]
    facility_depths = np.zeros((len(points), len(frames)))

    series = []
    for index, frame in enumerate(frames):
        depth, grid = (first, None) if index == 0 else _depth(frame["fields"]["depth"], folder)
        if grid is not None and grid != (transform, crs, width, height):
            raise ValueError("Depth rasters of one result must share a grid.")
        at_people = depth[rows, cols]
        for wet, threshold in zip(wet_people, DEPTH_THRESHOLDS):
            wet[index] = at_people >= threshold
        entry = {"time": frame["time"], "people": [round(float(people[wet[index]].sum())) for wet in wet_people]}
        if "velocity" in frame["fields"]:
            speed, speed_grid = _depth(frame["fields"]["velocity"], folder)
            if speed_grid != (transform, crs, width, height):
                raise ValueError("Velocity and depth rasters must share a grid.")
            entry["danger"] = round(float(people[hazard_rating(at_people, speed[rows, cols]) >= HAZARD_DANGER].sum()))
        series.append(entry)
        if points:
            facility_depths[:, index] = depth[f_rows, f_cols]

    # Ties on the shallow count go to the frame with more people in deep water.
    peak_index = max(range(len(series)), key=lambda i: tuple(series[i]["people"]))
    items = []
    for point, depths in zip(points, facility_depths):
        top = int(np.argmax(depths))
        flooded = np.nonzero(depths >= FACILITY_FLOOD_M)[0]
        item = {"id": point["id"], **point["properties"], "coordinates": point["geometry"]["coordinates"],
                "max_depth_m": round(float(depths[top]), 2), "max_time": frames[top]["time"],
                "first_flooded_time": frames[int(flooded[0])]["time"] if flooded.size else None}
        if depths[top] >= FACILITY_SERIES_MIN_M:
            item["depth_m"] = [round(float(value), 2) for value in depths]
        items.append(item)
    items.sort(key=lambda item: -item["max_depth_m"])
    exposure = {
        "result_id": result_id,
        "inputs": {"population_sha256": population["sha256"], "population_product": population["product"],
                   "population_license": population["license"],
                   "facilities_sha256": (facilities or {}).get("sha256"),
                   "facilities_osm_timestamp": (facilities or {}).get("osm_timestamp"),
                   "depth_rasters_verified": len(frames)},
        "thresholds_m": DEPTH_THRESHOLDS,
        "hazard": {"rating": "HR = d (v + 0.5) + DF; DF 0.5 where d >= 0.25 m", "danger_threshold": HAZARD_DANGER,
                   "source": "Defra/Environment Agency FD2321 flood risks to people"} if "danger" in series[0] else None,
        "facility_flood_m": FACILITY_FLOOD_M,
        "population_in_extent": round(float(people.sum()) + start_wet_people),
        "population_excluded_start_wet": round(start_wet_people),
        "excluded_baseline": baseline_note,
        "frames": series,
        "peak": {"time": series[peak_index]["time"], "people": series[peak_index]["people"]},
        "facilities": {"in_extent": len(items),
                       "ever_flooded": sum(1 for item in items if item["first_flooded_time"]),
                       "items": items},
        "method": "Each populated WorldPop cell is assigned the depth of the model raster cell containing its centre. "
                  "Cells already wet in the first published frame (the starting river) are excluded. "
                  "Facilities use the depth at their point. Counts are residents of modelled wet cells, rounded to whole people.",
        "notes": "Model-derived exposure from an uncalibrated simulation; not a casualty, displacement or damage estimate.",
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    columns = population_columns(pop_transform, pop_rows, pop_cols, people, wet_people, len(frames))
    exposure["columns"] = {"count": len(columns["columns"]), "cell_deg": columns["cell_deg"],
                           "url": f"/api/results/{result_id}/exposure/columns"}
    write_json(EXPOSURE / "results" / f"{key}-columns.json", {"result_id": result_id, **columns})
    write_json(cache, exposure)
    return exposure


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    acquire = sub.add_parser("acquire", help="Download WorldPop 2022 and OSM facilities for the pilot area")
    acquire.add_argument("layers", nargs="*", help="population, facilities (default: both)")
    compute = sub.add_parser("compute", help="Compute exposure for published results")
    compute.add_argument("result_ids", nargs="+")
    args = parser.parse_args()
    if args.command == "acquire":
        if any(layer not in {"population", "facilities"} for layer in args.layers):
            parser.error("Layers: population, facilities")
        for layer in args.layers or ["population", "facilities"]:
            record = (acquire_population if layer == "population" else acquire_facilities)()
            print(json.dumps({layer: {k: v for k, v in record.items() if k not in {"query"}}}, indent=2))
    else:
        for result_id in args.result_ids:
            exposure = compute_exposure(result_id)
            peak = exposure["peak"]
            print(f"{result_id}: {exposure['population_in_extent']:,} people in extent; peak "
                  f"{peak['people'][0]:,} in >={DEPTH_THRESHOLDS[0]} m at {peak['time']}; "
                  f"{exposure['facilities']['ever_flooded']} of {exposure['facilities']['in_extent']} facilities flooded")


if __name__ == "__main__":
    main()
