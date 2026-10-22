"""Build and run an exploratory HEC-RAS 6.6 Nowshera 2D model.

Geometry, mesh, terrain tables and hydraulics are computed by the installed
HEC tools. The source channel bed is estimated, not surveyed or calibrated.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import re
from uuid import uuid4

import numpy as np
import rasterio

from .models import Scenario
from .store import ROOT, read_json, write_json, file_hash, scenario_hash
from .worker import runtimes, bind, preflight
from .domain import prepare_domain

AREA = "Nowshera"
NAME = "Nowshera"
FORMAT = "nowshera-hecras-swe-v4"
MESH_M = 200
WARMUP_HOURS = 72
INDEX = ROOT / "hecras" / "case.json"
LIMITATIONS = [
    "Exploratory HEC-RAS 6.6 full shallow-water model; uncalibrated and not an operational forecast.",
    "FABDEM channel bed is conditioned using estimated channel dimensions; surveyed bathymetry, levees and structures are unavailable.",
    "HEC-HMS aggregate inflow is modeled from sparse daily gauges; upstream withheld KGE is below its target. Aggregate flow is imposed at the western model edge without additional tributary inflows.",
    "200 m computational mesh with 100 m conditioned terrain; uniform Manning n=0.04 is an analyst assumption, not locally calibrated roughness.",
    "Gauge-driven case: rainfall, infiltration and soil moisture are unused. Downstream normal-depth slope is terrain-derived, not an observed stage boundary.",
    "72-hour constant-inflow warm-up precedes the event. Independent flood extent and water-level validation remain unavailable.",
]


def _write(path, text):
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))


def prepare():
    from ras_commander import (
        create_project_from_template,
        GeomStorage,
        GeomMesh,
        GeomBcLines,
        GeomReferenceFeatures,
        RasUnsteady,
    )

    source = read_json(ROOT / "screening" / "case.json")
    if not source:
        raise ValueError("Prepare the public-data screening inputs first.")
    base = Path(source["project"])
    terrain = base / "computational-terrain.tif"
    config = read_json(base / "screening.json")
    if file_hash(terrain) != config["computational_terrain_sha256"]:
        raise ValueError(
            "Source conditioned terrain changed after its preparation review."
        )
    from .study import STUDY

    routing = read_json(STUDY / "routing-calibration.json")
    if file_hash(STUDY / "hms-nowshera-hourly-modeled.csv") != routing.get(
        "output_csv_sha256"
    ):
        raise ValueError(
            "HEC-HMS inflow changed after the routing study; recompute and review it first."
        )
    engine = Path(runtimes()["hec_ras_exe"])
    if not engine.is_file():
        raise ValueError("HEC-RAS is not installed.")
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "format": FORMAT,
                "mesh_m": MESH_M,
                "terrain": file_hash(terrain),
                "inflow": source["scenario"]["forcing"]["inflow_asset"],
                "engine": file_hash(engine),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    folder = ROOT / "hecras" / fingerprint[:12]
    project = folder / "project"
    values = json.loads(json.dumps(source["scenario"]))
    values["id"] = f"nowshera-hecras-{fingerprint[:8]}"
    values["name"] = "Nowshera · HEC-RAS 2D exploratory SWE"
    values["domain"]["mesh_m"] = MESH_M
    values["hydraulics"].update(
        engine="HEC-RAS 2D", equations="full SWE", manning_source="Prepared model"
    )
    values["provenance"].update(
        notes="\n".join(LIMITATIONS),
        purpose="Exploratory HEC-RAS full SWE case; uncalibrated",
    )
    scenario = Scenario.model_validate(values)
    existing = read_json(INDEX)
    if existing and existing.get("fingerprint") == fingerprint:
        if preflight(scenario)["ready"]:
            return existing
        raise ValueError(
            "The registered HEC case changed after binding. Preserve its records and prepare a new case rather than rebinding changed inputs to old output."
        )
    if (folder / "preparation.json").exists():
        return read_json(folder / "preparation.json")
    prepare_domain(scenario)
    project.mkdir(parents=True, exist_ok=True)
    create_project_from_template(
        project,
        NAME,
        version="6.6",
        target_crs=scenario.domain.model_crs,
        overwrite=True,
    )
    shutil.copy2(terrain, project / "conditioned-terrain.tif")
    shutil.copy2(base / "channel-geometry.json", project / "channel-geometry.json")
    with rasterio.open(terrain) as src:
        west, south, east, north = src.bounds
        # Native face-property sampling needs terrain on both sides of a face.
        # Keep the perimeter inside the source grid by a full terrain pixel.
        west += src.res[0]
        east -= src.res[0]
        south += src.res[1]
        north -= src.res[1]
    geom = project / f"{NAME}.g01"
    GeomStorage.set_2d_flow_area_perimeter(
        geom,
        AREA,
        coordinates=[
            (west, south),
            (east, south),
            (east, north),
            (west, north),
            (west, south),
        ],
        point_generation_data=[MESH_M, MESH_M, 0, 0],
    )
    GeomStorage.set_2d_flow_area_settings(geom, AREA, mannings_n=0.04)
    GeomStorage.repair_viewing_rectangle_from_2d_areas(geom)
    result = GeomMesh.generate_computation_points(
        geom, mesh_name=AREA, cell_size=MESH_M, hecras_dir=engine.parent
    )
    print("Mesh seeds:", result, flush=True)
    line = (base / "boundaries.bci").read_text().splitlines()[0].split()
    lo, hi = float(line[1]), float(line[2])
    GeomBcLines.add_bc_lines(
        geom,
        [
            {
                "name": "HMS Inflow",
                "storage_area": AREA,
                "coordinates": [(west, hi), (west, lo)],
            },
            {
                "name": "Downstream",
                "storage_area": AREA,
                "coordinates": [(east, south), (east, north)],
            },
        ],
    )
    gauge_x = float((base / "nowshera.gauge").read_text().splitlines()[1].split()[0])
    GeomReferenceFeatures.add_reference_lines(
        geom,
        [
            {
                "name": "Nowshera gauge",
                "coordinates": [(gauge_x, north), (gauge_x, south)],
            }
        ],
        storage_area=AREA,
    )
    start = scenario.time.start - timedelta(hours=WARMUP_HOURS)
    end = scenario.time.end
    prj = project / f"{NAME}.prj"
    _write(
        prj, prj.read_text() + "\nCurrent Plan=p01\nPlan File=p01\nUnsteady File=u01\n"
    )
    plan = {
        "Plan Title": "Nowshera exploratory full SWE",
        "Program Version": "6.60",
        "Short Identifier": "NowsheraSWE",
        "Simulation Date": f"{start:%d%b%Y},{start:%H%M},{end:%d%b%Y},{end:%H%M}".upper(),
        "Geom File": "g01",
        "Flow File": "u01",
        "Computation Interval": "30SEC",
        "Output Interval": "1HOUR",
        "Instantaneous Interval": "1HOUR",
        "Mapping Interval": "1HOUR",
        "Run HTab": "-1",
        "Run UNet": "-1",
        "Run PostProcess": "-1",
        "Run RASMapper": "-1",
        "Run WQNet": "0",
        "CheckData": "True",
        "UNET Theta": "1",
        "UNET Theta Warmup": "1",
        "UNET ZTol": "0.01",
        "UNET ZSATol": "0.01",
        "UNET Gravity": "9.80665",
        "UNET MaxCRTS": "20",
        "UNET WFStab": "2",
        "UNET SFStab": "1",
        "UNET WFX": "1",
        "UNET SFX": "1",
        "UNET DZMax Abort": "30",
        "UNET DSS MLevel": "4",
        "UNET MxIter": "20",
        "UNET Use Existing IB Tables": "-1",
        "UNET D2 Name": AREA,
        "UNET D2 Equation": "1",
        "UNET D2 Theta": "1",
        "UNET D2 Theta Warmup": "1",
        "UNET D2 Z Tol": "0.01",
        "UNET D2 Volume Tol": "0.01",
        "UNET D2 Max Iterations": "20",
        "UNET D2 TotalICTime": "0",
        "UNET D2 RampUpFraction": "0.1",
        "UNET D2 TimeSlices": "1",
        "UNET D2 BCVolumeCheck": "-1",
        "UNET D2 Cores": "2",
        "UNET D2 Latitude": "34",
        "UNET D2 SolverType": "PARDISO (Direct)",
        "UNET D2 Minimum Iterations": "3",
        "UNET D2 Maximum Iterations": "30",
        "UNET D2 Restart Number": "10",
        "UNET D2 Relaxation Coeff": "1.3",
        "UNET D2 SOR Precondition Iterations": "10",
        "UNET D2 ILUT Maximum Fill": "8",
        "UNET D2 ILUT Tolerance": "1E-08",
        "UNET D2 Convergence Tolerance": "0.00001",
        "UNET D2 Turbulence Formulation": "None",
        "Write HDF5 File": "1",
        "HDF Compression": "1",
        "UNET Output HDF": "-1",
    }
    _write(
        project / f"{NAME}.p01",
        "\n".join(f"{key}={value}" for key, value in plan.items()) + "\n",
    )
    flow = project / f"{NAME}.u01"
    _write(
        flow,
        "Flow Title=HEC-HMS aggregate Nowshera inflow\nProgram Version=6.60\nUse Restart= 0\nInitial Flow Loc=0\n",
    )
    for name in ["HMS Inflow", "Downstream"]:
        RasUnsteady.ensure_2d_boundary_location(flow, geom, area_2d=AREA, bc_line=name)
    import pandas as pd

    csv_path = ROOT / "downloads/nowshera-2022/study/hms-nowshera-hourly-modeled.csv"
    data = pd.read_csv(csv_path)
    times = pd.to_datetime(data["time"], utc=True)
    hours = ((times - pd.Timestamp(start)).dt.total_seconds() / 3600).to_numpy()
    flows = data["discharge_m3s"].to_numpy()
    # Fixed one-hour ordinates from the beginning of initialization through
    # the event. The model reads SI total discharge, not per-unit-width QVAR.
    hourly = np.arange(0, (end - start).total_seconds() / 3600 + 1)
    discharges = np.interp(hourly, hours, flows, left=flows[0], right=flows[-1])
    RasUnsteady.set_boundary_inline_hydrograph(
        flow,
        pd.DataFrame({"hour": hourly, "value": discharges}),
        area_2d=AREA,
        bc_line="HMS Inflow",
    )
    RasUnsteady.set_flow_hydrograph_slope(
        flow, config["channel_geometry"]["slope"], area_2d=AREA, bc_line="HMS Inflow"
    )
    RasUnsteady.set_normal_depth_boundary(
        flow, config["channel_geometry"]["slope"], area_2d=AREA, bc_line="Downstream"
    )
    RasUnsteady.set_initial_storage_elevation(flow, AREA, -9999)
    _write(
        project / "REVIEW.md",
        "# Exploratory HEC-RAS preparation record\n\n"
        + "\n\n".join(LIMITATIONS)
        + f"\n\nSource terrain SHA-256: {file_hash(terrain)}\n\nSource scenario SHA-256: {scenario_hash(Scenario.model_validate(source['scenario']))}\n",
    )
    # Use the vendor terrain constructor to preserve the HEC terrain schema.
    terrain_dir = project / "Terrain"
    terrain_dir.mkdir(exist_ok=True)
    out = terrain_dir / "Nowshera.hdf"
    command = [
        str(engine.parent / "RasProcess.exe"),
        "CreateTerrain",
        "units=Meters",
        "stitch=true",
        f"prj={project / (NAME+'.projection.prj')}",
        f"out={out}",
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
    if not out.is_file():
        raise ValueError("HEC terrain creation failed; inspect terrain.log")
    import h5py

    with h5py.File(project / f"{NAME}.g01.hdf", "r+") as hdf:
        hdf["Geometry"].attrs["SI Units"] = np.bytes_("True")
    GeomMesh.set_geometry_association(
        project / f"{NAME}.g01.hdf", terrain_hdf_path=out, hecras_dir=engine.parent
    )
    # Mapper also retains the project association for interactive inspection.
    import xml.etree.ElementTree as ET

    mapper = project / f"{NAME}.rasmap"
    tree = ET.parse(mapper)
    layers = tree.getroot().find("Terrains")
    if layers is None:
        layers = ET.SubElement(tree.getroot(), "Terrains")
    ET.SubElement(
        layers,
        "Layer",
        Name="Nowshera",
        Type="TerrainLayer",
        Filename=".\\Terrain\\Nowshera.hdf",
    )
    geometry = tree.getroot().find("Geometries/Layer")
    ET.SubElement(geometry, "Terrain", Filename=".\\Terrain\\Nowshera.hdf")
    tree.write(mapper, encoding="utf-8", xml_declaration=True)
    case = {
        "scenario": scenario.model_dump(mode="json"),
        "project": str(project),
        "fingerprint": fingerprint,
        "label": "HEC-RAS · Nowshera exploratory full SWE",
        "ready": False,
        "limitations": LIMITATIONS,
    }
    write_json(
        project / "hecras-case.json",
        {
            "format": FORMAT,
            "scenario_sha256": scenario_hash(scenario),
            "engine_sha256": file_hash(engine),
            "terrain_sha256": file_hash(project / "conditioned-terrain.tif"),
            "warmup_hours": WARMUP_HOURS,
            "mesh_m": MESH_M,
            "mannings_n": 0.04,
            "limitations": LIMITATIONS,
        },
    )
    write_json(folder / "preparation.json", case)
    return case


def _native_output(project, scenario, expected_end=None):
    """Read closed native output and reject partial or unstable engine runs."""
    import h5py
    from collections import deque

    path = project / f"{NAME}.p01.hdf"
    with h5py.File(path, "r") as hdf:
        if hdf.attrs.get("Units System") != b"SI Units":
            raise ValueError("HEC-RAS output must declare SI units.")
        messages = hdf["Results/Summary/Compute Messages (text)"][0].decode()
        if "Finished Unsteady Flow Simulation" not in messages or any(
            word in messages.lower()
            for word in [
                "went unstable",
                "simulation terminated",
                "error processing",
                "severe",
            ]
        ):
            raise ValueError(
                "HEC-RAS did not finish a stable simulation. Inspect native compute messages."
            )
        if "SWE-ELM" not in messages:
            raise ValueError("Expected the full shallow-water SWE-ELM solver.")
        match = re.search(
            r"Overall Volume Accounting Error as percentage:\s*([-+\d.eE]+)", messages
        )
        if not match or not np.isfinite(float(match[1])) or abs(float(match[1])) > 0.1:
            raise ValueError(
                "HEC-RAS volume accounting error is unavailable or exceeds 0.1%."
            )
        ts = hdf[
            "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
        ]
        dates = [
            datetime.strptime(value.decode(), "%d%b%Y %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
            for value in ts["Time Date Stamp"][()]
        ]
        end = expected_end or scenario.time.end
        start = scenario.time.start - timedelta(hours=WARMUP_HOURS)
        expected_count = round((end - start).total_seconds() / 3600) + 1
        if (
            not dates
            or dates[0] != start
            or dates[-1] != end
            or len(dates) != expected_count
            or any((b - a).total_seconds() != 3600 for a, b in zip(dates, dates[1:]))
        ):
            raise ValueError(
                "Native HEC output does not cover the full requested hourly simulation window."
            )
        geometry = hdf[f"Geometry/2D Flow Areas/{AREA}"]
        attributes = hdf["Geometry/2D Flow Areas/Attributes"][()]
        count = int(
            next(row for row in attributes if row["Name"].decode().strip() == AREA)[
                "Cell Count"
            ]
        )
        minimum = geometry["Cells Minimum Elevation"][:count]
        wse = ts[f"2D Flow Areas/{AREA}/Water Surface"][:, :count]
        velocity = ts[f"2D Flow Areas/{AREA}/Face Velocity"][()]
        if (
            not np.isfinite(wse).all()
            or not np.isfinite(minimum).all()
            or not np.isfinite(velocity).all()
        ):
            raise ValueError("Native hydraulic output contains non-finite values.")
        bc = ts[f"2D Flow Areas/{AREA}/Boundary Conditions"]
        inflow = bc["HMS Inflow"][:, 1]
        outflow = bc["Downstream"][:, 1]
        volume = ts[f"2D Flow Areas/{AREA}/Computations/Volume"][:, 0]
        warm = np.array(
            [
                scenario.time.start - timedelta(hours=6) <= date <= scenario.time.start
                for date in dates
            ]
        )
        reference = float(inflow[warm][-1])
        flux_error = float(np.max(np.abs(outflow[warm] - inflow[warm])) / reference)
        volume_range = float(np.ptp(volume[warm]) / max(abs(volume[warm][-1]), 1))
        if reference <= 0 or flux_error > 0.02 or volume_range > 0.01:
            raise ValueError("HEC-RAS constant-flow initialization has not converged.")
        faces = geometry["Faces Cell Indexes"][()]
        active = (wse[dates.index(scenario.time.start)] - minimum) > 0.05
        adjacent = [[] for _ in range(count)]
        for a, b in faces:
            if 0 <= a < count and 0 <= b < count and active[a] and active[b]:
                adjacent[a].append(b)
                adjacent[b].append(a)
        ext = hdf["Geometry/Boundary Condition Lines/External Faces"][()]
        names = hdf["Geometry/Boundary Condition Lines/Attributes"]["Name"]

        def boundary_cells(name):
            index = next(
                i for i, value in enumerate(names) if value.decode().strip() == name
            )
            return {
                int(cell)
                for row in ext
                if row["BC Line ID"] == index
                for cell in faces[row["Face Index"]]
                if 0 <= cell < count and active[cell]
            }

        inlet = boundary_cells("HMS Inflow")
        outlet = boundary_cells("Downstream")
        seen = set(inlet)
        queue = deque(inlet)
        while queue:
            for neighbor in adjacent[queue.popleft()]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        if not outlet.intersection(seen):
            raise ValueError(
                "Initialized HEC mesh has no wet inlet-to-outlet connection."
            )
        review = {
            "passed": True,
            "physical_cells": count,
            "native_frames": len(dates),
            "first_native_time": dates[0].isoformat(),
            "last_native_time": dates[-1].isoformat(),
            "volume_accounting_error_percent": float(match[1]),
            "warmup_outflow_relative_error": flux_error,
            "warmup_storage_relative_range": volume_range,
            "warmup_hours_excluded": WARMUP_HOURS,
            "wet_inlet_to_outlet_connection": True,
            "max_native_face_velocity_m_s": float(np.max(np.abs(velocity))),
            "native_hdf_sha256": file_hash(path),
            "classification": "Numerical checks only; uncalibrated and unvalidated",
        }
        metadata = read_json(project / "hecras-case.json", {})
        if metadata.get("roughness_zones"):
            from ras_commander import HdfLandCover

            expected_n = [row["n"] for row in metadata["roughness_zones"]["classes"]]
            for values in [
                geometry["Cells Center Manning's n"][:count],
                geometry["Faces Area Elevation Values"][:, 3],
            ]:
                if (
                    not np.isfinite(values).all()
                    or np.any(values <= 0)
                    or np.any(values < min(expected_n) - 1e-6)
                    or np.any(values > max(expected_n) + 1e-6)
                ):
                    raise ValueError(
                        "Native cell/face Manning values are invalid or outside the prepared roughness priors."
                    )
            audit = HdfLandCover.audit_final_mannings_n(
                path,
                mesh_name=AREA,
                minimum_cell_distinct_values=2,
                minimum_face_distinct_values=2,
            )
            review["roughness_zones"] = json.loads(audit.to_json(orient="records"))
        reference_lines = ts[f"2D Flow Areas/{AREA}/Reference Lines"]
        gauge_index = next(
            i
            for i, name in enumerate(reference_lines["Name"][()])
            if name.decode().strip() == "Nowshera gauge"
        )
        gauge_flow = reference_lines["Flow"][:, gauge_index]
        if not np.isfinite(gauge_flow).all():
            raise ValueError(
                "Native reference-section hydrograph contains non-finite values."
            )
        return {
            "review": review,
            "dates": dates,
            "wse": wse,
            "minimum": minimum,
            "points": geometry["FacePoints Coordinate"][()],
            "indexes": geometry["Cells FacePoint Indexes"][:count],
            "inflow": inflow,
            "outflow": outflow,
            "gauge_flow": gauge_flow,
            "messages": messages,
        }


def finish_and_publish(scenario, project):
    """Rasterize native cell WSE onto the actual conditioned terrain grid."""
    from rasterio.features import rasterize
    from shapely.geometry import Polygon
    from .publish import publish
    from .screening import _tiff
    from .study import STUDY, write_csv

    metadata = read_json(project / "hecras-case.json", {})
    if metadata.get("format") != FORMAT or metadata.get(
        "scenario_sha256"
    ) != scenario_hash(scenario):
        raise ValueError("Unsupported or mismatched HEC-RAS public case.")
    if file_hash(project / "conditioned-terrain.tif") != metadata["terrain_sha256"]:
        raise ValueError("Conditioned HEC terrain changed after preparation.")
    native = _native_output(project, scenario)
    out = project.parent / f"hecras-export-{uuid4().hex[:8]}"
    out.mkdir()
    with rasterio.open(project / "conditioned-terrain.tif") as src:
        dem = src.read(1)
        affine = src.transform
        crs = src.crs
    polygons = []
    for cell, indexes in enumerate(native["indexes"]):
        indexes = indexes[indexes >= 0]
        polygon = Polygon(native["points"][indexes])
        if not polygon.is_valid or polygon.area <= 0:
            raise ValueError(f"Invalid native cell polygon {cell}.")
        polygons.append((polygon, cell + 1))
    cells = rasterize(
        polygons, out_shape=dem.shape, transform=affine, fill=0, dtype="int32"
    )
    inside = cells > 0
    frames = []
    maximum = 0.0
    for i, date in enumerate(native["dates"]):
        if date < scenario.time.start or date > scenario.time.end:
            continue
        cell_wse = native["wse"][i]
        grid = cell_wse[np.maximum(cells - 1, 0)]
        wet = (cell_wse - native["minimum"] > 0.01)[np.maximum(cells - 1, 0)] & inside
        depth = np.where(
            inside, np.where(wet, np.maximum(grid - dem, 0), 0), -9999
        ).astype("float32")
        if not np.isfinite(depth).all() or depth.max() > 100:
            raise ValueError("Non-finite or implausibly large native-derived depth.")
        maximum = max(maximum, float(depth.max()))
        stamp = f"{len(frames):05d}"
        _tiff(out / f"{stamp}-depth.tif", depth, affine, crs, "m")
        _tiff(
            out / f"{stamp}-wse.tif",
            np.where(depth > 0.01, grid, -9999),
            affine,
            crs,
            "m EGM2008",
        )
        frames.append(
            {
                "time": date.isoformat(),
                "depth": f"{stamp}-depth.tif",
                "wse": f"{stamp}-wse.tif",
            }
        )
    review = {
        **native["review"],
        "published_frames": len(frames),
        "maximum_depth_m": maximum,
        "raster_method": "Native HEC cell WSE rasterized by exact mesh polygon; depth=max(WSE-conditioned terrain,0) within wet cells. Ghost cells and warm-up excluded. Face-normal velocities are not exported as cell speeds.",
    }
    modeled = {
        date.timestamp(): {
            "time": date.isoformat(),
            "station_id": "nowshera",
            "observed_m3s": "",
            "simulated_m3s": float(value),
        }
        for date, value in zip(native["dates"], native["gauge_flow"])
        if scenario.time.start <= date <= scenario.time.end
    }
    import csv

    with (STUDY / "nowshera-heldout-observations.csv").open(
        newline="", encoding="utf-8-sig"
    ) as stream:
        for observed in csv.DictReader(stream):
            date = datetime.fromisoformat(observed["time"])
            if (
                observed["split"] == "validation"
                and scenario.time.start <= date <= scenario.time.end
            ):
                modeled[date.timestamp()] = {
                    "time": date.isoformat(),
                    "station_id": "nowshera",
                    "observed_m3s": observed["observed_m3s"],
                    "simulated_m3s": float(
                        np.interp(
                            date.timestamp(),
                            [t.timestamp() for t in native["dates"]],
                            native["gauge_flow"],
                        )
                    ),
                }
    write_csv(out / "hydrographs.csv", [modeled[key] for key in sorted(modeled)])
    domain = read_json(ROOT / "domains" / scenario_hash(scenario) / "domain.json")
    manifest = {
        "scenario": scenario.model_dump(mode="json"),
        "engine": "HEC-RAS 2D",
        "terrain_sha256": domain["clips"]["dem"]["sha256"],
        "units": {"depth": "m", "wse": "m", "velocity": "m/s"},
        "vertical_datum": (
            "EGM2008; reviewed survey channel bed on FABDEM floodplain"
            if metadata.get("bed_is_surveyed")
            else "FABDEM EGM2008; estimated channel bed; no surveyed bathymetry"
        ),
        "provenance": {
            "model_run": f"HEC-RAS 6.6 native SWE-ELM run in {project}; plan 01",
            "engine_sha256": metadata["engine_sha256"],
            "conditioned_terrain_sha256": metadata["terrain_sha256"],
            "numerical_review": review,
            "limitations": metadata["limitations"],
            "gauge_comparison": "Native Nowshera reference-line discharge, interpolated to withheld daily observations. Geometry and roughness were not fitted to these values.",
            "classification": "Exploratory HEC-RAS; uncalibrated and unvalidated",
            **(
                {"geometry_and_roughness": metadata["roughness_zones"]}
                if metadata.get("roughness_zones")
                else {}
            ),
        },
        "frames": frames,
        "gauges_csv": "hydrographs.csv",
    }
    write_json(out / "export.json", manifest)
    _write(out / "native-compute-messages.txt", native["messages"])
    result = publish(out / "export.json")
    result["validation_status"] = (
        "Exploratory HEC-RAS full SWE; uncalibrated; independent flood extent unavailable"
    )
    write_json(ROOT / "results" / result["id"] / "manifest.json", result)
    write_json(project.parent / "numerical-review.json", review)
    return result


def cached_result(scenario):
    # The shared reader verifies every original raster and overlay hash.
    from .screening import cached_result as verified_result

    result = verified_result(scenario)
    if result and result.get("engine") != "HEC-RAS 2D":
        raise ValueError("Existing result uses a different engine.")
    return result


def finalize(case, project):
    scenario = Scenario.model_validate(case["scenario"])
    # Even when immutable published rasters already exist, a newly supplied
    # native run must pass independently before it is called successful.
    _native_output(project, scenario)
    result = cached_result(scenario) or finish_and_publish(scenario, project)
    source = Path(case["project"])
    bind(scenario, source, "01", str(source / "REVIEW.md"))
    case.update(ready=preflight(scenario)["ready"], result_id=result["id"])
    if not case["ready"]:
        raise ValueError(
            "HEC model passed native checks but the app readiness check still fails."
        )
    write_json(Path(case.get("index_path", INDEX)), case)
    print(
        json.dumps(
            {
                "ready": True,
                "engine": "HEC-RAS 2D",
                "result_id": result["id"],
                "frames": len(result["frames"]),
            }
        ),
        flush=True,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "smoke", "run", "publish"])
    args = parser.parse_args()
    case = prepare()
    if args.command == "publish":
        record = read_json(Path(case["project"]).parent / "latest-run.json")
        if not record:
            raise ValueError("No native HEC run is available to publish.")
        finalize(case, Path(record["run_project"]))
        return
    if args.command == "prepare":
        print(json.dumps(case, indent=2))
        return
    from ras_commander import RasPrj, init_ras_project, RasCmdr

    project = Path(case["project"])
    if args.command == "smoke":
        target = project.parent / f"smoke-{uuid4().hex[:8]}"
        shutil.copytree(project, target)
        scenario = Scenario.model_validate(case["scenario"])
        plan = target / f"{NAME}.p01"
        text = plan.read_text()
        lines = text.splitlines()
        end = scenario.time.start + timedelta(hours=6)
        for i, line in enumerate(lines):
            if line.startswith("Simulation Date="):
                old = line.split("=", 1)[1].split(",")
                lines[i] = "Simulation Date=" + ",".join(
                    old[:2] + [end.strftime("%d%b%Y").upper(), end.strftime("%H%M")]
                )
        _write(plan, "\n".join(lines) + "\n")
        project = target
    ras = RasPrj()
    if args.command == "run":
        target = project.parent / f"run-{uuid4().hex[:8]}"
        shutil.copytree(project, target)
        project = target
    write_json(
        project.parent / f"latest-{args.command}.json",
        {**case, "run_project": str(project)},
    )
    init_ras_project(str(project), runtimes()["hec_ras_exe"], ras_object=ras)
    result = RasCmdr.compute_plan(
        "01",
        ras_object=ras,
        verify=True,
        force_geompre=True,
        num_cores=2,
        max_runtime=7200,
        stream_callback=lambda line: print(line, flush=True),
    )
    print("HEC-RAS result:", result, flush=True)
    if not result:
        raise ValueError("HEC-RAS launch did not complete successfully.")
    scenario = Scenario.model_validate(case["scenario"])
    if args.command == "smoke":
        native = _native_output(
            project, scenario, scenario.time.start + timedelta(hours=6)
        )
        write_json(project.parent / "smoke-review.json", native["review"])
    else:
        finalize(case, project)


if __name__ == "__main__":
    main()
