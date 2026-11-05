"""Tributary audit: which real streams enter a hydraulic model, and which get water.

Run `python -m server.tributaries --help`.

A 2D model only receives water through its declared inflow boundaries. Every
HydroRIVERS reach that crosses into the published model footprint is listed
with its drainage area and long-term modelled discharge, and is matched against
the model's actual inflow boundary lines (HEC-RAS geometry/unsteady files or the
LISFLOOD-FP .bci file). A stream that enters away from every inflow line is
**unrepresented**: the model gives it no water. Nothing here changes a model.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

import rasterio
from pyproj import Transformer
import numpy as np
import shapely
from shapely.geometry import LineString, Point, box, mapping, shape

from .acquire import BASE
from .store import ROOT, checked_asset, file_hash, read_json, write_json

AUDITS = ROOT / "tributaries"
WATERWAYS = AUDITS / "osm-waterways.geojson"
PDMA = BASE / "references" / "pdma-dwr-2022" / "untimed-reference-observations.csv"
CUSECS_TO_M3S = 0.028316846592
# A crossing within this distance of an inflow line is fed by that line.
BOUNDARY_TOLERANCE_M = 500
NAME_DISTANCE_M = 750
MAJOR_UPLAND_KM2 = 500
METHOD_VERSION = "v2"
ALIASES = Path(__file__).with_name("data") / "waterway-aliases.json"
# Names are looked up only around each hydraulic reach (Nowshera, then the
# Warsak below-dam window); a basin-wide waterway query is too heavy for the
# public Overpass servers.
NAME_BOUNDS = [[71.85, 33.90, 72.12, 34.15], [71.38, 33.98, 71.60, 34.35]]


def transform(function, geometry):
    """Reproject a geometry with a pyproj transform function."""
    return shapely.transform(geometry, lambda xy: np.column_stack(function(xy[:, 0], xy[:, 1])))


def acquire_waterway_names(bounds=NAME_BOUNDS):
    """Named OSM waterways around each hydraulic reach, used only to label HydroRIVERS reaches."""
    from .exposure import _overpass

    elements, sources, data = {}, [], {}
    for west, south, east, north in bounds:
        query = (f'[out:json][timeout:90];way["waterway"~"^(river|stream|canal|drain)$"]["name"]'
                 f'({south},{west},{north},{east});out tags geom;')
        source, response = _overpass(query)
        data = response.json()
        sources.append(source)
        for element in data.get("elements", []):
            elements[element["id"]] = element
    source = sources[0] if len(set(sources)) == 1 else ", ".join(sorted(set(sources)))
    features = []
    for element in sorted(elements.values(), key=lambda item: item["id"]):
        coordinates = [[point["lon"], point["lat"]] for point in element.get("geometry", [])]
        if len(coordinates) < 2:
            continue
        tags = element.get("tags", {})
        features.append({"type": "Feature", "id": f"osm:way/{element['id']}",
                         "geometry": {"type": "LineString", "coordinates": coordinates},
                         "properties": {"name": tags.get("name:en") or tags["name"], "waterway": tags["waterway"]}})
    write_json(WATERWAYS, {"type": "FeatureCollection", "features": features,
                           "source": source, "license": "ODbL 1.0; © OpenStreetMap contributors",
                           "osm_timestamp": data.get("osm3s", {}).get("timestamp_osm_base")})
    return {"path": str(WATERWAYS), "sha256": file_hash(WATERWAYS), "count": len(features)}


def _hecras_inflows(project: Path):
    """Inflow BC lines: lines whose unsteady boundary is a flow hydrograph."""
    flows = set()
    for flow_file in project.glob("*.u[0-9][0-9]"):
        current = None
        for line in flow_file.read_text(errors="replace").splitlines():
            if line.startswith("Boundary Location="):
                current = line.split(",")[-1].strip()
            elif current and line.startswith(("Flow Hydrograph=", "Lateral Inflow Hydrograph=", "Uniform Lateral Inflow")):
                flows.add(current)
    lines = []
    for geometry in project.glob("*.g[0-9][0-9]"):
        text = geometry.read_text(errors="replace").splitlines()
        for index, line in enumerate(text):
            if not line.startswith("BC Line Name="):
                continue
            name = line.split("=", 1)[1].strip()
            arc = next((i for i in range(index, min(index + 12, len(text))) if text[i].startswith("BC Line Arc=")), None)
            if name not in flows or arc is None:
                continue
            count = int(text[arc].split("=")[1])
            # HEC-RAS writes coordinates in 16-character fields, two points per line.
            rows = text[arc + 1: arc + 1 + (count + 1) // 2]
            numbers = [float(row[i:i + 16]) for row in rows for i in range(0, len(row.rstrip()), 16)]
            points = list(zip(numbers[0::2], numbers[1::2]))[:count]
            if len(points) >= 2:
                lines.append({"name": name, "line": LineString(points)})
    return lines


def _lisflood_inflows(project: Path):
    """QVAR/QFIX/HVAR/HFIX edges of a LISFLOOD-FP .bci file, as model-CRS lines."""
    header = {}
    for line in (project / "terrain.asc").read_text().splitlines()[:6]:
        key, value = line.split()
        header[key.lower()] = float(value)
    west, south = header["xllcorner"], header["yllcorner"]
    east = west + header["ncols"] * header["cellsize"]
    north = south + header["nrows"] * header["cellsize"]
    lines = []
    for row in (project / "boundaries.bci").read_text().splitlines():
        parts = row.split()
        if len(parts) < 4 or parts[3] not in {"QVAR", "QFIX", "HVAR", "HFIX"}:
            continue
        edge, low, high = parts[0], float(parts[1]), float(parts[2])
        segment = {"W": [(west, low), (west, high)], "E": [(east, low), (east, high)],
                   "N": [(low, north), (high, north)], "S": [(low, south), (high, south)]}.get(edge)
        if segment:
            lines.append({"name": parts[4] if len(parts) > 4 else f"{edge} inflow", "line": LineString(segment)})
    return lines


def inflow_boundaries(engine: str, project: Path):
    if engine == "HEC-RAS 2D":
        return _hecras_inflows(project)
    if engine == "LISFLOOD-FP":
        return _lisflood_inflows(project)
    raise ValueError(f"No boundary reader for {engine}.")


def _gauge_x(engine, project):
    if engine == "HEC-RAS 2D":
        for geometry in project.glob("*.g[0-9][0-9]"):
            text = geometry.read_text(errors="replace")
            match = re.search(r"Reference Line Name=.*?\n(?:.*\n)*?Reference Line Arc=\s*\d+\s*\n\s*([-\d.]+)", text)
            if match:
                return float(match.group(1))
    gauge = project / "nowshera.gauge"
    if gauge.is_file():
        return float(gauge.read_text().splitlines()[1].split()[0])
    return None


def _pdma_reference(label):
    """Largest untimed PDMA daily reading for a river label; reference only."""
    if not label or not PDMA.is_file():
        return None
    rows = [row for row in csv.DictReader(PDMA.open(encoding="utf-8")) if row["river"].strip().lower() == label.lower()]
    if not rows:
        return None
    top = max(rows, key=lambda row: float(row["discharge_cusecs"]))
    return {"river": top["river"], "location": top["location"], "report_date": top["report_date"],
            "max_discharge_cusecs": float(top["discharge_cusecs"]),
            "max_discharge_m3s": round(float(top["discharge_cusecs"]) * CUSECS_TO_M3S, 1),
            "reports": len({row["report_date"] for row in rows}), "source": top["source"],
            "status": "Untimed daily report value; reference only, never model forcing."}


def audit(result_id: str):
    folder = (ROOT / "results" / result_id).resolve()
    if not folder.is_relative_to((ROOT / "results").resolve()):
        raise ValueError("Unknown result.")
    result = read_json(folder / "manifest.json")
    if not result:
        raise ValueError(f"No published result named {result_id}.")
    binding = read_json(ROOT / "bindings" / f"{result['scenario_sha256']}.json")
    if not binding:
        raise ValueError("The result has no model binding; its boundaries cannot be read.")
    project = Path(binding["project"])
    hydro_asset, hydro_path = checked_asset("hydrography")
    names_hash = file_hash(WATERWAYS)[:8] + file_hash(ALIASES)[:4] if WATERWAYS.is_file() else "none"
    cache = AUDITS / f"{METHOD_VERSION}-{result_id}-{hydro_asset['sha256'][:12]}-{names_hash}.json"
    aliases = read_json(ALIASES, {})
    if cached := read_json(cache):
        return cached

    frame = next(frame["fields"]["depth"] for frame in result["frames"] if "depth" in frame["fields"])
    with rasterio.open(folder / Path(frame["raster_url"]).name) as src:
        footprint = box(*src.bounds)
        crs = src.crs.to_wkt()
    to_model = Transformer.from_crs(4326, crs, always_xy=True).transform
    to_wgs = Transformer.from_crs(crs, 4326, always_xy=True).transform
    boundaries = inflow_boundaries(binding["engine"], project)
    gauge_x = _gauge_x(binding["engine"], project)

    reaches = {}
    for feature in read_json(hydro_path)["features"]:
        props = feature["properties"]
        reaches[props["HYRIV_ID"]] = (transform(to_model, shape(feature["geometry"])), props)
    named = []
    if WATERWAYS.is_file():
        named = [(transform(to_model, shape(f["geometry"])), f["properties"]["name"])
                 for f in read_json(WATERWAYS)["features"]]

    edge = footprint.exterior
    entering = []
    for geometry, props in reaches.values():
        start = Point(geometry.coords[0])
        if footprint.contains(start) or not geometry.intersects(footprint):
            continue
        crossing = geometry.intersection(edge)
        crossing = min(getattr(crossing, "geoms", [crossing]), key=start.distance)
        crossing = crossing if isinstance(crossing, Point) else Point(crossing.coords[0])
        fed = [b for b in boundaries if b["line"].distance(crossing) <= BOUNDARY_TOLERANCE_M]
        # Follow the network inside the footprint to the reach this stream joins.
        downstream, guard = props, 0
        while guard < 50 and downstream["NEXT_DOWN"] in reaches:
            nxt_geometry, nxt = reaches[downstream["NEXT_DOWN"]]
            if nxt["UPLAND_SKM"] > 1.5 * downstream["UPLAND_SKM"] + 50 or not footprint.contains(Point(nxt_geometry.coords[0])):
                break
            downstream, guard = nxt, guard + 1
        end = Point(reaches[downstream["HYRIV_ID"]][0].coords[-1])
        name, name_distance = None, None
        if named:
            geometry_near, label = min(named, key=lambda item: item[0].distance(crossing))
            if geometry_near.distance(crossing) <= NAME_DISTANCE_M:
                name, name_distance = label, round(geometry_near.distance(crossing))
        side = min({"west": abs(crossing.x - footprint.bounds[0]), "south": abs(crossing.y - footprint.bounds[1]),
                    "east": abs(crossing.x - footprint.bounds[2]), "north": abs(crossing.y - footprint.bounds[3])}.items(),
                   key=lambda item: item[1])[0]
        inside = geometry.intersection(footprint)
        alias = aliases.get(name, {}) if name else {}
        entering.append({
            "hyriv_id": props["HYRIV_ID"], "name": alias.get("en", name), "osm_name": name,
            "name_source": f"OpenStreetMap waterway within {name_distance} m" if name else None,
            "upland_km2": float(props["UPLAND_SKM"]), "mean_discharge_m3s": float(props["DIS_AV_CMS"]),
            "strahler_order": int(props["ORD_STRA"]), "edge": side,
            "crossing": [round(v, 6) for v in to_wgs(crossing.x, crossing.y)],
            "joins": [round(v, 6) for v in to_wgs(end.x, end.y)],
            "downstream_of_gauge": None if gauge_x is None else bool(end.x > gauge_x),
            "represented": bool(fed), "boundary": fed[0]["name"] if fed else None,
            "significance": "major" if props["UPLAND_SKM"] >= MAJOR_UPLAND_KM2 else "minor",
            "geometry": mapping(transform(to_wgs, geometry)),
            "inside_length_km": round(inside.length / 1000, 2),
            "reference_observation": _pdma_reference(alias.get("pdma")) if props["UPLAND_SKM"] >= MAJOR_UPLAND_KM2 else None,
        })
    entering.sort(key=lambda item: -item["upland_km2"])
    represented = [item for item in entering if item["represented"]]
    missing = [item for item in entering if not item["represented"]]
    main = represented[0] if represented else None
    report = {
        "result_id": result_id, "engine": binding["engine"], "project_sha256_source": binding.get("project_sha256"),
        "hydrography": {"product": hydro_asset["product"], "sha256": hydro_asset["sha256"]},
        "inflow_boundaries": [{"name": b["name"],
                               "coordinates": [list(map(lambda v: round(v, 6), to_wgs(*c))) for c in b["line"].coords]}
                              for b in boundaries],
        "entering": entering,
        "summary": {
            "entering": len(entering), "represented": len(represented), "unrepresented": len(missing),
            "unrepresented_major": [item["name"] or f"HydroRIVERS {item['hyriv_id']}" for item in missing if item["significance"] == "major"],
            "unrepresented_upland_km2": round(sum(item["upland_km2"] for item in missing), 1),
            "main_inflow_upland_km2": main["upland_km2"] if main else None,
            "unrepresented_mean_discharge_m3s": round(sum(item["mean_discharge_m3s"] for item in missing), 2),
            "main_inflow_mean_discharge_m3s": main["mean_discharge_m3s"] if main else None,
        },
        "method": "HydroRIVERS reaches starting outside and entering the published depth-raster footprint. A reach is "
                  f"represented when its edge crossing lies within {BOUNDARY_TOLERANCE_M} m of a declared inflow line. "
                  "Mean discharge is HydroRIVERS' long-term modelled average, not a 2022 flow.",
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(cache, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("names", help="Download named OSM waterways used to label reaches")
    run = sub.add_parser("audit", help="Audit tributaries entering published results")
    run.add_argument("result_ids", nargs="+")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.command == "names":
        print(json.dumps(acquire_waterway_names(), indent=2))
        return
    for result_id in args.result_ids:
        report = audit(result_id)
        print(result_id)
        for item in report["entering"]:
            label = item["name"] or f"HydroRIVERS {item['hyriv_id']}"
            state = f"fed by '{item['boundary']}'" if item["represented"] else "NO INFLOW"
            print(f"  {label:32} {item['upland_km2']:>9,.0f} km2  mean {item['mean_discharge_m3s']:>8.1f} m3/s  "
                  f"{item['edge']:5}  {state}")


if __name__ == "__main__":
    main()
