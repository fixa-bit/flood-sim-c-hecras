"""Timestamp-aligned validation; undefined skill is reported as null."""
import csv
from datetime import datetime
from pathlib import Path
import numpy as np


def gauge_metrics(observed, simulated):
    obs, sim = np.asarray(observed, dtype=float), np.asarray(simulated, dtype=float)
    valid = np.isfinite(obs) & np.isfinite(sim)
    obs, sim = obs[valid], sim[valid]
    count = len(obs)
    if count < 3:
        return {"pairs": count, "nse": None, "kge": None, "rmse_m3s": None, "reason": "At least three finite, aligned pairs are required."}
    variance = np.sum((obs - obs.mean()) ** 2)
    nse = float(1 - np.sum((sim - obs) ** 2) / variance) if variance > 0 else None
    kge = None
    if obs.std() > 0 and sim.std() > 0 and obs.mean() != 0:
        r = np.corrcoef(obs, sim)[0, 1]
        kge = float(1 - np.sqrt((r - 1) ** 2 + (sim.std() / obs.std() - 1) ** 2 + (sim.mean() / obs.mean() - 1) ** 2))
    return {"pairs": count, "nse": nse, "kge": kge, "rmse_m3s": float(np.sqrt(np.mean((sim - obs) ** 2)))}


def extent_metrics(observed, simulated, valid=None):
    obs, sim = np.asarray(observed, bool), np.asarray(simulated, bool)
    if obs.shape != sim.shape:
        raise ValueError("Observed and modeled extents must use an identical grid.")
    valid = np.ones(obs.shape, bool) if valid is None else np.asarray(valid, bool)
    hits = int(np.sum(obs & sim & valid))
    misses = int(np.sum(obs & ~sim & valid))
    false_alarms = int(np.sum(~obs & sim & valid))
    return {"hits": hits, "misses": misses, "false_alarms": false_alarms,
            "csi": hits / (hits + misses + false_alarms) if hits + misses + false_alarms else None,
            "pod": hits / (hits + misses) if hits + misses else None,
            "far": false_alarms / (hits + false_alarms) if hits + false_alarms else None}


def read_hydrographs(path: Path):
    groups = {}
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            time = datetime.fromisoformat(row["time"].replace("Z", "+00:00"))
            if time.tzinfo is None:
                raise ValueError("Hydrograph times require a timezone.")
            station = row["station_id"].strip()
            if (station, time) in seen:
                raise ValueError("Duplicate station/timestamp in gauge data.")
            seen.add((station, time))
            obs = float(row["observed_m3s"]) if row.get("observed_m3s", "").strip() else None
            sim = float(row["simulated_m3s"]) if row.get("simulated_m3s", "").strip() else None
            if any(v is not None and (not np.isfinite(v) or v < 0) for v in [obs, sim]):
                raise ValueError("Discharge must be finite, nonnegative m³/s or blank.")
            item = {"time": time.isoformat(), "observed_m3s": obs, "simulated_m3s": sim}
            lower, upper = row.get("lower_m3s", ""), row.get("upper_m3s", "")
            if lower or upper:
                low, high = float(lower), float(upper)
                if not (np.isfinite(low) and np.isfinite(high) and 0 <= low <= high):
                    raise ValueError("Uncertainty bounds require 0 <= lower <= upper.")
                item.update(lower_m3s=low, upper_m3s=high)
            groups.setdefault(station, []).append(item)
    output = []
    for station, samples in groups.items():
        samples.sort(key=lambda r: r["time"])
        metrics = gauge_metrics([np.nan if r["observed_m3s"] is None else r["observed_m3s"] for r in samples],
                                [np.nan if r["simulated_m3s"] is None else r["simulated_m3s"] for r in samples])
        output.append({"station_id": station, "samples": samples, "metrics": metrics})
    return output
