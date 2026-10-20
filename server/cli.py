"""Local asset registration and model workflow: python -m server.cli --help."""
import argparse
import json
from pathlib import Path
import shutil
import httpx
import rasterio
from .domain import bounds_for, clip_raster, geojson_geometry, prepare_domain
from .models import Scenario
from .publish import inspect_hdf, publish
from .store import ROOT, assets, file_hash, write_json
from .worker import bind, preflight
from .hydrology import compute_hms

KINDS = ["dem", "hydrography", "catchment", "soil", "moisture", "rainfall", "landcover", "inflow", "validation"]


def register(kind, source_path, source, license, product):
    source_path = Path(source_path).resolve()
    if not source.strip() or not license.strip() or not product.strip():
        raise ValueError("Source, product and license are mandatory provenance.")
    metadata = {}
    if kind in {"hydrography", "catchment"}:
        allowed = {"LineString", "MultiLineString"} if kind == "hydrography" else {"Polygon", "MultiPolygon"}
        geojson_geometry(source_path, allowed)
    elif kind != "inflow":
        with rasterio.open(source_path) as raster:
            if not raster.crs:
                raise ValueError("Raster needs a CRS.")
            metadata = {"crs": str(raster.crs), "bounds": list(raster.bounds), "bands": raster.count}
    else:
        import csv
        import math
        from datetime import datetime
        rows = list(csv.DictReader(source_path.open(encoding="utf-8-sig", newline="")))
        if not rows:
            raise ValueError("Inflow CSV is empty.")
        seen = set()
        coverage = {}
        for row in rows:
            time = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            discharge = float(row["discharge_m3s"])
            if time.tzinfo is None or not math.isfinite(discharge) or discharge < 0 or row["value_type"] not in {"observed", "modeled"} or not row["source"].strip():
                raise ValueError("Inflow requires timezone, finite SI discharge, source and observed/modeled value_type.")
            identity = (row["station_id"], time)
            if identity in seen:
                raise ValueError("Duplicate station/time in inflow.")
            seen.add(identity)
            coverage.setdefault(row["station_id"], []).append(time)
        metadata = {"stations": sorted({r["station_id"] for r in rows}), "rows": len(rows),
                    "coverage": {station: [min(times).isoformat(), max(times).isoformat()] for station, times in coverage.items()}}
    digest = file_hash(source_path)
    target = ROOT / "assets" / f"{kind}-{digest[:16]}{source_path.suffix.lower()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if source_path != target:
        shutil.copy2(source_path, target)
    record = {"path": target.relative_to(ROOT).as_posix(), "sha256": digest, "source": source,
              "license": license, "product": product, "metadata": metadata}
    catalog = assets()
    catalog[kind] = record
    write_json(ROOT / "assets.json", catalog)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    asset = commands.add_parser("register", help="Copy a local documented raster, vector or boundary CSV into the workspace")
    asset.add_argument("kind", choices=KINDS)
    asset.add_argument("path", type=Path)
    for flag in ["source", "license", "product"]:
        asset.add_argument(f"--{flag}", required=True)
    for name in ["domain", "preflight"]:
        p = commands.add_parser(name)
        p.add_argument("scenario", type=Path)
    p = commands.add_parser("bind", help="Bind an externally prepared model to an exact scenario digest")
    p.add_argument("scenario", type=Path)
    p.add_argument("project", type=Path)
    p.add_argument("--plan", default="01")
    p.add_argument("--review", required=True, help="Review reference covering mesh, hydrology, structures, conditions and timestep")
    p = commands.add_parser("publish", help="Publish RAS Mapper / LISFLOOD raster exports using an export manifest")
    p.add_argument("manifest", type=Path)
    p = commands.add_parser("inspect-hdf")
    p.add_argument("path", type=Path)
    p = commands.add_parser("compute-hms", help="Run an existing reviewed HEC-HMS simulation using bundled Java/Jython")
    p.add_argument("scenario", type=Path)
    p.add_argument("project", type=Path, help="Path to the prepared .hms project")
    p.add_argument("--run", required=True)
    p.add_argument("--installation", type=Path, required=True)
    p.add_argument("--review", required=True)
    p = commands.add_parser("stac-import", help="Clip a public STAC COG asset; authenticated services require pre-downloaded data")
    p.add_argument("scenario", type=Path)
    p.add_argument("item_url")
    p.add_argument("asset_key")
    p.add_argument("--kind", choices=["dem", "soil", "moisture", "rainfall", "landcover", "validation"], required=True)
    p.add_argument("--license", required=True)
    args = parser.parse_args()
    if args.command == "register":
        result = register(args.kind, args.path, args.source, args.license, args.product)
    elif args.command in {"domain", "preflight", "bind", "stac-import", "compute-hms"}:
        scenario = Scenario.model_validate_json(args.scenario.read_text(encoding="utf-8-sig"))
        if args.command == "domain":
            result = prepare_domain(scenario)
        elif args.command == "preflight":
            result = preflight(scenario)
        elif args.command == "bind":
            result = bind(scenario, args.project, args.plan, args.review)
        elif args.command == "compute-hms":
            result = compute_hms(scenario, args.project, args.run, args.installation, args.review)
        else:
            response = httpx.get(args.item_url, follow_redirects=True, timeout=60)
            response.raise_for_status()
            item = response.json()
            href = item["assets"][args.asset_key]["href"]
            from urllib.parse import urljoin
            href = urljoin(args.item_url, href)
            if not href.startswith("https://"):
                raise ValueError("Public STAC import requires an HTTPS COG asset.")
            temp = ROOT / "imports" / f"{args.kind}.tif"
            clip_raster(href, temp, bounds_for(scenario))
            result = register(args.kind, temp, args.item_url, args.license, item["id"])
    elif args.command == "publish":
        result = publish(args.manifest)
    else:
        result = inspect_hdf(args.path)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
