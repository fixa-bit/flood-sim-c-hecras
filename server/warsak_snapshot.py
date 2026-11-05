"""Warsak steady-release snapshots scored against Sentinel-1 water masks.

Run `python -m server.warsak_snapshot --help`.

A snapshot holds one observed FFC 06:00 Warsak release constant until the
river below the dam is steady, then compares the steady flood extent with a
Sentinel-1 water mask from (nearly) the same moment. The discharge forces the
model; the satellite only calibrates and validates it. This is not a 2022
replay: frames show the steady state at that release, not event timing.

Calibration: floodplain roughness multiplier x channel Manning n, chosen by
floodplain CSI against the 25 Aug 2022 01:16 UTC scene (06:16 PKT, 16 minutes
after the 59,000-cusec reading). Validation: the chosen values, unchanged, at
the steady 5 Sep release against the 5 Sep 13:13 UTC scene.
"""
import argparse
import csv
from datetime import datetime, timedelta
import json
import os
import shutil
import subprocess

import numpy as np
import rasterio
from scipy.ndimage import distance_transform_edt

from . import warsak
from .metrics import extent_metrics
from .store import ROOT, file_hash, read_json, write_json

CUSECS_TO_M3S = 0.028316846592
STEADY_HOURS = 24
MULTIPLIERS = [0.7, 0.85, 1.0, 1.15, 1.3]
CHANNEL_N = [0.030, 0.035, 0.040, 0.045]
CALIBRATION_DATE, VALIDATION_DATE = "2022-08-25", "2022-09-05"
BRACKET_DATES = ["2022-08-24", "2022-08-26"]
# Kabul floodplain zone: what a river-forced model can flood. Water far out on
# the plain (rain ponding, irrigated fields) is outside it.
ZONE_HEIGHT_M = 10.0
ZONE_DISTANCE_M = 3000.0
WET_DEPTH_M = .05
DIR = warsak.SITE_DIR / "snapshots"
TABLE = ROOT / "observations" / "observed-daily-2022.csv"


def release(date):
    """The FFC 06:00 Warsak outflow on `date`, with its source document."""
    with TABLE.open(encoding="utf-8", newline="") as stream:
        rows = [r for r in csv.DictReader(stream) if r["station_id"] == "warsak" and r["date"] == date
                and r["source"].startswith("FFC") and r["quantity"] == "outflow"]
    if len(rows) != 1:
        raise ValueError(f"No single FFC Warsak outflow reading on {date}.")
    row = rows[0]
    return {"date": date, "cusecs": int(row["discharge_cusecs"]), "m3s": int(row["discharge_cusecs"]) * CUSECS_TO_M3S,
            "time_local": row["time_local"], "document": row["document"], "document_sha256": row["document_sha256"],
            "page": row["page"], "source_line": row["source_line"]}


def reference_flow():
    """Median FFC Warsak outflow, 1 Jul - 30 Sep 2022: the one bed-conditioning flow for every run."""
    with TABLE.open(encoding="utf-8", newline="") as stream:
        values = sorted(int(r["discharge_cusecs"]) for r in csv.DictReader(stream)
                        if r["station_id"] == "warsak" and r["source"].startswith("FFC") and r["quantity"] == "outflow"
                        and "2022-07-01" <= r["date"] <= "2022-09-30")
    if not values:
        raise ValueError("Build the observed table first: python -m server.observations build")
    median = float(np.median(values))
    return {"cusecs": median, "m3s": median * CUSECS_TO_M3S, "readings": len(values),
            "method": "median of FFC 06:00 Warsak outflows, 1 Jul - 30 Sep 2022; not tuned"}


def observed(date):
    record = read_json(warsak.SITE_DIR / "satellite" / date / "mask.json")
    if not record:
        raise ValueError(f"Build the Sentinel-1 mask first: python -m server.satellite {date}")
    path = ROOT / record["files"]["observed_extent"]["path"]
    if file_hash(path) != record["files"]["observed_extent"]["sha256"]:
        raise ValueError(f"The {date} observed extent changed after it was built.")
    with rasterio.open(path) as src:
        values = src.read(1)
    return record, values


def floodplain_zone(geometry):
    """Cells within ZONE_DISTANCE_M of the mapped Kabul corridor and at most ZONE_HEIGHT_M above its water surface."""
    with rasterio.open(warsak.GEOMETRY / "channel-mask.tif") as src:
        corridor = src.read(1) > 0
    with rasterio.open(warsak.GEOMETRY / "unconditioned-terrain.tif") as src:
        terrain = src.read(1).astype("float64")
    surface = np.load(warsak.GEOMETRY / "water-surface-reference.npy")
    distance, (rows, cols) = distance_transform_edt(~corridor, return_indices=True)
    reference = surface[rows, cols]
    if not np.isfinite(reference[corridor]).all():
        raise ValueError("The corridor lacks reference water-surface heights.")
    height = terrain - reference
    zone = (distance * warsak.MESH_M <= ZONE_DISTANCE_M) & (height <= ZONE_HEIGHT_M)
    return zone, corridor


def scores(depth, observed_values, zone, corridor):
    valid = observed_values != 255
    obs, sim = observed_values == 1, depth > WET_DEPTH_M
    return {"zone": extent_metrics(obs, sim, valid & zone),
            "floodplain": extent_metrics(obs, sim, valid & zone & ~corridor),
            "window": extent_metrics(obs, sim, valid)}


def snapshot_scenario(rel, image_time):
    from .models import Scenario
    values = warsak.scenario().model_dump(mode="json")
    # Labels put the satellite acquisition at the 23rd steady hour. The engine
    # writes hourly frames a few seconds after each hour, and the frame at the
    # window's end is (correctly) dropped, so the last published frame is the
    # image time to within seconds; it is the one compared with the mask.
    image = datetime.fromisoformat(image_time)
    values.update(id=f"warsak-snapshot-{rel['date'].replace('-', '')}-{rel['cusecs']}",
                  name=f"Warsak · steady {rel['cusecs']:,} cusecs ({rel['date']} FFC 06:00 reading)",
                  kind="reservoir_release")
    values["time"].update(start=(image - timedelta(hours=STEADY_HOURS - 1)).isoformat(),
                          end=(image + timedelta(hours=1)).isoformat())
    values["provenance"].update(
        purpose="Steady snapshot at an observed FFC release, compared with a Sentinel-1 water mask; not 2022 timing.",
        notes=f"Release held at the FFC {rel['time_local']} Warsak outflow of {rel['cusecs']:,} cusecs until steady. "
              "Frames show the steady state at that release, labelled from the satellite acquisition time; they are not an event replay. "
              "The reservoir above the dam is not modelled. Rainfall and infiltration are off: rain on this 602 km2 window is under 1% of river volume.",
        sources=values["provenance"]["sources"] + [rel["document"], "https://planetarycomputer.microsoft.com/dataset/sentinel-1-rtc"])
    return Scenario.model_validate(values)


def run(release_date, mask_date, multiplier=1.0, channel_n=.035, velocity=True):
    """One steady snapshot run, scored against the mask of `mask_date`. Cached by its inputs."""
    from .channel import warmup_review
    from .worker import runtimes
    geometry, _ = warsak._checked_geometry()
    rel = release(release_date)
    mask, observed_values = observed(mask_date)
    reference = reference_flow()
    s = snapshot_scenario(rel, mask["time"])
    name = f"{release_date}-vs-{mask_date}-fp{multiplier:.2f}-n{channel_n:.3f}"
    folder = DIR / "runs" / name
    key = {"release": rel["cusecs"], "mask_sha256": mask["files"]["observed_extent"]["sha256"], "multiplier": multiplier,
           "channel_n": channel_n, "reference_cusecs": reference["cusecs"], "geometry": geometry["files"], "velocity": velocity}
    cached = read_json(folder / "result.json")
    if cached and cached.get("key") == key:
        return cached
    if folder.exists():
        shutil.rmtree(folder)
    project = folder / "project"
    total = warsak.WARMUP_SECONDS + STEADY_HOURS * 3600
    q = rel["m3s"]
    written = warsak._write_project(project, s, [s.time.start, s.time.end], np.array([q, q]), geometry, sim_seconds=total,
                                    conditioning_m3s=reference["m3s"], floodplain_multiplier=multiplier,
                                    channel_n=channel_n, velocity=velocity)
    with (project / "engine.log").open("w") as log:
        result = subprocess.run([runtimes()["lisflood_fp_exe"], "screen.par"], cwd=project, stdout=log, stderr=subprocess.STDOUT,
                                env={**os.environ, "OMP_NUM_THREADS": "2"}, timeout=7200,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise RuntimeError(f"LISFLOOD-FP exited with {result.returncode}; see {project / 'engine.log'}")
    output = project / "output"
    mass = np.loadtxt(output / "warsak.mass", skiprows=1, ndmin=2)
    sections = np.loadtxt(output / "warsak.discharge", skiprows=3, ndmin=2)
    depths = sorted(output.glob("warsak-*.wd"))
    start_index = int(np.flatnonzero(mass[:, 0] >= warsak.WARMUP_SECONDS)[0])
    start_depth = np.loadtxt(depths[start_index], skiprows=6, ndmin=2)
    final_depth = np.loadtxt(depths[-1], skiprows=6, ndmin=2)
    try:
        review = warmup_review(mass, sections, start_depth, written["water"], written["centerline"],
                               warsak.WARMUP_SECONDS, q)
    except ValueError as exc:
        review = {"passed": False, "detail": str(exc)}
    inflow = float(np.trapezoid(mass[:, 6], mass[:, 0]))
    zone, corridor = floodplain_zone(geometry)
    record = {
        "key": key, "name": name, "release": rel, "mask_date": mask_date, "mask_time": mask["time"],
        "multiplier": multiplier, "channel_n": channel_n, "reference_flow": reference,
        "warmup_review": review, "relative_mass_error": float(abs(mass[:, 10]).sum() / max(inflow, 1)),
        "steady_change": {"max_depth_change_m": float(np.abs(final_depth - start_depth).max()),
                          "wet_cells_start": int((start_depth > WET_DEPTH_M).sum()),
                          "wet_cells_final": int((final_depth > WET_DEPTH_M).sum())},
        "maximum_depth_m": float(final_depth.max()),
        "wet_area_km2": float((final_depth > WET_DEPTH_M).sum() * warsak.MESH_M ** 2 / 1e6),
        "scores": scores(final_depth, observed_values, zone, corridor),
        "project": str(project),
    }
    write_json(folder / "result.json", record)
    return record


def _choose(table):
    """Highest floodplain CSI; ties go to the zone CSI, then to the values closest to the priors."""
    def rank(item):
        fp, zone = item["scores"]["floodplain"]["csi"] or 0, item["scores"]["zone"]["csi"] or 0
        prior = abs(item["multiplier"] - 1) + abs(item["channel_n"] - .035) * 20
        return (round(fp, 4), round(zone, 4), -prior)
    return max((item for item in table if item["warmup_review"].get("passed")), key=rank)


def sweep():
    table = []
    for multiplier in MULTIPLIERS:
        for channel_n in CHANNEL_N:
            item = run(CALIBRATION_DATE, CALIBRATION_DATE, multiplier, channel_n)
            table.append(item)
            print(f"fp x{multiplier:.2f}  n {channel_n:.3f}  floodplain CSI {item['scores']['floodplain']['csi']:.3f}  "
                  f"zone CSI {item['scores']['zone']['csi']:.3f}  converged {item['warmup_review'].get('passed')}", flush=True)
    chosen = _choose(table)
    brackets = [run(date, CALIBRATION_DATE, chosen["multiplier"], chosen["channel_n"]) for date in BRACKET_DATES]
    validation = run(VALIDATION_DATE, VALIDATION_DATE, chosen["multiplier"], chosen["channel_n"])
    summary = {
        "calibration": {"date": CALIBRATION_DATE, "objective": "floodplain CSI (Kabul floodplain zone, excluding the mapped channel)",
                        "grid": {"floodplain_multiplier": MULTIPLIERS, "channel_n": CHANNEL_N},
                        "runs": [{k: item[k] for k in ["name", "multiplier", "channel_n", "scores", "relative_mass_error"]}
                                 | {"converged": item["warmup_review"].get("passed")} for item in table],
                        "chosen": {"multiplier": chosen["multiplier"], "channel_n": chosen["channel_n"], "scores": chosen["scores"]}},
        "bracketing": [{"release": b["release"]["cusecs"], "date": b["release"]["date"], "scores": b["scores"],
                        "wet_area_km2": b["wet_area_km2"]} for b in brackets],
        "validation": {"date": VALIDATION_DATE, "release": validation["release"]["cusecs"], "scores": validation["scores"],
                       "converged": validation["warmup_review"].get("passed"), "wet_area_km2": validation["wet_area_km2"]},
        "zone": {"max_height_above_kabul_m": ZONE_HEIGHT_M, "max_distance_m": ZONE_DISTANCE_M},
        "built_at": datetime.now().astimezone().isoformat(),
    }
    write_json(DIR / "calibration.json", summary)
    return summary


def publish():
    """Publish the chosen 25 Aug run and the 5 Sep validation run, with their observed extents."""
    from .domain import prepare_domain
    from .store import scenario_hash
    from .worker import runtimes
    summary = read_json(DIR / "calibration.json")
    if not summary:
        raise ValueError("Run the sweep first.")
    chosen = summary["calibration"]["chosen"]
    published = []
    geometry, _ = warsak._checked_geometry()
    zone, _ = floodplain_zone(geometry)
    for date in [CALIBRATION_DATE, VALIDATION_DATE]:
        item = run(date, date, chosen["multiplier"], chosen["channel_n"])
        if not item["warmup_review"].get("passed"):
            raise ValueError(f"The {date} run did not reach a converged steady state; not publishing.")
        rel = item["release"]
        mask, values = observed(date)
        s = snapshot_scenario(rel, mask["time"])
        domain = prepare_domain(s)
        project = warsak.Path(item["project"])
        # The published comparison covers the Kabul floodplain zone only; outside it is "not observable" here.
        zoned = np.where(zone, values, 255).astype("uint8")
        extent = project / "observed-extent-floodplain-zone.tif"
        with rasterio.open(ROOT / mask["files"]["observed_extent"]["path"]) as src:
            profile = src.profile
        with rasterio.open(extent, "w", **profile) as dst:
            dst.write(zoned, 1)
        written = read_json(project / "channel-geometry.json")
        config = {
            "format": warsak.FORMAT, "site": warsak.SITE, "resroot": "warsak", "scenario_sha256": scenario_hash(s),
            "source_terrain_sha256": domain["clips"]["dem"]["sha256"],
            "computational_terrain_sha256": file_hash(project / "computational-terrain.tif"),
            "inflow": {"kind": "steady observed release", **rel}, "warmup_seconds": warsak.WARMUP_SECONDS,
            "baseflow_m3s": rel["m3s"], "channel_geometry": {k: v for k, v in written.items() if k != "centerline_grid_rows_columns"},
            "channel_geometry_sha256": file_hash(project / "channel-geometry.json"),
            "channel_mask_sha256": file_hash(project / "channel-mask.tif"),
            "engine_sha256": file_hash(warsak.Path(runtimes()["lisflood_fp_exe"])),
            "grid": geometry["summary"]["grid"], "upstream": {**geometry["summary"]["inlet"], "station_id": warsak.SITE},
            "downstream": geometry["summary"]["downstream"],
            "gauge": {"station_id": "warsak-east-edge", "segments": geometry["summary"]["grid"]["shape"][0],
                      "method": "sum of signed eastward one-cell section outputs near the east edge; modelled outflow, not a gauge"},
            "gauge_comparison": "Modelled outflow near the east edge only; no downstream observations exist inside the window.",
            "validation_status": f"Steady snapshot at an observed FFC release, scored against Sentinel-1 ({date}); "
                                 "uncalibrated beyond floodplain roughness; not 2022 timing",
            "calibration": {"floodplain_multiplier": chosen["multiplier"], "channel_n": chosen["channel_n"],
                            "fitted_on": CALIBRATION_DATE, "role": "calibration" if date == CALIBRATION_DATE else "independent validation"},
            "scores": item["scores"], "massint_seconds": 3600, "velocity": True,
            # Exposure counts people outside the mapped river channel: a steady
            # snapshot has no dry first frame to define "the river at the start".
            "exposure_baseline": {"kind": "mapped river channel (WorldCover water corridor)",
                                  "path": (project / "channel-mask.tif").relative_to(ROOT).as_posix(),
                                  "sha256": file_hash(project / "channel-mask.tif")},
            "validation_extent": {"path": str(extent), "frame": "last",
                                  "source": f"{mask['source']}; {mask['method']}; Kabul floodplain zone only"},
        }
        write_json(project / "warsak-screening.json", config)
        published.append(warsak.finish_and_publish(s, project)["id"])
    return published


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("run", help="One snapshot run")
    one.add_argument("release_date")
    one.add_argument("mask_date")
    one.add_argument("--multiplier", type=float, default=1.0)
    one.add_argument("--channel-n", type=float, default=.035)
    sub.add_parser("sweep", help="Calibrate on 25 Aug, bracket, validate on 5 Sep")
    sub.add_parser("publish", help="Publish the chosen calibration and validation runs")
    args = parser.parse_args()
    if args.command == "run":
        result = run(args.release_date, args.mask_date, args.multiplier, args.channel_n)
        result = {k: result[k] for k in ["name", "warmup_review", "relative_mass_error", "steady_change", "wet_area_km2", "scores"]}
    elif args.command == "sweep":
        result = sweep()
    else:
        result = publish()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
