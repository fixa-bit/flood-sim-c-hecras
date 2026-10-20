"""Preserve official daily FFC PDFs and cautiously transcribe gauge snapshots.

Rows retain their document, page, original units and reported local time.
They are reference observations, not a model-ready inflow hydrograph.
"""
import csv
from datetime import datetime, timedelta, timezone
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from pypdf import PdfReader
from .acquire import BASE, download
from .store import file_hash, write_json

STATIONS = {"Tarbela": "tarbela", "Kalabagh": "kalabagh", "Chashma": "chashma", "Taunsa": "taunsa", "Guddu": "guddu",
            "Sukkur": "sukkur", "Kotri": "kotri", "Warsak": "warsak", "Nowshera": "nowshera",
            "Chakdara": "chakdara", "Munda": "munda", "Charsadda Road": "charsadda-road", "Mangla": "mangla", "Marala": "marala"}


def extract_table(text, day, source, page_number):
    lines = text.splitlines()
    # Require the reported observation time instead of inventing midnight.
    time_match = re.search(r"\bat\s+(\d{4})\s+Hours", text, re.I)
    if not time_match or not re.search(r"ANNEXURE[ -]*I\b", text, re.I):
        return []
    hour, minute = int(time_match[1][:2]), int(time_match[1][2:])
    if hour > 23 or minute > 59:
        return []
    time_local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone(timedelta(hours=5)))
    # Locate both repeated Inflow/Outflow column pairs. Only parse the current Outflow column.
    header = next((line for line in lines if len(re.findall(r"\bOutflow\b", line, re.I)) >= 2 and len(re.findall(r"\bInflow\b", line, re.I)) >= 2), None)
    if not header:
        return []
    positions = [match.start() + len(match[0]) / 2 for match in re.finditer(r"\b(?:Inflow|Outflow)\b", header, re.I)]
    if len(positions) != 4:
        return []
    center, half_width = positions[3], min(positions[3] - positions[2], positions[1] - positions[0]) / 2
    output = []
    for line in lines:
        station = next((identifier for label, identifier in STATIONS.items() if re.search(r"\b" + re.escape(label) + r"\b", line, re.I)), None)
        if not station:
            continue
        candidates = []
        for match in re.finditer(r"(?<![\w.,])\d{1,3}(?:\s*,\s*\d{3})+(?![\w.,])|(?<![\w.,])\d+(?![\w.,]|\s*,)", line):
            value_center = match.start() + len(match[0]) / 2
            if abs(value_center - center) < half_width:
                candidates.append(match[0])
        if len(candidates) != 1:
            continue
        cusecs = int(re.sub(r"[\s,]", "", candidates[0]))
        if not 0 <= cusecs <= 2_000_000:
            continue
        output.append({"time": time_local.astimezone(timezone.utc).isoformat(), "reported_time_local": time_local.isoformat(),
                       "station_id": station, "discharge_cusecs": cusecs, "discharge_m3s": cusecs * 0.028316846592,
                       "measurement": "reported current outflow / gauge discharge", "source": source, "page": page_number,
                       "value_type": "observed", "quality": "PDF column extraction; visual review required", "source_line": line.strip()})
    return output


def fetch_day(day):
    folder = BASE / "references" / "daily-ffc"
    errors = []
    for suffix in ["", "-1", "-2"]:
        url = f"https://www.ffc.gov.pk/wp-content/uploads/{day:%Y/%m}/DFSR-{day:%d-%m-%Y}{suffix}.pdf"
        path = folder / f"FFC-{day.isoformat()}{suffix}.pdf"
        try:
            download(url, path, max_bytes=20_000_000)
            reader = PdfReader(path)
            page_texts = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
            text = "\n\n".join(page_texts)
            if str(day.year) not in text or "FLOOD" not in text.upper():
                raise ValueError("Downloaded document is not the expected flood bulletin.")
            path.with_suffix(".txt").write_text(text, encoding="utf-8")
            observations = [row for index, page in enumerate(page_texts, 1) for row in extract_table(page, day, url, index)]
            return {"date": day.isoformat(), "source": url, "path": str(path), "sha256": file_hash(path), "pages": len(reader.pages), "extracted_observations": len(observations)}, observations
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}")
    return {"date": day.isoformat(), "state": "unavailable", "attempts": errors}, []


def main():
    days = [(datetime(2022, 8, 20) + timedelta(days=index)).date() for index in range(17)]
    records, observations = [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for record, rows in pool.map(fetch_day, days):
            records.append(record)
            observations.extend(rows)
            print(f"{record['date']}: {'downloaded' if 'path' in record else 'unavailable'}; {len(rows)} extracted rows", flush=True)
    observations.sort(key=lambda row: (row["time"], row["station_id"]))
    output = BASE / "references" / "ffc-gauge-snapshots-20220820-20220905.csv"
    if observations:
        with output.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(observations[0]))
            writer.writeheader()
            writer.writerows(observations)
        normalized = output.with_name("ffc-observed-gauges-review-required.csv")
        with normalized.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["time", "station_id", "observed_m3s", "simulated_m3s", "source", "quality"])
            writer.writeheader()
            for row in observations:
                writer.writerow({"time": row["time"], "station_id": row["station_id"], "observed_m3s": row["discharge_m3s"],
                                 "simulated_m3s": "", "source": row["source"], "quality": row["quality"]})
    report = {"source": "Federal Flood Commission, Government of Pakistan", "documents": records,
              "observations": len(observations), "stations": sorted({row["station_id"] for row in observations}),
              "csv": str(output) if observations else None,
              "limitations": ["Reported local time assumed PKT UTC+05:00, preserving the document's time label.",
                              "Current outflow column only; not historical-peak or previous-year columns.",
                              "Automated transcriptions require visual review. Missing or ambiguous entries are omitted; no interpolation or peak reconstruction.",
                              "Not registered as a complete hydraulic boundary. Tributary contributions, event peaks, sampling and model-time coverage require review."]}
    write_json(BASE / "references" / "ffc-bulletin-index.json", report)


if __name__ == "__main__":
    main()
