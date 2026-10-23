"""Prepare documented roughness zones and require real evidence for survey beds.

python -m server.geometry_inputs prepare|build|run [--survey REVIEW.json]
No synthetic or DEM-derived bathymetry is labeled surveyed.
"""

import argparse
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling

from .models import Scenario
from .store import ROOT, checked_asset, file_hash, read_json, scenario_hash, write_json
from .domain import prepare_domain
from .worker import runtimes, preflight

RULES = Path(__file__).with_name("data") / "roughness-worldcover-v1.json"
FORMAT = "nowshera-geometry-roughness-v1"
RESOLUTION_M = 30


def crosswalk(values, rules):
    """Reject unclassified terrain instead of silently applying a default n."""
    values = np.asarray(values)
    if not np.isfinite(values).all() or not np.equal(values, np.floor(values)).all():
        raise ValueError("Roughness classes must be finite integers.")
    lookup = {r["code"]: r for r in rules["classes"]}
    unknown = sorted(set(int(c) for c in np.unique(values)) - set(lookup))
    if unknown:
        raise ValueError(
            f"Roughness classification contains missing/unsupported classes: {unknown}"
        )
    outputs = {
        key: np.empty(values.shape, dtype="float32") for key in ["n", "low", "high"]
    }
    for code in np.unique(values):
        rule = lookup[int(code)]
        if not 0 < rule["low"] <= rule["n"] <= rule["high"] < 1:
            raise ValueError(f"Invalid documented roughness range for class {code}.")
        for key in outputs:
            outputs[key][values == code] = rule[key]
    return outputs


def surveyed_terrain(review_path, base):
    """Import a reviewed survey raster on the existing hydraulic terrain grid.

    A GIS-reviewed grid is required; this function does not invent a surface
    from sparse points or extend a section beyond its measured coverage.
    """
    review_path = Path(review_path).resolve()
    review = read_json(review_path)
    required = [
        "source",
        "survey_date",
        "survey_method",
        "review",
        "grid_aggregation_review",
        "historical_representativeness_review",
    ]
    if not review or any(not str(review.get(k, "")).strip() for k in required):
        raise ValueError(
            "Survey source, date, method, grid aggregation, historical relevance and review are required."
        )
    date.fromisoformat(review["survey_date"])
    if (
        review.get("channel_bed_measured") is not True
        or review.get("is_dem_derived_bathymetry") is not False
    ):
        raise ValueError(
            "The channel bed must be measured; DEM-derived/estimated bathymetry is not a survey."
        )
    if (
        review.get("vertical_datum") != "EGM2008"
        or review.get("elevation_units") != "m"
    ):
        raise ValueError(
            "Survey elevations must already be reviewed in EGM2008 meters, matching the terrain datum."
        )
    if (
        review.get("source_vertical_datum") != "EGM2008"
        and not str(review.get("vertical_transformation_review", "")).strip()
    ):
        raise ValueError(
            "A source-to-EGM2008 vertical transformation review is required."
        )
    slope = float(review.get("reviewed_boundary_slope", 0))
    if not math.isfinite(slope) or not 0 < slope < 0.02:
        raise ValueError(
            "Provide a reviewed positive boundary normal-depth slope below 0.02."
        )
    paths = {}
    for key in ["terrain", "coverage"]:
        path = (review_path.parent / review[key]).resolve()
        if file_hash(path) != review.get(f"{key}_sha256"):
            raise ValueError(f"Survey {key} hash differs from its review.")
        paths[key] = path
    with rasterio.open(base / "unconditioned-terrain.tif") as reference, rasterio.open(
        base / "channel-mask.tif"
    ) as channel:
        values = reference.read(1).astype("float32")
        channel_mask = channel.read(1) > 0
        arrays = {}
        for key, path in paths.items():
            with rasterio.open(path) as src:
                if (
                    src.count != 1
                    or src.shape != reference.shape
                    or src.crs != reference.crs
                    or not src.transform.almost_equals(reference.transform)
                ):
                    raise ValueError(
                        "Survey terrain and coverage must match the reviewed projected hydraulic grid exactly."
                    )
                arrays[key] = src.read(1, masked=True)
        coverage = arrays["coverage"]
        if (
            np.ma.getmaskarray(coverage).any()
            or not np.isin(coverage.data, [0, 1]).all()
        ):
            raise ValueError(
                "Survey coverage must contain only explicit 0/1 values without nodata."
            )
        covered = coverage.data == 1
        if not covered[channel_mask].all():
            raise ValueError(
                "Survey coverage does not cover the entire resolved model channel; estimated gap filling is refused."
            )
        bed = arrays["terrain"]
        if (
            np.ma.getmaskarray(bed)[covered].any()
            or not np.isfinite(bed.data[covered]).all()
        ):
            raise ValueError(
                "Surveyed terrain has missing/non-finite elevations inside declared survey coverage."
            )
        values[covered] = bed.data[covered]
        return values, {
            **review,
            "review_sha256": file_hash(review_path),
            "resolved_channel_coverage_fraction": 1.0,
            "covered_model_cells": int(covered.sum()),
            "modified_cells": int(np.count_nonzero(values != reference.read(1))),
            "bed_is_surveyed": True,
            "terrain_grid_m": list(reference.res),
        }


def _raster(path, values, affine, crs, nodata, **tags):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype=str(values.dtype),
        transform=affine,
        crs=crs,
        nodata=nodata,
        compress="deflate",
    ) as dst:
        dst.write(values, 1)
        dst.update_tags(**tags)


def prepare(survey=None):
    source = read_json(ROOT / "screening" / "case.json")
    if not source:
        raise ValueError("Prepare the existing Nowshera screening terrain first.")
    base = Path(source["project"])
    terrain = base / "computational-terrain.tif"
    config = read_json(base / "screening.json")
    if file_hash(terrain) != config["computational_terrain_sha256"]:
        raise ValueError("The source hydraulic terrain changed after review.")
    asset, cover_path = checked_asset("landcover")
    rules = read_json(RULES)
    survey_values, survey_review = (
        surveyed_terrain(survey, base) if survey else (None, None)
    )
    identity = {
        "format": FORMAT,
        "rules": file_hash(RULES),
        "landcover": asset["sha256"],
        "terrain": file_hash(terrain),
        "resolution_m": RESOLUTION_M,
        "survey": survey_review,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode()
    ).hexdigest()
    folder = ROOT / "geometry" / fingerprint[:12]
    folder.mkdir(parents=True, exist_ok=True)
    with rasterio.open(terrain) as ref:
        west, south, east, north = ref.bounds
        affine = from_origin(west, north, RESOLUTION_M, RESOLUTION_M)
        dims = (
            math.ceil((north - south) / RESOLUTION_M),
            math.ceil((east - west) / RESOLUTION_M),
        )
        codes = np.zeros(dims, dtype="uint8")
        with rasterio.open(cover_path) as src:
            reproject(
                rasterio.band(src, 1),
                codes,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata,
                dst_transform=affine,
                dst_crs=ref.crs,
                dst_nodata=0,
                resampling=Resampling.nearest,
            )
        mapped = crosswalk(codes, rules)
        _raster(
            folder / "roughness-classes.tif",
            codes,
            affine,
            ref.crs,
            0,
            source=asset["source"],
            classification="ESA WorldCover 2021 v200; nearest neighbor; source already sampled to approximately 30 m",
        )
        for key, values in mapped.items():
            _raster(
                folder / f"manning-{key}.tif",
                values,
                affine,
                ref.crs,
                -9999,
                units="s/m^(1/3)",
                status="uncalibrated roughness prior; not measured",
                rules_sha256=file_hash(RULES),
            )
        if survey_values is not None:
            _raster(
                folder / "computational-terrain.tif",
                survey_values,
                ref.transform,
                ref.crs,
                -9999,
                vertical_datum="EGM2008",
                units="m",
                survey_review_sha256=survey_review["review_sha256"],
            )
        else:
            shutil.copy2(terrain, folder / "computational-terrain.tif")
    classifications = [
        {
            **r,
            "pixels": int(np.count_nonzero(codes == r["code"])),
            "area_m2": int(np.count_nonzero(codes == r["code"])) * RESOLUTION_M**2,
        }
        for r in rules["classes"]
        if np.any(codes == r["code"])
    ]
    report = {
        "format": FORMAT,
        "fingerprint": fingerprint,
        "folder": str(folder),
        "source": identity,
        "terrain_sha256": file_hash(folder / "computational-terrain.tif"),
        "roughness_classes_sha256": file_hash(folder / "roughness-classes.tif"),
        "rules_sha256": file_hash(RULES),
        "classes": classifications,
        "roughness_grid_m": RESOLUTION_M,
        "roughness_is_measured_or_calibrated": False,
        "bed_is_surveyed": survey_review is not None,
        "survey_review": survey_review,
        "normal_depth_slope": (
            survey_review["reviewed_boundary_slope"]
            if survey_review
            else config["channel_geometry"]["slope"]
        ),
        "limitations": rules["limitations"],
        "source_reference": rules["source"],
        "missing_geometry_evidence": (
            []
            if survey_review
            else [
                "No qualified channel survey with georeferencing, bed elevations, datum and reach coverage was located. Estimated bathymetry remains explicitly labeled.",
                "The public AIIB Nowshera-Peshawar report describes bridge surveys but does not supply a usable full-reach georeferenced channel survey for this model.",
            ]
        ),
        "survey_search_reference": "https://www.aiib.org/en/projects/details/2025/_download/Pakistan/ESIA-Vol.-3-Climate-Reports-Detailed-Design-Report-Section-8-Nowshera-Peshawar-Combined-26-12-2024.pdf",
    }
    write_json(folder / "geometry-inputs.json", report)
    write_json(ROOT / "geometry" / "latest.json", report)
    return report


def build(survey=None):
    from ras_commander import GeomLandCover, GeomMesh, RasMap
    import pandas as pd
    from .hecras import AREA, FORMAT as HEC_FORMAT, NAME, _write

    inputs = prepare(survey)
    baseline = read_json(ROOT / "hecras" / "case.json")
    if not baseline:
        raise ValueError(
            "Prepare the original HEC-RAS case before creating its geometry/roughness variant."
        )
    if not preflight(Scenario.model_validate(baseline["scenario"]))["ready"]:
        raise ValueError(
            "The original HEC-RAS case no longer matches its bound inputs; resolve its source review before cloning it."
        )
    original = Path(baseline["project"])
    engine = Path(runtimes()["hec_ras_exe"])
    marker = read_json(original / "hecras-case.json")
    if marker["format"] != HEC_FORMAT or marker["engine_sha256"] != file_hash(engine):
        raise ValueError("The baseline HEC-RAS format/engine differs from its review.")
    if file_hash(original / "conditioned-terrain.tif") != marker["terrain_sha256"]:
        raise ValueError(
            "The baseline HEC-RAS source terrain changed after its review."
        )
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "baseline": baseline["fingerprint"],
                "geometry_inputs": inputs["fingerprint"],
                "engine": file_hash(engine),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    folder = ROOT / "hecras" / fingerprint[:12]
    index = ROOT / "hecras" / "variants" / f"{fingerprint[:12]}.json"
    if index.exists():
        existing = read_json(index)
        if not preflight(Scenario.model_validate(existing["scenario"]))["ready"]:
            raise ValueError(
                "The zoned case changed after binding. Preserve its records and prepare a new input identity."
            )
        return existing
    if (folder / "preparation.json").exists():
        return read_json(folder / "preparation.json")
    # Keep failed native preparations for diagnosis; each attempt has a fresh
    # source directory and cannot inherit a half-created classification HDF.
    project = folder / f"build-{uuid4().hex[:8]}" / "project"
    shutil.copytree(original, project)
    shutil.copy2(
        Path(inputs["folder"]) / "computational-terrain.tif",
        project / "conditioned-terrain.tif",
    )
    shutil.copy2(
        Path(inputs["folder"]) / "roughness-classes.tif",
        project / "roughness-classes.tif",
    )
    shutil.copy2(
        Path(inputs["folder"]) / "geometry-inputs.json",
        project / "geometry-inputs.json",
    )
    if inputs["bed_is_surveyed"]:
        write_json(
            project / "channel-geometry.json",
            {
                "method": "Reviewed survey terrain on the existing hydraulic grid",
                "bed_is_estimated_not_surveyed": False,
                "survey_review": inputs["survey_review"],
                "terrain_sha256": inputs["terrain_sha256"],
            },
        )
    import xml.etree.ElementTree as ET

    mapper = project / f"{NAME}.rasmap"
    tree = ET.parse(mapper)
    tree.getroot().find("RASProjectionFilename").set(
        "Filename", f".\\{NAME}.projection.prj"
    )
    geometry_layer = tree.getroot().find("Geometries/Layer")
    geometry_layer.find("Terrain").set("Filename", ".\\Terrain\\GeometryInput.hdf")
    ET.SubElement(
        geometry_layer,
        "LandCover",
        Filename=".\\Land Classification\\RoughnessZones.hdf",
    )
    tree.write(mapper, encoding="utf-8", xml_declaration=True)
    values = json.loads(json.dumps(baseline["scenario"]))
    values["id"] = f"nowshera-hecras-zoned-{fingerprint[:8]}"
    values["name"] = "Nowshera · HEC-RAS zoned roughness · " + (
        "reviewed survey bed" if inputs["bed_is_surveyed"] else "estimated bed"
    )
    limitations = [n for n in marker["limitations"] if "uniform Manning" not in n]
    if inputs["bed_is_surveyed"]:
        limitations = [n for n in limitations if "surveyed bathymetry" not in n]
        limitations.append(
            "Channel bed uses a reviewed survey raster aggregated to the existing 100 m terrain grid. Survey coverage does not establish surveyed structures, levees or all floodplain elevations."
        )
    limitations += [
        "Spatial roughness uses 2021 WorldCover classes and USACE comparable-class ranges. Values are provisional priors, not field measured or calibrated; no withheld data were used to choose them."
    ] + inputs["limitations"]
    values["provenance"].update(
        notes="\n".join(limitations),
        purpose="Exploratory zoned-roughness HEC-RAS case; uncalibrated",
    )
    scenario = Scenario.model_validate(values)
    prepare_domain(scenario)
    terrain = project / "Terrain" / "GeometryInput.hdf"
    command = [
        str(engine.parent / "RasProcess.exe"),
        "CreateTerrain",
        "units=Meters",
        "stitch=true",
        f"prj={project / (NAME+'.projection.prj')}",
        f"out={terrain}",
        str(project / "conditioned-terrain.tif"),
    ]
    with (folder / "terrain.log").open("w") as log:
        subprocess.run(
            command,
            cwd=engine.parent,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    if not terrain.exists():
        raise ValueError("Native terrain construction failed.")
    table = pd.DataFrame(
        [
            {
                "source_value": r["code"],
                "class_id": r["code"],
                "class_name": r["name"],
                "mannings_n": r["n"],
            }
            for r in inputs["classes"]
        ]
    )
    old_root = os.environ.get("HECRAS_INSTALL_ROOT")
    os.environ["HECRAS_INSTALL_ROOT"] = str(engine.parent)
    try:
        prj = project / f"{NAME}.prj"
        landcover = RasMap.add_landcover_layer(
            prj,
            project / "roughness-classes.tif",
            table,
            cell_size=RESOLUTION_M,
            output_hdf_path=project / "Land Classification" / "RoughnessZones.hdf",
            layer_name="RoughnessZones",
            hecras_version="6.6",
        )
        GeomLandCover.replace_base_mannings_n(
            project / f"{NAME}.g01", table, backup=False
        )
        GeomMesh.set_geometry_association(
            project / f"{NAME}.g01.hdf",
            terrain_hdf_path=terrain,
            landcover_hdf_path=landcover,
            hecras_dir=engine.parent,
        )
        RasMap.remove_terrain_layers(project / f"{NAME}.rasmap")
        RasMap.add_terrain_layer(
            terrain,
            project / f"{NAME}.rasmap",
            layer_name="GeometryInput",
            relative_paths=True,
        )
    finally:
        if old_root is None:
            os.environ.pop("HECRAS_INSTALL_ROOT", None)
        else:
            os.environ["HECRAS_INSTALL_ROOT"] = old_root
    # Native source text remains authoritative. Do not fill solver HDF arrays
    # in Python: HEC-RAS builds the final cell/face Manning values at compute.
    _write(project / f"{NAME}.g01", (project / f"{NAME}.g01").read_text())
    if inputs["bed_is_surveyed"]:
        from ras_commander import RasUnsteady

        RasUnsteady.set_flow_hydrograph_slope(
            project / f"{NAME}.u01",
            inputs["normal_depth_slope"],
            area_2d=AREA,
            bc_line="HMS Inflow",
        )
        RasUnsteady.set_normal_depth_boundary(
            project / f"{NAME}.u01",
            inputs["normal_depth_slope"],
            area_2d=AREA,
            bc_line="Downstream",
        )
    _write(
        project / "REVIEW.md",
        "# HEC-RAS geometry and roughness candidate\n\n"
        + "\n\n".join(limitations)
        + f"\n\nGeometry input fingerprint: {inputs['fingerprint']}\n",
    )
    marker.update(
        scenario_sha256=scenario_hash(scenario),
        terrain_sha256=inputs["terrain_sha256"],
        mannings_n=None,
        limitations=limitations,
        roughness_zones=inputs,
        bed_is_surveyed=inputs["bed_is_surveyed"],
        geometry_inputs_sha256=file_hash(project / "geometry-inputs.json"),
    )
    write_json(project / "hecras-case.json", marker)
    case = {
        "scenario": scenario.model_dump(mode="json"),
        "project": str(project),
        "fingerprint": fingerprint,
        "index_path": str(index),
        "bed_is_surveyed": inputs["bed_is_surveyed"],
        "label": "HEC-RAS · zoned roughness · "
        + ("reviewed survey bed" if inputs["bed_is_surveyed"] else "estimated bed"),
        "ready": False,
        "limitations": limitations,
    }
    write_json(folder / "preparation.json", case)
    return case


def run(survey=None):
    from ras_commander import RasPrj, init_ras_project, RasCmdr
    from .hecras import finalize

    case = build(survey)
    source = Path(case["project"])
    target = source.parent / f"run-{uuid4().hex[:8]}"
    shutil.copytree(source, target)
    write_json(source.parent / "latest-run.json", {**case, "run_project": str(target)})
    ras = RasPrj()
    init_ras_project(str(target), runtimes()["hec_ras_exe"], ras_object=ras)
    success = RasCmdr.compute_plan(
        "01",
        ras_object=ras,
        verify=True,
        force_geompre=True,
        num_cores=2,
        max_runtime=7200,
        stream_callback=lambda line: print(line, flush=True),
    )
    if not success:
        raise ValueError(
            "The native HEC-RAS geometry/roughness candidate did not complete."
        )
    return finalize(case, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "build", "run"])
    parser.add_argument(
        "--survey",
        type=Path,
        help="Reviewed survey terrain/coverage bundle; see docs/GEOMETRY_ROUGHNESS.md.",
    )
    args = parser.parse_args()
    action = {"prepare": prepare, "build": build, "run": run}[args.command]
    result = action(args.survey)
    if args.command == "run":
        print(
            json.dumps(
                {
                    "result_id": result["id"],
                    "frames": len(result["frames"]),
                    "bed_is_surveyed": result["provenance"]["geometry_and_roughness"][
                        "bed_is_surveyed"
                    ],
                }
            )
        )
        return
    print(
        json.dumps(
            {
                "folder": result.get("folder", result.get("project")),
                "id": result.get("id"),
                "ready": result.get("ready"),
                "bed_is_surveyed": result.get("bed_is_surveyed", False),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
