"""Reproducible Nowshera channel-conditioned, warmed LISFLOOD-FP ACC case.

The compiled external engine computes water movement. This module prepares its
inputs and converts its real outputs; it contains no hydraulic flow solver.
"""
import argparse
import csv
from datetime import datetime, timedelta, timezone
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
from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import transform

from .domain import prepare_domain
from .channel import condition_channel, water_sources, warmup_review
from .models import Scenario
from .store import ROOT, assets, checked_asset, file_hash, read_json, scenario_hash, write_json
from .study import STUDY, START, END, write_csv
from .worker import bind, preflight, runtimes

FORMAT = "nowshera-channel-warm-acc-v3"
SETTINGS = {"mesh_m": 100, "warmup_seconds": 72 * 3600, "profile_bin_m": 500,
            "water_fraction_threshold": .25, "channel_manning_n": .035}
INDEX = ROOT / "screening" / "case.json"
# Analyst assumptions for a sensitivity model, not fitted Pakistani roughness.
MANNING = {10: .10, 20: .06, 30: .035, 40: .04, 50: .10, 60: .03,
           70: .03, 80: .035, 90: .07, 95: .10, 100: .04}
LIMITATIONS = [
    "Exploratory channel-conditioned LISFLOOD-FP ACC model; not calibrated HEC-RAS or an operational forecast.",
    "The HEC-HMS inflow is modeled from daily Warsak/Swat snapshots and a fitted constant lateral contribution. Its withheld KGE is 0.462, below the 0.60 target.",
    "The aggregate Nowshera flow is imposed at the western edge of this short reach. That spatial transfer neglects additional travel time; no separate tributaries are added or double counted.",
    "WorldCover water footprints and a monotone FABDEM water-surface profile define estimated channel geometry. Bed levels use rectangular Manning normal depths at the initial modeled inflow; they are not surveyed or fitted to held-out observations. Terrain outside the mapped-water corridor is unchanged.",
    "100 m terrain averaging, estimated bathymetry, assumed land-cover roughness, zero rainfall/infiltration and a free downstream boundary are explicit screening assumptions. Surveyed structures and levee operations remain unavailable.",
    "A 72-hour constant-flow numerical warm-up precedes the displayed flood period. The starting HEC-HMS flow is an initialization assumption, not an observed pre-event hydrograph. Only converged flood-period frames are published. Depth includes river water, not only additional flood depth above normal water.",
    "Independent water levels and a matched satellite flood extent are unavailable. Numerical checks do not validate real-world inundation.",
]


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _tiff(path, values, affine, crs, units):
    with rasterio.open(path, "w", driver="GTiff", width=values.shape[1], height=values.shape[0],
                       count=1, dtype="float32", crs=crs, transform=affine, nodata=-9999, compress="deflate") as dst:
        dst.write(values.astype("float32"), 1)
        dst.update_tags(units=units, model_status="uncalibrated exploratory screening")


def _ascii(path, values, affine):
    height, width = values.shape
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(f"ncols {width}\nnrows {height}\nxllcorner {affine.c:.3f}\nyllcorner {affine.f - height * affine.a:.3f}\ncellsize {affine.a:.3f}\nNODATA_value -9999\n")
        np.savetxt(stream, values, fmt="%.5f")


def modeled_inflows(target):
    """Keep measured snapshots and interpolated/model-derived values distinguishable."""
    report = read_json(STUDY / "routing-calibration.json")
    source = STUDY / "hms-nowshera-hourly-modeled.csv"
    if not report or file_hash(source) != report["output_csv_sha256"]:
        raise ValueError("Recompute/review the HEC-HMS study; its output hash does not match the calibration report.")
    routed = _rows(source)
    times = [datetime.fromisoformat(row["time"]) for row in routed]
    flows = np.array([float(row["discharge_m3s"]) for row in routed])
    if len(times) != 385 or times[0] != START or times[-1] != END or any(b - a != timedelta(hours=1) for a, b in zip(times, times[1:])):
        raise ValueError("The modeled inflow must cover the complete 385-hourly-ordinate study window without gaps.")
    if not np.isfinite(flows).all() or np.any(flows < 0) or any(row["value_type"] != "modeled" for row in routed):
        raise ValueError("Expected finite, nonnegative and explicitly modeled HEC-HMS discharges.")
    upstream = STUDY / "upstream-hourly-interpolated.csv"
    if file_hash(upstream) != report["boundary_csv_sha256"]:
        raise ValueError("The upstream inputs changed after HEC-HMS calibration.")
    columns = ["time", "station_id", "discharge_m3s", "source", "value_type"]
    combined = [{key: row[key] for key in columns} for row in _rows(upstream)]
    combined += [{"time": row["time"], "station_id": "nowshera-hms", "discharge_m3s": row["discharge_m3s"],
                  "source": f"HEC-HMS 4.14 FittedRouting; source SHA-256 {report['output_csv_sha256']}; uncalibrated hydraulic boundary", "value_type": "modeled"} for row in routed]
    write_csv(target, combined, columns)
    return times, flows, report


def _warp(path, shape_, affine, crs, method):
    values = np.full(shape_, np.nan, dtype="float32")
    with rasterio.open(path) as src:
        reproject(rasterio.band(src, 1), values, src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata,
                  dst_transform=affine, dst_crs=crs, dst_nodata=np.nan, resampling=method)
    if not np.isfinite(values).all():
        raise ValueError(f"Computational grid is not fully covered by {path.name}.")
    return values


def gauge_sections(path, gauge_x, top, height, cell):
    # The 8.0.3 input reader clamps E/W section lengths using remaining columns,
    # although CalcVirtualGauge integrates along rows. One-cell sections avoid
    # that input-reader issue without modifying the external solver. Sum their
    # signed outputs to obtain the full north-to-south cross-section flux.
    lines = [str(height)] + [f"{gauge_x:.3f} {top - (row + .5) * cell:.3f} E {cell:.3f}" for row in range(height)]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def prepare():
    from .cli import register
    catalog = assets()
    engine = Path(runtimes()["lisflood_fp_exe"])
    if not engine.is_file():
        raise ValueError("LISFLOOD-FP is not installed/configured.")
    inputs = {key: checked_asset(key)[0]["sha256"] for key in ["dem", "landcover", "soil", "rainfall", "hydrography", "catchment"]}
    fingerprint = hashlib.sha256(json.dumps({"format": FORMAT, "settings": SETTINGS, "inputs": inputs,
        "engine": file_hash(engine), "hms": file_hash(STUDY / "hms-nowshera-hourly-modeled.csv"),
        "report": file_hash(STUDY / "routing-calibration.json")}, sort_keys=True).encode()).hexdigest()
    existing = read_json(INDEX)
    if existing and existing.get("fingerprint") == fingerprint:
        s = Scenario.model_validate(existing["scenario"])
        binding = read_json(ROOT / "bindings" / f"{scenario_hash(s)}.json", {})
        if binding.get("asset_hashes") and preflight(s)["ready"]:
            return existing
    folder = ROOT / "screening" / fingerprint[:12]
    project = folder / "project"
    project.mkdir(parents=True, exist_ok=True)
    times, flows, report = modeled_inflows(folder / "documented-inflows.csv")
    if catalog.get("inflow"):
        write_json(folder / f"previous-inflow-{catalog['inflow']['sha256'][:12]}.json", catalog["inflow"])
    inflow = register("inflow", folder / "documented-inflows.csv", "FFC daily reports + computed HEC-HMS FittedRouting; see screening review and routing-calibration.json",
                      "Derived research input; retain FFC and USACE attribution; source report terms apply", "Exploratory observed/interpolated gauge series + modeled Nowshera aggregate")
    values = json.loads((Path(__file__).resolve().parents[1] / "examples" / "nowshera-2022.json").read_text())
    values.update(id=f"nowshera-public-screen-{fingerprint[:8]}", name="Nowshera · warmed river public-data screening")
    values["domain"].update(radius_km=8, mesh_m=SETTINGS["mesh_m"], dem_sha256=inputs["dem"])
    values["time"].update(start=START.isoformat(), end=END.isoformat(), output_interval_minutes=60)
    values["forcing"].update(rainfall_product="CHIRPS", soil_moisture="normal", upstream_station_ids=["nowshera-hms"],
        inflow_asset=inflow["sha256"], bias_correction="Gauge-driven screening: rainfall, infiltration and initial soil moisture are unused. HEC-HMS aggregate inflow includes routed Warsak/Swat and an estimated constant lateral term; see explicit limitations.")
    values["hydraulics"].update(engine="LISFLOOD-FP", equations="local inertial")
    values["provenance"].update(created_at="2026-10-20T00:00:00Z", purpose="Runnable exploratory public-data 2D screening; uncalibrated and unvalidated.",
        notes="\n".join(LIMITATIONS), sources=["https://www.ffc.gov.pk/", "https://zenodo.org/records/4073011", "https://data.bris.ac.uk/data/dataset/s5hqmjcdj8yo2ibzi9b4ew3sn", "https://esa-worldcover.org/en/data-access"])
    s = Scenario.model_validate(values)
    domain = prepare_domain(s)
    crs = s.domain.model_crs
    forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    center_x, center_y = forward(s.outlet.lon, s.outlet.lat)
    cell = s.domain.mesh_m
    # Inscribe the metric rectangle inside the native geographic clip, preserving
    # complete coverage without extrapolating or inventing terrain edge pixels.
    # Retain v2's physical bounds; refine the grid, not the study window.
    half, alignment = s.domain.radius_km * 1000 - 600, 200
    west = math.ceil((center_x - half) / alignment) * alignment
    east = math.floor((center_x + half) / alignment) * alignment
    bottom = math.ceil((center_y - half) / alignment) * alignment
    top = math.floor((center_y + half) / alignment) * alignment
    affine = from_origin(west, top, cell, cell)
    dims = (round((top - bottom) / cell), round((east - west) / cell))
    native = ROOT / "domains" / scenario_hash(s)
    dem = np.round(_warp(native / "dem.tif", dims, affine, crs, Resampling.average), 3)
    cover = _warp(native / "landcover.tif", dims, affine, crs, Resampling.mode).astype("int16")
    unknown = set(np.unique(cover)) - MANNING.keys()
    if unknown:
        raise ValueError(f"Unmapped land-cover classes: {sorted(unknown)}")
    roughness = np.array([MANNING[int(value)] for value in cover.ravel()], dtype="float32").reshape(dims)
    fraction, surface = water_sources(native / "dem.tif", native / "landcover.tif", dims, affine, crs)
    raw_dem = dem.copy()
    dem, water, centerline, geometry = condition_channel(dem, fraction, surface, affine, float(flows[0]))
    roughness[water] = SETTINGS["channel_manning_n"]
    _tiff(project / "unconditioned-terrain.tif", raw_dem, affine, crs, "m EGM2008")
    _tiff(project / "channel-water-fraction.tif", fraction, affine, crs, "fraction")
    _tiff(project / "channel-mask.tif", water.astype("float32"), affine, crs, "boolean")
    _tiff(project / "channel-lowering.tif", raw_dem - dem, affine, crs, "m estimated bed correction")
    write_json(project / "channel-geometry.json", {**geometry, "centerline_grid_rows_columns": centerline.tolist()})
    features = read_json(checked_asset("hydrography")[1])["features"]
    area = box(west, bottom, east, top)
    crossings = []
    for feature in features:
        if feature["properties"].get("UPLAND_SKM", 0) < 85000:
            continue
        river_geometry = transform(forward, shape(feature["geometry"]))
        boundary = river_geometry.intersection(area.boundary)
        if boundary.geom_type == "Point": crossings.append(boundary)
        elif boundary.geom_type == "MultiPoint": crossings.extend(boundary.geoms)
    western = [point for point in crossings if abs(point.x - west) < .01]
    eastern = [point for point in crossings if abs(point.x - east) < .01]
    if len(western) != 1 or len(eastern) != 1:
        raise ValueError("The short reach needs one unambiguous major-channel western entry and eastern exit.")
    target_row = round((top - western[0].y) / cell - .5)
    candidates = [row for row in range(dims[0]) if abs(row - target_row) * cell < 1500 and water[row, 0]]
    if not candidates:
        raise ValueError("No mapped-water cell near the HydroRIVERS upstream boundary.")
    entry = min(candidates, key=lambda row: abs(row - target_row))
    lower_row = upper_row = entry
    while lower_row > 0 and lower_row - 1 in candidates: lower_row -= 1
    while upper_row + 1 < dims[0] and upper_row + 1 in candidates: upper_row += 1
    y_low, y_high = top - (upper_row + 1) * cell, top - lower_row * cell
    width = y_high - y_low
    slope = geometry["slope"]
    if not 0 < slope < .02:
        raise ValueError("Terrain-derived downstream slope is unsuitable; review the boundary instead of guessing it.")
    _ascii(project / "terrain.asc", dem, affine)
    _ascii(project / "roughness.asc", roughness, affine)
    _tiff(project / "computational-terrain.tif", dem, affine, crs, "m EGM2008")
    (project / "terrain.prj").write_text(rasterio.crs.CRS.from_string(crs).to_wkt(), encoding="utf-8")
    (project / "boundaries.bci").write_text(f"W {y_low:.3f} {y_high:.3f} QVAR routed\nE {bottom:.3f} {top:.3f} FREE {slope:.9f}\n", encoding="ascii")
    # Floodplain QVAR is discharge per unit width (m2/s), not total m3/s.
    warmup = SETTINGS["warmup_seconds"]
    with (project / "inflow.bdy").open("w", encoding="ascii", newline="\n") as stream:
        stream.write(f"Modeled HMS inflow divided by {width:.3f} m boundary width; constant-flow warm-up first\nrouted\n{len(times) + 1} seconds\n")
        stream.write(f"{flows[0] / width:.12f} 0.000\n")
        for time, discharge in zip(times, flows): stream.write(f"{discharge / width:.12f} {warmup + (time - START).total_seconds():.3f}\n")
    gauge_col = max(0, min(dims[1] - 2, math.floor((center_x - west) / cell) - 1))
    gauge_x = west + (gauge_col + .5) * cell
    gauge_sections(project / "nowshera.gauge", gauge_x, top, dims[0], cell)
    duration = warmup + (END - START).total_seconds()
    (project / "screen.par").write_text(f"DEMfile terrain.asc\nmanningfile roughness.asc\nresroot nowshera\ndirroot output\nsim_time {duration:.3f}\ninitial_tstep 20\nmassint 3600\nsaveint 3600\nacceleration\nbcifile boundaries.bci\nbdyfile inflow.bdy\ngaugefile nowshera.gauge\n", encoding="ascii")
    config = {"format": FORMAT, "scenario_sha256": scenario_hash(s), "source_terrain_sha256": domain["clips"]["dem"]["sha256"],
        "computational_terrain_sha256": file_hash(project / "computational-terrain.tif"), "inflow_asset_sha256": inflow["sha256"],
        "warmup_seconds": warmup, "baseflow_m3s": float(flows[0]), "channel_geometry": geometry,
        "channel_geometry_sha256": file_hash(project / "channel-geometry.json"), "channel_mask_sha256": file_hash(project / "channel-mask.tif"),
        "engine_sha256": file_hash(engine), "grid": {"crs": crs, "shape": list(dims), "cell_m": cell, "bounds": [west, bottom, east, top]},
        "upstream": {"side": "W", "y_low": y_low, "y_high": y_high, "width_m": width, "station_id": "nowshera-hms", "units_in_bdy": "m2/s", "hydrorivers_entry": list(western[0].coords)[0]},
        "downstream": {"side": "E", "type": "FREE", "slope": slope, "method": "monotone mapped-water surface drop divided by centerline distance; assumption, not surveyed normal slope"},
        "gauge": {"station_id": "nowshera", "easting": west + (gauge_col + 1) * cell, "segments": dims[0],
            "method": "sum of signed eastward one-cell section outputs across every grid row near the approximate Nowshera gauge; avoids the installed reader's E/W length clamp; not a surveyed section"},
        "roughness": {str(key): value for key, value in MANNING.items()}, "limitations": LIMITATIONS, "massint_seconds": 3600,
        "hms_validation_kge": report["scores"]["validation"]["kge"]}
    write_json(project / "screening.json", config)
    review = "# Automated preparation review — exploratory only\n\n" + "\n\n".join(LIMITATIONS) + "\n\nInputs use metric UTM 42N and native EGM2008 vertical heights. channel-geometry.json records all estimated dimensions; original and conditioned terrain, water fractions, mask and lowering are retained. Boundary QVAR is divided by the exact mapped inlet width. West/North/South are closed except the inlet; East is a free outflow. Numerical conservation, warm-up convergence, wet channel connectivity and native output times are checked separately at publication. The continuous external-engine run retains both water depth and flow momentum across the warm-up/flood boundary, without a depth-only restart. This is a preparation review, not independent expert validation.\n"
    (project / "REVIEW.md").write_text(review, encoding="utf-8")
    write_json(folder / "scenario.json", s.model_dump(mode="json"))
    bind(s, project, "screen.par", str(project / "REVIEW.md"))
    case = {"fingerprint": fingerprint, "label": "Runnable · Nowshera warmed river screening", "scenario": s.model_dump(mode="json"),
            "project": str(project), "limitations": LIMITATIONS, "ready": preflight(s)["ready"]}
    if not case["ready"]:
        raise ValueError(f"Prepared screening case failed preflight: {preflight(s)}")
    write_json(INDEX, case)
    return case


def prepared_cases():
    case = read_json(INDEX)
    return [case] if case else []


def cached_result(s):
    """Reuse only immutable, hash-verified output of the same exact scenario."""
    folder = ROOT / "results" / f"{s.id}-{scenario_hash(s)[:12]}"
    result = read_json(folder / "manifest.json")
    if not result:
        return None
    if result["scenario_sha256"] != scenario_hash(s) or not result["frames"]:
        raise ValueError("Existing screening result has inconsistent identity.")
    for frame in result["frames"]:
        for field in frame["fields"].values():
            original = folder / Path(field["raster_url"]).name
            overlay = folder / Path(field["url"]).name
            if not original.is_file() or file_hash(original) != field["sha256"] or not overlay.is_file() or file_hash(overlay) != field.get("overlay_sha256"):
                raise ValueError("Published output changed. Preserve the original and prepare a new case ID before recomputing.")
    return result


def finish_and_publish(s, project):
    from .publish import publish
    config = read_json(project / "screening.json")
    if not config or config.get("format") != FORMAT or config.get("scenario_sha256") != scenario_hash(s):
        raise ValueError("Unsupported or mismatched screening export configuration.")
    if file_hash(project / "computational-terrain.tif") != config["computational_terrain_sha256"]:
        raise ValueError("Computational terrain changed after preparation.")
    output = project / "output"
    mass = np.loadtxt(output / "nowshera.mass", skiprows=1, ndmin=2)
    sections = np.loadtxt(output / "nowshera.discharge", skiprows=3, ndmin=2)
    duration = (s.time.end - s.time.start).total_seconds()
    warmup = config.get("warmup_seconds", 0)
    total_duration = duration + warmup
    interval = config["massint_seconds"]
    expected = int(total_duration // interval) + 1
    if mass.shape != (expected, 12) or not np.isfinite(mass).all() or np.any(np.diff(mass[:, 0]) <= 0):
        raise ValueError("Engine mass output is incomplete, non-finite or unordered.")
    if not total_duration <= mass[-1, 0] <= total_duration + 20.001:
        raise ValueError("The engine did not reach the complete scenario window.")
    if np.any(abs(mass[:, 0] - np.arange(expected) * interval) > 20.001):
        raise ValueError("Unexpected output timing; refusing nominal timestamp substitution.")
    segments = config.get("gauge", {}).get("segments", 1)
    if sections.shape != (expected, segments + 1) or not np.isfinite(sections).all() or not np.allclose(sections[:, 0], mass[:, 0], atol=.011, rtol=0):
        raise ValueError("Gauge output does not match the engine's actual mass-output times.")
    discharge = np.column_stack([sections[:, 0], sections[:, 1:].sum(axis=1)])
    if np.any(discharge[:, 1] < 0):
        raise ValueError("Signed reverse gauge flow requires a separate publication contract; it cannot be relabeled as positive discharge.")
    inflow_volume = float(np.trapezoid(np.r_[mass[0, 6], mass[:, 6]], np.r_[0, mass[:, 0]]))
    relative_error = float(abs(mass[:, 10]).sum() / max(inflow_volume, 1))
    if relative_error > .001:
        raise ValueError(f"Numerical volume error {relative_error:.3%} exceeds the declared 0.1% screening tolerance.")
    depth_paths = sorted(output.glob("nowshera-*.wd"))
    wse_paths = sorted(output.glob("nowshera-*.elev"))
    if len(depth_paths) != expected or len(wse_paths) != expected:
        raise ValueError("Engine did not write every expected depth and WSE frame.")
    if file_hash(project / "channel-geometry.json") != config["channel_geometry_sha256"] or file_hash(project / "channel-mask.tif") != config["channel_mask_sha256"]:
        raise ValueError("Channel geometry changed after preparation.")
    with rasterio.open(project / "channel-mask.tif") as mask:
        corridor = mask.read(1) > 0
    geometry = read_json(project / "channel-geometry.json")
    first_index = int(np.flatnonzero(mass[:, 0] >= warmup)[0])
    first_depth = np.loadtxt(depth_paths[first_index], skiprows=6, ndmin=2)
    initialization = warmup_review(mass, sections, first_depth, corridor,
        np.array(geometry["centerline_grid_rows_columns"]), warmup, config["baseflow_m3s"])
    initialization["first_frame_wet_area_m2"] = initialization.pop("first_frame_wet_cells") * s.domain.mesh_m ** 2
    initialization["first_frame_off_channel_wet_area_m2"] = int(np.count_nonzero((first_depth > .05) & ~corridor)) * s.domain.mesh_m ** 2
    write_json(project.parent / "warmup-review.json", initialization)
    with rasterio.open(project / "computational-terrain.tif") as terrain:
        affine, crs, dims = terrain.transform, terrain.crs, (terrain.height, terrain.width)
    rasters = project.parent / "exports"
    rasters.mkdir(exist_ok=True)
    frames, source_outputs, max_depth, max_wet_area = [], [], 0., 0.
    for index, (depth_path, wse_path) in enumerate(zip(depth_paths, wse_paths)):
        depths = np.loadtxt(depth_path, skiprows=6, ndmin=2)
        levels = np.loadtxt(wse_path, skiprows=6, ndmin=2)
        if depths.shape != dims or levels.shape != dims or not np.isfinite(depths).all() or not np.isfinite(levels).all() or np.any(depths < 0):
            raise ValueError(f"Invalid engine field in frame {index}.")
        # Both regular rasters and mass records are written in the same engine
        # iteration (equal massint/saveint). Preserve those actual, not nominal,
        # times. The final adaptive step may overshoot; do not invent an end frame.
        event_seconds = float(mass[index, 0]) - warmup
        time = s.time.start + timedelta(seconds=event_seconds)
        source_outputs += [{"path": path.relative_to(project).as_posix(), "sha256": file_hash(path)} for path in [depth_path, wse_path]]
        if event_seconds < 0 or time > s.time.end:
            continue
        max_depth = max(max_depth, float(depths.max()))
        max_wet_area = max(max_wet_area, float(np.count_nonzero(depths > .05) * s.domain.mesh_m ** 2))
        depth_name, wse_name = f"{len(frames):04d}-depth.tif", f"{len(frames):04d}-wse.tif"
        _tiff(rasters / depth_name, depths, affine, crs, "m")
        _tiff(rasters / wse_name, levels, affine, crs, "m EGM2008")
        frames.append({"time": time.isoformat(), "depth": depth_name, "wse": wse_name})
    if not max_depth > 0 or not max_wet_area > 0 or not np.any(mass[:, 8] > 0):
        raise ValueError("Model has no wet output or never reaches downstream outflow; inspect its domain and boundaries.")
    event_discharge = discharge.copy()
    event_discharge[:, 0] -= warmup
    modeled = {float(row[0]): {"time": (s.time.start + timedelta(seconds=float(row[0]))).isoformat(), "station_id": "nowshera",
               "observed_m3s": "", "simulated_m3s": float(row[1])} for row in event_discharge if 0 <= row[0] <= duration}
    for observed in _rows(STUDY / "nowshera-heldout-observations.csv"):
        if observed["split"] != "validation":
            continue
        time = datetime.fromisoformat(observed["time"])
        seconds = (time - s.time.start).total_seconds()
        if event_discharge[0, 0] <= seconds <= min(event_discharge[-1, 0], duration):
            modeled[seconds] = {"time": time.isoformat(), "station_id": "nowshera", "observed_m3s": observed["observed_m3s"],
                                "simulated_m3s": float(np.interp(seconds, event_discharge[:, 0], event_discharge[:, 1]))}
    write_csv(rasters / "hydrographs.csv", [modeled[time] for time in sorted(modeled)])
    numerical = {"completed_seconds": float(mass[-1, 0]), "requested_seconds": total_duration, "flood_duration_seconds": duration,
        "warmup_seconds_excluded_from_playback": warmup, "warmup_review": initialization, "engine_step_limit_seconds": 20,
        "mass_absolute_error_sum_m3": float(abs(mass[:, 10]).sum()), "inflow_volume_approx_m3": inflow_volume,
        "relative_mass_error": relative_error, "declared_relative_mass_error_limit": .001, "maximum_depth_m": max_depth,
        "maximum_wet_area_m2_at_5cm": max_wet_area, "published_frames": len(frames), "engine_frames": expected,
        "engine_final_overshoot_seconds": float(mass[-1, 0] - total_duration), "first_published_time": frames[0]["time"], "last_published_time": frames[-1]["time"],
        "source_mass_sha256": file_hash(output / "nowshera.mass"), "source_discharge_sha256": file_hash(output / "nowshera.discharge"),
        "note": "Numerical execution and warm-up checks only, not real-world validation. Warm-up is excluded; event times equal native engine mass-record seconds minus the explicit initialization duration. No depth-only restart or nominal timestamp substitution."}
    write_json(project.parent / "numerical-review.json", numerical)
    manifest = {"scenario": s.model_dump(mode="json"), "engine": "LISFLOOD-FP", "terrain_sha256": config["source_terrain_sha256"],
        "units": {"depth": "m", "wse": "m", "velocity": "m/s"}, "vertical_datum": "FABDEM native EGM2008; UTM 42N; estimated channel-bed correction, not surveyed bathymetry",
        "provenance": {"model_run": f"LISFLOOD-FP 8.0.3 ACC external compute in {project}; configuration {scenario_hash(s)}",
            "classification": "exploratory channel-conditioned screening", "engine_sha256": config["engine_sha256"], "configuration": config,
            "numerical_review": numerical, "source_outputs": source_outputs,
            "gauge_comparison": "Signed one-cell engine section fluxes summed across all grid rows, then linearly interpolated to eight held-out observation times. No extrapolation or calibration-period observations in skill scores."},
        "frames": frames, "gauges_csv": "hydrographs.csv"}
    write_json(rasters / "export.json", manifest)
    result = publish(rasters / "export.json")
    result["validation_status"] = "Exploratory channel-conditioned screening; warmed river, estimated bathymetry, no independent flood-extent validation"
    write_json(ROOT / "results" / result["id"] / "manifest.json", result)
    # Keep earlier files for comparison/audit, but offer the corrected prepared
    # case by default. Never rewrite the old scientific fields or metrics.
    for previous in (ROOT / "results").glob("nowshera-public-screen-*/manifest.json"):
        old = read_json(previous)
        if old["id"] != result["id"] and not old.get("superseded_by"):
            old.update(superseded_by=result["id"], superseded_reason="Replaced by the channel-conditioned case with a converged pre-event river warm-up; original outputs retained.")
            write_json(previous, old)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "smoke", "run"])
    args = parser.parse_args()
    case = prepare()
    if args.command == "smoke":
        project = Path(case["project"])
        target = project.parent / f"smoke-{uuid4().hex[:8]}"
        shutil.copytree(project, target)
        path = target / "screen.par"
        duration = SETTINGS["warmup_seconds"] + (END - START).total_seconds()
        path.write_text(path.read_text().replace(f"sim_time {duration:.3f}", f"sim_time {SETTINGS['warmup_seconds'] + 21600:.3f}"))
        with (target / "engine.log").open("w") as log:
            result = subprocess.run([runtimes()["lisflood_fp_exe"], "screen.par"], cwd=target,
                env={**os.environ, "OMP_NUM_THREADS": "2"}, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        print(json.dumps({"exit_code": result.returncode, "folder": str(target), "mass_tail": (target / "output" / "nowshera.mass").read_text().splitlines()[-2:]}))
    elif args.command == "run":
        from .worker import execute
        job_id = uuid4().hex
        execute(Scenario.model_validate(case["scenario"]), job_id)
        print(json.dumps(read_json(ROOT / "jobs" / job_id / "status.json")))
    else:
        print(json.dumps({key: case[key] for key in ["label", "ready", "project", "fingerprint"]}))


if __name__ == "__main__":
    main()
