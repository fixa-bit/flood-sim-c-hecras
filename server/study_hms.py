"""Fit an upstream routing experiment using the installed HEC-HMS engine.

This is hydrologic routing calibration, not a calibrated 2-D inundation model.
All hydrographs are computed by HEC-HMS; Python only prepares data and scores.
"""
import csv
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timedelta, timezone

import numpy as np

from .metrics import gauge_metrics
from .store import ROOT, file_hash, read_json, write_json
from .study import STUDY, START, END, TRAIN_END, boundaries, write_csv

PROJECT = STUDY / "hec-hms"


def installation():
    runtime = read_json(ROOT / "runtimes.json", {})
    return Path(runtime["hec_hms_exe"]).parent


def run_script(path, log):
    home = installation()
    jars = f"{home / 'hms.jar'};{home / 'lib' / '*'}"
    libraries = f"{home / 'bin'};{home / 'bin' / 'gdal'};{home / 'bin' / 'hdf'}"
    env = os.environ.copy()
    env.update(PATH=libraries + ";" + env.get("PATH", ""), GDAL_DATA=str(home / "bin/gdal/gdal-data"), PROJ_LIB=str(home / "bin/gdal/projlib"))
    command = [str(home / "jre/bin/java.exe"), "-Djava.awt.headless=true", "-Dpython.import.site=false", f"-Dpython.path={jars}",
               f"-Djava.library.path={libraries}", "-classpath", jars, "hms.Hms", "-s", str(path.resolve())]
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=home, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
    text = log.read_text(encoding="utf-8", errors="replace")
    if result.returncode or "Traceback" in text or "ERROR " in text:
        raise RuntimeError(f"HEC-HMS script failed; inspect {log}")


def project_files(candidates):
    PROJECT.mkdir(parents=True, exist_ok=True)
    def save(name, text):
        import re
        text = re.sub(r"(?m)^(\S[^\n]*:) ([^\n]+)\n", r"\1 \2\n     Last Modified Date: 20 October 2026\n     Last Modified Time: 00:00:00\n", text)
        (PROJECT / name).write_text(text, encoding="utf-8")
    header = "Project: upstream\n     Version: 4.14\n     Filepath Separator: /\n     DSS File Name: inputs.dss\n     Time Zone ID: UTC\nEnd:\n\n"
    header += "Precipitation: GaugeOnly\n     Filename: GaugeOnly.met\nEnd:\n\nControl: Event\n     FileName: Event.control\nEnd:\n\n"
    runs = ""
    for name, upper_k, swat_k in candidates:
        header += f"Basin: {name}\n     Filename: {name}.basin\nEnd:\n\n"
        runs += f"Run: {name}\n     Default Description: Yes\n     Log File: {name}.log\n     DSS File: {name}.dss\n     Is Save Spatial Results: No\n     Basin: {name}\n     Precip: GaugeOnly\n     Control: Event\n     Save State Type: None\n     Time-Series Output: Save All\nEnd:\n\n"
        basin = f"Basin: {name}\n     Version: 4.14\n     Filepath Separator: /\n     Unit System: Metric\n     Missing Flow To Zero: No\n     Enable Flow Ratio: No\n     Compute Local Flow At Junctions: No\n     Enable Sediment Routing: No\nEnd:\n\n"
        for station, k, x in [("Warsak", upper_k, 0), ("SwatCharsadda", swat_k, 200)]:
            basin += f"Source: {station}\n     Canvas X: {x}\n     Canvas Y: 1000\n     Downstream: {station}Route\n     Flow Method: GAGE_FLOW\n     Flow Gage: {station}\n     End Flow Method:\nEnd:\n\n"
            basin += f"Reach: {station}Route\n     Canvas X: {x}\n     Canvas Y: 500\n     From Canvas X: {x}\n     From Canvas Y: 1000\n     Downstream: Nowshera\n     Route: Muskingum\n     Initial Variable: Combined Inflow\n     Muskingum K: {k}\n     Muskingum x: 0.0\n     Muskingum Steps: 1\n     Channel Loss: None\nEnd:\n\n"
        basin += "Source: UnmeasuredLocal\n     Canvas X: 400\n     Canvas Y: 500\n     Downstream: Nowshera\n     Flow Method: GAGE_FLOW\n     Flow Gage: UnmeasuredLocal\n     End Flow Method:\nEnd:\n\nJunction: Nowshera\n     Canvas X: 100\n     Canvas Y: 0\nEnd:\n"
        save(name + ".basin", basin)
    save("upstream.hms", header)
    save("upstream.run", runs)
    save("Event.control", "Control: Event\n     Version: 4.14\n     Start Date: 20 August 2022\n     Start Time: 01:00\n     End Date: 5 September 2022\n     End Time: 01:00\n     Time Interval: 60\nEnd:\n")
    save("GaugeOnly.met", "Meteorology: GaugeOnly\n     Version: 4.14\n     Unit System: Metric\n     Set Missing Data to Default: No\n     Precipitation Method: Specified Average\n     Evapotranspiration Method: None\n     Snowmelt Method: None\n" + "".join(f"     Use Basin Model: {name}\n" for name, _, _ in candidates) + "End:\n\nPrecip Method Parameters: Specified Average\n     Allow Depth Override: No\nEnd:\n")
    gages = "Gage Manager: upstream\n     Version: 4.14\n     Filepath Separator: /\nEnd:\n\n"
    for name in ["Warsak", "SwatCharsadda", "UnmeasuredLocal"]:
        gages += f"Gage: {name}\n     Gage: {name}\n     Gage Type: Flow\n     Data Source Type: External DSS\n     Filename: inputs.dss\n     Pathname: /KABUL/{name.upper()}/FLOW//1HOUR/FFC-DAILY-INTERPOLATED/\n     Variant: Variant-1\n       Start Time: 20 August 2022, 01:00\n       End Time: 5 September 2022, 01:00\n     End Variant: Variant-1\nEnd:\n\n"
    save("upstream.gage", gages)


def compute_batch(candidates, local_m3s, prefix):
    with (STUDY / "upstream-hourly-interpolated.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    values = {"Warsak": [float(row["discharge_m3s"]) for row in rows if row["station_id"] == "warsak"],
              "SwatCharsadda": [float(row["discharge_m3s"]) for row in rows if row["station_id"] == "charsadda-road"]}
    values["UnmeasuredLocal"] = [local_m3s] * len(values["Warsak"])
    write_json(PROJECT / f"{prefix}-inputs.json", values)
    for name in ["upstream.hms", "upstream.gage"]:
        path = PROJECT / name
        path.write_text(path.read_text(encoding="utf-8").replace("inputs.dss", f"{prefix}-inputs.dss"), encoding="utf-8")
    write_json(PROJECT / f"{prefix}-project-text.json", {path.name: path.read_text(encoding="utf-8") for path in PROJECT.iterdir() if path.suffix in {".hms", ".run", ".gage", ".control", ".met", ".basin"}})
    script = PROJECT / f"{prefix}-compute.py"
    script.write_text("""from hms.model.JythonHms import *
from hec.heclib.dss import HecDss
from hec.io import TimeSeriesContainer
from hec.heclib.util import HecTime
import jarray
import json
import os
folder = %r
values = json.load(open(os.path.join(folder, %r)))
f = HecDss.open(os.path.join(folder, %r))
origin = HecTime('20Aug2022', '0100')
for name, data in values.items():
    ts = TimeSeriesContainer()
    ts.fullName = '/KABUL/' + name.upper() + '/FLOW//1HOUR/FFC-DAILY-INTERPOLATED/'
    ts.interval = 60
    ts.units = 'CMS'
    ts.type = 'INST-VAL'
    ts.times = jarray.array([origin.value() + i * 60 for i in range(len(data))], 'i')
    ts.values = jarray.array(data, 'd')
    ts.numberValues = len(data)
    ts.startTime = ts.times[0]
    ts.endTime = ts.times[-1]
    ts.startHecTime = HecTime()
    ts.startHecTime.set(ts.startTime)
    ts.endHecTime = HecTime()
    ts.endHecTime.set(ts.endTime)
    f.put(ts)
f.done()
OpenProject('upstream', folder)
out = open(os.path.join(folder, %r), 'w')
out.write('model,hec_minutes,discharge_m3s\\n')
for run in %r:
    Compute(run)
    dss = HecDss.open(os.path.join(folder, run + '.dss'))
    for path in dss.getCatalogedPathnames():
        parts = path.split('/')
        if parts[2].upper() != 'NOWSHERA' or parts[3].upper() != 'FLOW':
            continue
        ts = dss.get(path)
        for minute, value in zip(ts.times, ts.values):
            if value >= 0 and value < 1000000:
                out.write('%%s,%%d,%%.10f\\n' %% (run, minute, value))
    dss.done()
out.close()
from java.lang import System
System.exit(0)
""" % (PROJECT.as_posix(), f"{prefix}-inputs.json", f"{prefix}-inputs.dss", f"{prefix}-outputs.csv", [item[0] for item in candidates]), encoding="utf-8")
    run_script(script, PROJECT / f"{prefix}-engine.log")
    with (PROJECT / f"{prefix}-outputs.csv").open(encoding="utf-8", newline="") as stream:
        result = list(csv.DictReader(stream))
    grouped = {}
    epoch = datetime(1899, 12, 31, tzinfo=timezone.utc)
    for row in result:
        time = epoch + timedelta(minutes=int(row["hec_minutes"]))
        if START <= time <= END:
            grouped.setdefault(row["model"], {})[time.isoformat()] = float(row["discharge_m3s"])
    for name, _, _ in candidates:
        expected = {(START + timedelta(hours=hour)).isoformat() for hour in range(int((END - START).total_seconds() / 3600) + 1)}
        if set(grouped.get(name, {})) != expected:
            raise ValueError(f"{name}: HEC-HMS did not produce the complete requested hourly series.")
    return grouped


def select_parameters(candidates, baseline, observed):
    train = [row for row in observed if datetime.fromisoformat(row["time"]) < TRAIN_END]
    if len(train) < 3:
        raise ValueError("At least three calibration observations are required.")
    scores = []
    for name, upper_k, swat_k in candidates:
        o = np.array([float(row["observed_m3s"]) for row in train])
        m = np.array([baseline[name][row["time"]] for row in train])
        # Constant unmeasured lateral contribution estimated from TRAINING ONLY.
        # It is not an observed tributary series or an event-wide residual replay.
        local = float(max(0, np.mean(o - m)))
        metric = gauge_metrics(o, m + local)
        scores.append({"model": name, "warsak_k_hours": upper_k, "swat_k_hours": swat_k,
                       "muskingum_x": 0, "estimated_local_constant_m3s": local, **metric})
    return min(scores, key=lambda row: row["rmse_m3s"]), scores


def main():
    boundaries()
    candidates = [(f"C{i:02d}", k, s) for i, (k, s) in enumerate((k, s) for k in [1, 3, 6, 12, 24, 36] for s in [1, 3, 6, 12, 24])]
    project_files(candidates)
    baseline = compute_batch(candidates, 0, "calibration")
    with (STUDY / "nowshera-heldout-observations.csv").open(encoding="utf-8", newline="") as stream:
        observed = list(csv.DictReader(stream))
    best, scores = select_parameters(candidates, baseline, observed)
    final = [("FittedRouting", best["warsak_k_hours"], best["swat_k_hours"])]
    project_files(final)
    output = compute_batch(final, best["estimated_local_constant_m3s"], "fitted")["FittedRouting"]
    validation = {}
    for split in ["calibration", "validation"]:
        subset = [row for row in observed if row["split"] == split]
        validation[split] = {"samples": len(subset), **gauge_metrics([float(row["observed_m3s"]) for row in subset], [output[row["time"]] for row in subset])}
    write_csv(STUDY / "routing-calibration-candidates.csv", scores)
    obs_lookup = {row["time"]: row for row in observed}
    write_csv(STUDY / "hms-nowshera-hourly-modeled.csv", [{"time": time, "station_id": "nowshera", "discharge_m3s": q,
              "value_type": "modeled", "source": "HEC-HMS 4.14 FittedRouting; see routing-calibration.json", "observed_m3s": obs_lookup.get(time, {}).get("observed_m3s", ""),
              "split": obs_lookup.get(time, {}).get("split", "unobserved")} for time, q in sorted(output.items())])
    report = {"state": "computed-and-fit; hydraulic calibration remains open", "engine": "HEC-HMS 4.14", "project": str(PROJECT / "upstream.hms"),
              "run": "FittedRouting", "parameters": best, "scores": validation, "calibration_end_exclusive": TRAIN_END.isoformat(),
              "validation_data_used_for_fitting": False, "candidates": len(candidates), "rainfall_used": False, "initial_soil_moisture_used": False,
              "boundary_csv_sha256": file_hash(STUDY / "upstream-hourly-interpolated.csv"),
              "output_csv_sha256": file_hash(STUDY / "hms-nowshera-hourly-modeled.csv"),
              "engine_jar_sha256": file_hash(installation() / "hms.jar"),
              "fitted_inputs": [{"path": filename, "sha256": file_hash(PROJECT / filename)} for filename in ["upstream.hms", "upstream.run", "upstream.gage", "Event.control", "GaugeOnly.met", "FittedRouting.basin", "fitted-inputs.dss"]],
              "validation_targets_met": validation["validation"]["nse"] is not None and validation["validation"]["nse"] >= .65 and validation["validation"]["kge"] is not None and validation["validation"]["kge"] >= .6,
              "limitations": ["Single-event daily sampling, seven calibration observations and eight validation observations. Not independent-event validation.",
                              "Hourly values are interpolated, not observed. Unmeasured laterals are a fitted constant, not complete tributary hydrographs.",
                              "Manning roughness, bed/bathymetry, structures and inundation extents have not been calibrated by routing discharge.",
                              "Rainfall and initial moisture are unused in gauged-source routing; no rainfall correction is necessary for this branch. Rainfall-runoff variants require separate acceptance.",
                              "HEC-HMS computes Muskingum routing; this code adds no custom flow solver."]}
    write_json(STUDY / "routing-calibration.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
