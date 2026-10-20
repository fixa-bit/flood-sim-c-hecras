"""Verify downloaded inputs without declaring hydraulic or historical skill."""
import csv
import json
import math
from pathlib import Path
import numpy as np
import rasterio
from shapely.geometry import box, shape
from .acquire import BASE
from .domain import bounds_for, prepare_domain
from .models import Scenario
from .store import ROOT, assets, checked_asset, file_hash, read_json, write_json
from .worker import preflight


def main():
    scenario = Scenario.model_validate_json((BASE / "scenario.json").read_text(encoding="utf-8"))
    study_bounds = box(*bounds_for(scenario))
    records = []
    for key in ["dem", "hydrography", "catchment", "soil", "landcover", "rainfall"]:
        item, path = checked_asset(key)
        record = {"asset": key, "sha256_verified": True, "path": str(path), "product": item["product"]}
        if key not in {"hydrography", "catchment"}:
            with rasterio.open(path) as src:
                values = src.read(masked=True)
                valid = values.compressed()
                if not src.crs or not len(valid) or not np.isfinite(valid).all():
                    raise ValueError(f"Invalid/nonfinite raster input: {key}")
                if str(src.crs) != "EPSG:4326" or not box(*src.bounds).covers(study_bounds):
                    raise ValueError(f"Prepared {key} does not cover the WGS84 pilot domain.")
                if key == "rainfall" and (src.count != 16 or valid.min() < 0):
                    raise ValueError("Expected 16 nonnegative daily rainfall bands.")
                if key == "rainfall":
                    _, catchment_path = checked_asset("catchment")
                    upstream = shape(read_json(catchment_path)["features"][0]["geometry"])
                    if not box(*src.bounds).covers(upstream):
                        raise ValueError("Rainfall misses part of the candidate contributing catchment.")
                    if [src.tags(band).get("date") for band in range(1, 17)] != [f"2022-08-{day:02d}" for day in range(20, 32)] + [f"2022-09-{day:02d}" for day in range(1, 5)]:
                        raise ValueError("Rainfall daily timestamps are incomplete or unordered.")
                    record["candidate_upstream_extent_covered"] = True
                if key == "landcover" and not set(np.unique(valid)).issubset({10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}):
                    raise ValueError("Unexpected ESA WorldCover class code.")
                if key == "dem" and values.count() != values.size:
                    raise ValueError("Prepared pilot DEM contains a missing value.")
                if key == "dem":
                    native_path = next((BASE / "raw" / "fabdem").glob("*.tif"))
                    with rasterio.open(native_path) as native:
                        offsets = [(src.transform.c - native.transform.c) / native.res[0],
                                   (src.transform.f - native.transform.f) / native.res[1]]
                        if src.crs != native.crs or not np.allclose(src.res, native.res, rtol=0, atol=1e-12) or not all(math.isclose(value, round(value), abs_tol=1e-6) for value in offsets):
                            raise ValueError("Prepared terrain changed the native FABDEM grid.")
                    record["native_grid_alignment"] = True
                record.update(crs=str(src.crs), bands=src.count, valid_fraction=float(values.count() / values.size), minimum=float(valid.min()), maximum=float(valid.max()))
        else:
            data = read_json(path)
            if not data["features"] or not all(shape(feature["geometry"]).is_valid for feature in data["features"]):
                raise ValueError(f"Invalid source vector: {key}")
            record.update(features=len(data["features"]))
            if key == "catchment":
                record["exact_gauge_delineation"] = data["features"][0]["properties"]["outlet_exact"]
        records.append(record)
    domain = prepare_domain(scenario)
    index = read_json(BASE / "references" / "ffc-bulletin-index.json")
    for doc in index["documents"]:
        if "path" in doc and file_hash(Path(doc["path"])) != doc["sha256"]:
            raise ValueError("Downloaded bulletin hash changed.")
    with Path(index["csv"]).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    keys = {(row["time"], row["station_id"]) for row in rows}
    if len(keys) != len(rows) or not all(abs(float(row["discharge_m3s"]) - float(row["discharge_cusecs"]) * 0.028316846592) < 1e-8 for row in rows):
        raise ValueError("Gauge timestamp uniqueness or SI conversion check failed.")
    check = preflight(scenario)
    result = {"data_checks_passed": True, "scenario": str(BASE / "scenario.json"), "assets": records,
              "bulletin_documents": sum("path" in doc for doc in index["documents"]), "gauge_snapshot_rows": len(rows),
              "gauge_stations": len({row["station_id"] for row in rows}), "snapped_outlet": domain["snapped_outlet"],
              "domain_artifact": str(ROOT / "domains" / domain["scenario_sha256"] / "domain.json"),
              "hydraulic_ready": check["ready"], "unresolved_requirements": [item for item in check["checks"] if not item["passed"]],
              "note": "Checks establish file integrity and geospatial usability, not calibration, flood-model validity or a completed 2022 replay."}
    write_json(BASE / "data-verification.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "assets"}, indent=2))


if __name__ == "__main__":
    main()
