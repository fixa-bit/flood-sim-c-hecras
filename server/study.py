"""Public-data Nowshera study preparation, with evidence and held-out validation.

python -m server.study moisture|boundaries|rainfall|all
No hydraulic calibration or missing observations are manufactured here.
"""
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from .acquire import BASE, download, raster_record
from .store import file_hash, read_json, write_json

STUDY = BASE / "study"
NOAA = "https://coastwatch.noaa.gov/erddap/griddap/noaacwSMcdrDaily.nc"
START = datetime(2022, 8, 20, 1, tzinfo=timezone.utc)
END = datetime(2022, 9, 5, 1, tzinfo=timezone.utc)
TRAIN_END = datetime(2022, 8, 29, 1, tzinfo=timezone.utc)
# Checked against the three rendered original-PDF contact sheets. Preserve even
# suspicious values printed by FFC; visual transcription is not instrument QA.
REVIEWED_CUSECS = {
    "warsak": [41000, 76000, 64000, 51000, 46000, 59000, 87000, 130000, 126000, 91000, 58000, 48000, 34000, 34000, 31000, 26000, 26000],
    "charsadda-road": [10000, 21000, 13000, 15000, 13000, 19000, 46000, 140000, 104000, 45000, 34000, 20000, 19000, 17000, 15000, 14000, 17000],
    "nowshera": [None, None, 117000, 94000, 71000, 78000, 116000, 263000, 307000, 299000, 212000, 117000, 80000, 71000, 73000, 56000, 51000],
}


def write_csv(path, rows, columns=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def interpolated_boundary(rows, station, start=START, end=END):
    points = sorted(((datetime.fromisoformat(row["time"]), float(row["discharge_m3s"]), row) for row in rows if row["station_id"] == station), key=lambda point: point[0])
    if any(time.tzinfo is None or not np.isfinite(q) or q < 0 for time, q, _ in points) or len({time for time, _, _ in points}) != len(points):
        raise ValueError(f"{station}: timezone-aware, finite, nonnegative, unique observations are required.")
    if not points or points[0][0] > start or points[-1][0] < end:
        raise ValueError(f"{station}: observations do not bracket the requested model window; extrapolation refused.")
    if any((b[0] - a[0]).total_seconds() > 86400 for a, b in zip(points, points[1:])):
        raise ValueError(f"{station}: more than a day between observations; cannot prepare this daily-input experiment.")
    result, cursor = [], 0
    current = start
    while current <= end:
        while cursor + 1 < len(points) and points[cursor + 1][0] <= current:
            cursor += 1
        left = points[cursor]
        right = points[min(cursor + 1, len(points) - 1)]
        exact = current == left[0]
        fraction = 0 if exact else (current - left[0]).total_seconds() / (right[0] - left[0]).total_seconds()
        q = left[1] + fraction * (right[1] - left[1])
        result.append({"time": current.isoformat(), "station_id": station, "discharge_m3s": q,
                       "value_type": "observed" if exact else "modeled",
                       "source": left[2]["source"], "right_source": right[2]["source"],
                       "method": "visually checked FFC daily snapshot" if exact else "linear interpolation between daily snapshots; sub-daily peaks unresolved",
                       "left_observation": left[0].isoformat(), "right_observation": right[0].isoformat()})
        current += timedelta(hours=1)
    return result


def render_review():
    import pymupdf
    from PIL import Image, ImageDraw
    panels = []
    for path in sorted((BASE / "references" / "daily-ffc").glob("*.pdf")):
        with pymupdf.open(path) as doc:
            page = next((page for page in doc if "ANNEXURE-I" in page.get_text() and "Warsak" in page.get_text()), None)
            if page is None:
                continue
            labels = page.search_for("Warsak") + page.search_for("Charsadda Road") + page.search_for("Nowshera")
            clip = pymupdf.Rect(15, min(rect.y0 for rect in labels) - 20, page.rect.width - 10, max(rect.y1 for rect in labels) + 20)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(1.7, 1.7), clip=clip)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            panel = Image.new("RGB", (image.width, image.height + 24), "white")
            panel.paste(image, (0, 24))
            ImageDraw.Draw(panel).text((5, 3), path.stem, fill="black")
            panels.append(panel)
    folder = BASE / "references" / "review"
    folder.mkdir(exist_ok=True)
    for first in range(0, len(panels), 6):
        subset = panels[first:first + 6]
        image = Image.new("RGB", (max(panel.width for panel in subset), sum(panel.height for panel in subset)), "white")
        top = 0
        for panel in subset:
            image.paste(panel, (0, top))
            top += panel.height
        image.save(folder / f"upstream-review-{first // 6 + 1}.png")
    return {"documents_rendered": len(panels)}


def boundaries():
    path = BASE / "references" / "ffc-gauge-snapshots-20220820-20220905.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        raw = list(csv.DictReader(stream))
    checked = []
    for station, expected in REVIEWED_CUSECS.items():
        lookup = {row["time"][:10]: row for row in raw if row["station_id"] == station}
        for i, value in enumerate(expected):
            day = (START + timedelta(days=i)).date().isoformat()
            if value is None:
                continue  # Period-separated Nowshera source entries remain unresolved.
            row = lookup.get(day)
            if not row or float(row["discharge_cusecs"]) != value:
                raise ValueError(f"Visual review disagrees with extraction: {station} {day}")
            checked.append({**row, "quality": "original PDF visually checked; instrument accuracy not independently verified"})
    inflows = [row for station in ["warsak", "charsadda-road"] for row in interpolated_boundary(checked, station)]
    observed = [row for row in checked if row["station_id"] == "nowshera"]
    write_csv(STUDY / "reviewed-daily-observations.csv", checked)
    write_csv(STUDY / "upstream-hourly-interpolated.csv", inflows)
    write_csv(STUDY / "nowshera-heldout-observations.csv", [{"time": row["time"], "observed_m3s": row["discharge_m3s"],
               "split": "calibration" if datetime.fromisoformat(row["time"]) < TRAIN_END else "validation", "source": row["source"]} for row in observed])
    report = {"source_csv_sha256": file_hash(path), "reviewed_rows": len(checked), "boundary_stations": ["warsak", "charsadda-road"],
              "validation_station": "nowshera", "start": START.isoformat(), "end": END.isoformat(), "training_end_exclusive": TRAIN_END.isoformat(),
              "hourly_rows": len(inflows), "subdaily_observations": False, "all_contributing_inflows_measured": False,
              "review_evidence": [{"path": str(p), "sha256": file_hash(p)} for p in sorted((BASE / "references" / "review").glob("upstream-review-*.png"))],
              "limitations": ["Only Warsak and downstream Swat/Khiali at Charsadda Road are used. Munda and Chakdara are nested and are not added again.",
                              "Other Kabul tributary/lateral inflows are unmeasured; a later estimated residual must remain labeled modeled.",
                              "Daily snapshots are interpolated for a coarse routing experiment. They are not hourly gauge observations and do not reconstruct the 336,000-cusec event peak.",
                              "Two period-separated Nowshera values are omitted. High-flow conditions and damaged gauges may affect reported accuracy."]}
    write_json(STUDY / "boundary-review.json", report)
    return report


def moisture():
    from netCDF4 import Dataset
    query = "sm[(2022-08-19T00:00:00Z)][(37.625):(33.125)][(67.125):(74.375)],q_flag[(2022-08-19T00:00:00Z)][(37.625):(33.125)][(67.125):(74.375)]"
    source = NOAA + "?" + query
    original = download(source, BASE / "raw" / "moisture" / "smops-cdr-20220819-upstream.nc", max_bytes=20_000_000)
    with Dataset(original) as ds:
        lat, lon = np.asarray(ds["latitude"][:]), np.asarray(ds["longitude"][:])
        values = ds["sm"][0].astype("float32")
        flags = ds["q_flag"][0].filled(0).astype("int16")
        if ds["sm"].units != "m^3/m^3" or not np.all(np.diff(lat) < 0) or not np.all(np.diff(lon) > 0):
            raise ValueError("Unexpected NOAA units or coordinate order.")
        bad = np.ma.getmaskarray(values) | ~np.isfinite(values.data) | (values.data < 0) | (values.data > 1)
        output = STUDY / "moisture" / "noaa-smops-cdr-20220819-native-025deg.tif"
        output.parent.mkdir(parents=True, exist_ok=True)
        profile = dict(driver="GTiff", width=len(lon), height=len(lat), count=1, crs="EPSG:4326", transform=from_origin(float(lon[0] - .125), float(lat[0] + .125), .25, .25), compress="deflate")
        with rasterio.open(output, "w", **profile, dtype="float32", nodata=-9999) as dst:
            dst.write(np.where(bad, -9999, values.data).astype("float32"), 1)
            dst.update_tags(units="m3/m3", date="2022-08-19", source=source, quality="Candidate prior; raw provider quality flags retained separately and not yet decoded.")
        flag_path = output.with_name("noaa-smops-cdr-20220819-raw-quality-flags.tif")
        with rasterio.open(flag_path, "w", **profile, dtype="int16") as dst:
            dst.write(flags, 1)
        report = {"product": "NOAA SMOPS Climate Data Record surface soil moisture", "source": source,
                  "documentation": "https://coastwatch.noaa.gov/erddap/griddap/noaacwSMcdrDaily.html", "license": "CC0-1.0 (provider metadata)",
                  "original_path": str(original), "original_sha256": file_hash(original), "quality_flags_path": str(flag_path),
                  "quality_flags_sha256": file_hash(flag_path), **raster_record(output), "accepted_for_infiltration": False,
                  "limitations": ["Native 0.25-degree surface layer, not root-zone water content or SMAP-only data.",
                                  "Missing pixels are retained; no spatial filling or artificial 30 m detail.",
                                  "Provider publishes packed q_flag without flag masks/values in this ERDDAP metadata. Preserve flags; do not silently label all finite values good-quality.",
                                  "Gauge-only HEC-HMS routing does not consume initial soil moisture. Rainfall-runoff use requires quality decoding, porosity and profile-depth review."]}
    write_json(STUDY / "moisture-review.json", report)
    return report


def gsod_station(station):
    source = f"https://www.ncei.noaa.gov/data/global-summary-of-the-day/access/2022/{station}.csv"
    path = download(source, BASE / "raw" / "rain-gauges" / f"{station}-2022.csv", max_bytes=2_000_000)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return source, path, rows


def fit_rainfall_factor(rows, cutoff="2022-08-27"):
    train = [row for row in rows if row["date"] < cutoff]
    if len(train) < 8 or sum(row["chirps_mm"] for row in train) <= 0:
        raise ValueError("Insufficient complete-24h training gauge/rainfall pairs.")
    factor = sum(row["gauge_mm"] for row in train) / sum(row["chirps_mm"] for row in train)
    if not .25 <= factor <= 4:
        raise ValueError(f"Estimated regional multiplier {factor:.3f} is outside the predeclared .25-4 screening range.")
    return factor


def rainfall():
    # Peshawar, Risalpur, Saidu Sharif, Dir, Chitral: original files supply names
    # and coordinates; missing station files are recorded, not substituted.
    stations = ["41530099999", "41533099999", "41523599999", "41508099999", "41520599999", "41510099999", "41515099999", "41565099999"]
    pairs, provenance = [], []
    rain = BASE / "prepared" / "chirps-v2-kabul-catchment-daily-20220820-20220904.tif"
    def fetch(station):
        try:
            return station, gsod_station(station), None
        except Exception as exc:
            return station, None, str(exc)
    with ThreadPoolExecutor(max_workers=3) as pool:
        fetched = list(pool.map(fetch, stations))
    with rasterio.open(rain) as src:
        for station, result, error in fetched:
            if error:
                provenance.append({"station": station, "unavailable": error})
                continue
            source, path, rows = result
            provenance.append({"station": station, "name": rows[0]["NAME"], "source": source, "sha256": file_hash(path)})
            for row in rows:
                day = row["DATE"]
                flag = row["PRCP_ATTRIBUTES"].strip()
                if not "2022-08-20" <= day <= "2022-09-04" or flag not in {"D", "F", "G"} or float(row["PRCP"]) == 99.99:
                    continue
                lat, lon = float(row["LATITUDE"]), float(row["LONGITUDE"])
                if not src.bounds.left <= lon < src.bounds.right or not src.bounds.bottom < lat <= src.bounds.top:
                    continue
                band = (datetime.fromisoformat(day) - datetime(2022, 8, 20)).days + 1
                sample = next(src.sample([(lon, lat)], indexes=band, masked=True))[0]
                if np.ma.is_masked(sample) or not np.isfinite(sample) or sample < 0:
                    continue
                pairs.append({"date": day, "station": station, "name": row["NAME"], "lat": lat, "lon": lon,
                              "gauge_mm": float(row["PRCP"]) * 25.4, "chirps_mm": float(sample), "gsod_flag": flag,
                              "split": "calibration" if day < "2022-08-27" else "validation", "source": source})
        write_csv(STUDY / "rainfall" / "gsod-chirps-pairs.csv", pairs)
        diagnostics = {"stations": provenance, "complete_24h_pairs": len(pairs), "input_pair_csv": str(STUDY / "rainfall" / "gsod-chirps-pairs.csv")}
        write_json(STUDY / "rainfall-source-audit.json", diagnostics)
        try:
            factor = fit_rainfall_factor(pairs)
        except ValueError as exc:
            report = {**diagnostics, "accepted_as_basinwide_correction": False, "state": "insufficient calibration evidence", "reason": str(exc),
                      "rainfall_used_in_gauged_routing": False}
            write_json(STUDY / "rainfall-review.json", report)
            return report
        scores = {}
        for split in ["calibration", "validation"]:
            subset = [row for row in pairs if row["split"] == split]
            if not subset:
                raise ValueError("No held-out rainfall pairs.")
            obs = np.array([row["gauge_mm"] for row in subset])
            model = np.array([row["chirps_mm"] for row in subset])
            scores[split] = {"pairs": len(subset), "raw_rmse_mm": float(np.sqrt(np.mean((model - obs) ** 2))),
                             "corrected_rmse_mm": float(np.sqrt(np.mean((factor * model - obs) ** 2))),
                             "raw_total_bias_mm": float(sum(model - obs)), "corrected_total_bias_mm": float(sum(factor * model - obs))}
        values = src.read(masked=True).astype("float32") * factor
        profile = src.profile.copy()
        output = STUDY / "rainfall" / "chirps-regional-bias-candidate.tif"
        profile.update(dtype="float32", nodata=-9999)
        with rasterio.open(output, "w", **profile) as dst:
            dst.write(values.filled(-9999))
            dst.descriptions = src.descriptions
            for band in src.indexes:
                dst.update_tags(band, **src.tags(band))
            dst.update_tags(correction="single regional multiplicative candidate", factor=str(factor), training_end="2022-08-26", heldout_start="2022-08-27")
    report = {"method": "Ratio of sums fitted only on complete-24h GSOD records dated August 20-26", "multiplier": factor,
              "scores": scores, "stations": provenance, "source_rainfall_sha256": file_hash(rain), **raster_record(output),
              "heldout_rmse_improved": scores["validation"]["corrected_rmse_mm"] < scores["validation"]["raw_rmse_mm"],
              "accepted_as_basinwide_correction": False,
              "limitations": ["GSOD D/F/G flags only; incomplete/trace/missing records are excluded, never interpreted as zero.",
                              "Gauge daily accumulation windows can include the prior day; CHIRPS daily support requires alignment review. Compare multi-day totals before operational use.",
                              "Stations represent only part of the basin; one multiplier is a sensitivity candidate, not an established correction for the Afghan mountains.",
                              "CHIRPS already blends gauges, so this comparison is not necessarily independent.",
                              "The gauged-routing experiment consumes no rainfall. Applying rainfall over measured upstream catchments would double count runoff."]}
    write_json(STUDY / "rainfall-review.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=["moisture", "render-review", "boundaries", "rainfall", "all"])
    args = parser.parse_args()
    tasks = {"moisture": moisture, "render-review": render_review, "boundaries": boundaries, "rainfall": rainfall}
    for name in tasks if args.task == "all" else [args.task]:
        report = tasks[name]()
        print(f"Prepared {name} in {STUDY}", flush=True)


if __name__ == "__main__":
    main()
