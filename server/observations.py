"""Observed 2022 river flows from FFC daily reports and the WAPDA river-flow workbook.

Run `python -m server.observations --help`.

Measured or reported values only. Nothing is interpolated, filled in or
adjusted. A row whose numbers cannot be placed unambiguously in the report's
own columns is left out and listed in the review. These are once-a-day values
(FFC: the 06:00 PKT reading; WAPDA: daily values), so they serve as observed
hydrographs for display and model checking, never as model forcing.
"""
import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
import json
import re
import shutil
from pathlib import Path

from .acquire import BASE as NOWSHERA_BASE, download
from .store import ROOT, file_hash, read_json, write_json

SOURCE_DIR = ROOT / "downloads" / "observations-2022"
OUTPUT = ROOT / "observations"
TABLE = OUTPUT / "observed-daily-2022.csv"
REVIEW = OUTPUT / "observed-daily-2022-review.json"
PKT = timezone(timedelta(hours=5))
CUSECS_TO_M3S = 0.028316846592
FFC_FIRST, FFC_LAST = date(2022, 6, 15), date(2022, 10, 15)
WAPDA_URL = "https://wapda.gov.pk/wp-content/uploads/2024/12/GRAPH-DG-16-for-MAIL-2.xls"
WAPDA_PAGE = "https://wapda.gov.pk/river-flow/"
# Printed row label -> (catalogue station id, river). Order matters only for
# labels that contain another ("Charsadda Road" before nothing shorter).
FFC_STATIONS = [
    ("Tarbela", "tarbela", "Indus"), ("Kalabagh", "kalabagh", "Indus"), ("Chashma", "chashma", "Indus"),
    ("Taunsa", "taunsa", "Indus"), ("Guddu", "guddu", "Indus"), ("Sukkur", "sukkur", "Indus"), ("Kotri", "kotri", "Indus"),
    ("Warsak", "warsak", "Kabul"), ("Nowshera", "nowshera", "Kabul"),
    ("Chakdara", "chakdara", "Swat"), ("Munda", "munda", "Swat"), ("Charsadda Road", "charsadda-road", "Swat"),
    ("Mangla", "mangla", "Jhelum"), ("Rasul", "rasul", "Jhelum"),
    ("Marala", "marala", "Chenab"), ("Khanki", "khanki", "Chenab"), ("Qadirabad", "qadirabad", "Chenab"),
    ("Trimmu", "trimmu", "Chenab"), ("Panjnad", "panjnad", "Chenab"),
    ("Jassar", "jassar", "Ravi"), ("Shahdara", "shahdara", "Ravi"), ("Balloki", "balloki", "Ravi"), ("Sidhnai", "sidhnai", "Ravi"),
    ("Sule?imanki", "suleimanki", "Sutlej"), ("Islam", "islam", "Sutlej"),
]
# WAPDA GHRAPH sheet columns (thousand cusecs) -> (station id, river, quantity).
WAPDA_COLUMNS = {2: ("tarbela", "Indus", "inflow"), 3: ("tarbela", "Indus", "outflow"),
                 4: ("nowshera", "Kabul", "inflow"), 6: ("mangla", "Jhelum", "inflow"),
                 7: ("mangla", "Jhelum", "outflow"), 8: ("marala", "Chenab", "inflow")}
WAPDA_HEADERS = {2: "INFLOW", 3: "OUTFLOW", 4: "KABUL INFLOW AT NOWSHERA", 6: "INFLOW", 7: "OUTFLOW",
                 8: "CHENAB INFLOW AT MARALA"}
WAPDA_LABELS = {2: "Indus at Tarbela", 3: "Indus at Tarbela", 4: "Kabul inflow at Nowshera",
                6: "Jhelum at Mangla", 7: "Jhelum at Mangla", 8: "Chenab inflow at Marala"}
COLUMNS = ["date", "time_local", "time_utc", "station_id", "station_label", "river", "quantity",
           "discharge_cusecs", "discharge_m3s", "reported_as", "cadence", "source", "document", "document_sha256",
           "page", "source_line"]
# Rows may start with a bullet glyph (e.g. U+F0B7) before the station name.
LEAD = r"\s*(?:[^\w\s(]\s*)?"
# Thousands groups may carry stray spaces around the comma ("292 ,000"), as the
# earlier FFC extractor also allows; a bare group is never read off such a number.
NUMBER = re.compile(r"(?<![\w,.\-/])(\d{1,3}(?:\s*,\s*\d{3})+|\d+)(?![\w.\-/]|\s*,\s*\d)|\bNIL\b", re.I)
MALFORMED = re.compile(r"(?<![\w,.\-/])\d{1,3}\.\d{3}(?![\w,.\-/])")


def ffc_url(day, suffix=""):
    return f"https://www.ffc.gov.pk/wp-content/uploads/{day:%Y/%m}/DFSR-{day:%d-%m-%Y}{suffix}.pdf"


def fetch_ffc(day):
    """Download one day's report, reusing a copy already in the Nowshera references."""
    folder = SOURCE_DIR / "ffc"
    errors = []
    for suffix in ["", "-1", "-2"]:
        target = folder / f"DFSR-{day.isoformat()}{suffix}.pdf"
        existing = NOWSHERA_BASE / "references" / "daily-ffc" / f"FFC-{day.isoformat()}{suffix}.pdf"
        try:
            if not target.is_file() and existing.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(existing, target)
            download(ffc_url(day, suffix), target, max_bytes=20_000_000)
            return {"date": day.isoformat(), "url": ffc_url(day, suffix), "path": target.relative_to(ROOT).as_posix(),
                    "sha256": file_hash(target)}
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, none is fatal
            errors.append(f"{ffc_url(day, suffix)}: {type(exc).__name__}")
    return {"date": day.isoformat(), "state": "unavailable", "attempts": errors}


def acquire():
    """Download the WAPDA workbook and every FFC daily report of the 2022 season."""
    workbook = download(WAPDA_URL, SOURCE_DIR / "wapda" / "river-flow-GRAPH-DG-16.xls", max_bytes=50_000_000)
    days = [FFC_FIRST + timedelta(days=i) for i in range((FFC_LAST - FFC_FIRST).days + 1)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        documents = list(pool.map(fetch_ffc, days))
    index = {"wapda": {"url": WAPDA_URL, "page": WAPDA_PAGE, "path": workbook.relative_to(ROOT).as_posix(),
                       "sha256": file_hash(workbook)},
             "ffc": documents, "acquired_at": datetime.now(timezone.utc).isoformat()}
    write_json(SOURCE_DIR / "index.json", index)
    return {"wapda_sha256": index["wapda"]["sha256"][:12],
            "ffc_downloaded": sum(1 for d in documents if "path" in d),
            "ffc_unavailable": [d["date"] for d in documents if "path" not in d]}


def _centres(line):
    return [((match.start() + match.end()) / 2, int(match[0])) for match in re.finditer(r"\b\d{1,2}\b", line)]


def parse_ffc_page(text):
    """River-flow rows of an Annexure-I page: today's 06:00 inflow and outflow.

    Returns (rows, skipped). Every number on a station line must sit closest
    to a distinct numbered column, in order; otherwise the line is skipped.
    """
    if not re.search(r"ANNEXURE[ -]*I\b", text, re.I) or not re.search(r"River\s+Flow\s+Situation", text, re.I):
        return None, []
    stamp = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})\s+at\s+(\d{4})\s+Hours", text)
    if not stamp:
        return None, ["no 'Month DD, YYYY at HHMM Hours' table stamp"]
    table_day = datetime.strptime(f"{stamp[1]} {stamp[2]} {stamp[3]}", "%B %d %Y").date()
    clock = time(int(stamp[4][:2]), int(stamp[4][2:]))
    lines = text.splitlines()
    header_index = next((i for i, line in enumerate(lines)
                         if [n for _, n in _centres(line)][:10] == list(range(1, 11))), None)
    if header_index is None:
        return None, ["no numbered column header 1-10"]
    centres = {number: x for x, number in _centres(lines[header_index])[:10]}
    rows, skipped = [], []
    for line in lines[header_index + 1:]:
        if re.search(r"Reservoir\s+Storage\s+Position", line, re.I):
            break
        label = next(((pattern, station, river) for pattern, station, river in FFC_STATIONS
                      if re.match(LEAD + pattern + r"\b", line, re.I)), None)
        if not label:
            continue
        for bad in MALFORMED.finditer(line):
            # e.g. "42.000": probably 42,000, but correcting the source is not ours to do.
            skipped.append({"line": line.strip(), "reason": f"malformed number {bad[0]!r} left out"})
        tokens = [((m.start() + m.end()) / 2, m[0]) for m in NUMBER.finditer(line)]
        placed = []
        for x, token in tokens:
            column = min(centres, key=lambda c: abs(centres[c] - x))
            placed.append((column, token))
        columns = [column for column, _ in placed]
        if len(set(columns)) != len(columns) or columns != sorted(columns):
            skipped.append({"line": line.strip(), "reason": "numbers do not map to distinct, ordered columns"})
            continue
        values = dict(placed)
        for column, quantity in [(7, "inflow"), (8, "outflow")]:
            if column not in values:
                continue
            token = values[column]
            cusecs = 0 if token.upper() == "NIL" else int(re.sub(r"[\s,]", "", token))
            if not 0 <= cusecs <= 2_000_000:
                skipped.append({"line": line.strip(), "reason": f"{quantity} {token} outside 0-2,000,000 cusecs"})
                continue
            printed = re.match(LEAD + r"(.+?)(?:\s{2,}|$)", line)
            rows.append({"station_id": label[1], "station_label": printed.group(1).strip() if printed else label[1],
                         "river": label[2], "quantity": quantity, "discharge_cusecs": cusecs, "reported_as": token,
                         "source_line": line.strip()})
    stamp_local = datetime.combine(table_day, clock, PKT)
    for row in rows:
        row.update(date=table_day.isoformat(), time_local=stamp_local.isoformat(),
                   time_utc=stamp_local.astimezone(timezone.utc).isoformat())
    return rows, skipped


def ffc_rows(index):
    from pypdf import PdfReader
    output, review = [], []
    for document in index["ffc"]:
        if "path" not in document:
            continue
        path = ROOT / document["path"]
        if file_hash(path) != document["sha256"]:
            raise ValueError(f"{path.name} changed after acquisition.")
        reader = PdfReader(path)
        found = False
        for number, page in enumerate(reader.pages, 1):
            rows, skipped = parse_ffc_page(page.extract_text(extraction_mode="layout") or "")
            if rows is None:
                continue
            found = True
            report_day = date.fromisoformat(document["date"])
            for row in rows:
                row.update(cadence="06:00 PKT reading", source="FFC daily flood situation report",
                           document=document["url"], document_sha256=document["sha256"], page=number,
                           discharge_m3s=round(row["discharge_cusecs"] * CUSECS_TO_M3S, 3))
                output.append(row)
            entry = {"date": document["date"], "page": number, "rows": len(rows), "skipped": skipped}
            if rows and rows[0]["date"] != report_day.isoformat():
                entry["table_date_differs_from_file_date"] = rows[0]["date"]
            review.append(entry)
        if not found:
            review.append({"date": document["date"], "rows": 0, "skipped": [], "note": "no Annexure-I river-flow table found"})
    return output, review


def wapda_rows(index):
    import xlrd
    path = ROOT / index["wapda"]["path"]
    if file_hash(path) != index["wapda"]["sha256"]:
        raise ValueError("The WAPDA workbook changed after acquisition.")
    book = xlrd.open_workbook(path)
    sheet = book.sheet_by_name("GHRAPH")
    units = str(sheet.cell_value(1, 9))
    if "1000" not in units or "CUSECS" not in units.upper():
        raise ValueError(f"Unexpected WAPDA units note: {units!r}")
    headers = " | ".join(str(sheet.cell_value(r, c)) for r in (2, 3) for c in range(sheet.ncols))
    for column, expected in WAPDA_HEADERS.items():
        printed = f"{sheet.cell_value(2, column)} {sheet.cell_value(3, column)}".upper()
        if expected not in printed:
            raise ValueError(f"WAPDA column {column} reads {printed!r}, expected {expected!r}.")
    output, zeros = [], []
    for r in range(4, sheet.nrows):
        stamp = sheet.cell_value(r, 0)
        if not isinstance(stamp, float) or stamp < 40000:
            continue
        day = xlrd.xldate_as_datetime(stamp, book.datemode).date()
        if day.year != 2022:
            continue
        for column, (station, river, quantity) in WAPDA_COLUMNS.items():
            value = sheet.cell_value(r, column)
            if not isinstance(value, float):
                continue
            if value == 0:
                zeros.append({"date": day.isoformat(), "station_id": station, "quantity": quantity})
                continue  # a zero may be a missing-data code; left out, listed in the review
            cusecs = round(value * 1000)
            output.append({"date": day.isoformat(), "time_local": "", "time_utc": "", "station_id": station,
                           "station_label": WAPDA_LABELS[column],
                           "river": river, "quantity": quantity, "discharge_cusecs": cusecs,
                           "discharge_m3s": round(cusecs * CUSECS_TO_M3S, 3), "reported_as": f"{value:g} thousand cusecs",
                           "cadence": "WAPDA daily value (definition per WAPDA; 24-hour mean at Tarbela/Nowshera/Mangla, 06:00 at Marala in its press releases)",
                           "source": "WAPDA river-flow workbook (GHRAPH sheet)", "document": WAPDA_URL,
                           "document_sha256": index["wapda"]["sha256"], "page": f"row {r + 1}", "source_line": ""})
    return output, {"headers": headers, "zeros_left_out": zeros}


def build():
    index = read_json(SOURCE_DIR / "index.json")
    if not index:
        raise ValueError("Run python -m server.observations acquire first.")
    ffc, ffc_review = ffc_rows(index)
    wapda, wapda_review = wapda_rows(index)
    rows = sorted(ffc + wapda, key=lambda r: (r["station_id"], r["date"], r["source"], r["quantity"]))
    identities = [(r["station_id"], r["date"], r["source"], r["quantity"]) for r in rows]
    duplicates = sorted({key for key in identities if identities.count(key) > 1})
    if duplicates:
        raise ValueError(f"Duplicate station/date/source/quantity rows: {duplicates[:5]}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with TABLE.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in COLUMNS})
    review = {
        "table": TABLE.relative_to(ROOT).as_posix(), "sha256": file_hash(TABLE), "rows": len(rows),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "stations": summarise(rows),
        "ffc": {"documents": len([d for d in index["ffc"] if "path" in d]),
                "unavailable_dates": [d["date"] for d in index["ffc"] if "path" not in d],
                "pages": ffc_review,
                "skipped_lines": sum(len(item["skipped"]) for item in ffc_review)},
        "wapda": wapda_review,
        "cross_checks": cross_checks(rows),
        "rules": [
            "Measured or reported values only; nothing interpolated, filled in or adjusted.",
            "FFC: today's inflow (column 7) and outflow (column 8) of Annexure-I, read at 06:00 PKT. 'NIL' is kept as 0 with reported_as = NIL.",
            "FFC lines whose numbers do not map to distinct, ordered printed columns are skipped and listed.",
            "WAPDA: 2022 rows of the GHRAPH sheet, thousand cusecs x 1000. Zero values are left out as possible missing-data codes.",
            "FFC 06:00 readings and WAPDA daily values measure different things and are not merged or reconciled.",
            "Not model forcing: once-a-day values cannot resolve within-day flood timing.",
        ],
    }
    write_json(REVIEW, review)
    return {"rows": len(rows), "stations": len(review["stations"]), "skipped_lines": review["ffc"]["skipped_lines"],
            "ffc_unavailable": review["ffc"]["unavailable_dates"]}


def summarise(rows):
    stations = {}
    for row in rows:
        item = stations.setdefault(row["station_id"], {"river": row["river"], "series": {}})
        key = f"{'FFC' if row['source'].startswith('FFC') else 'WAPDA'} {row['quantity']}"
        series = item["series"].setdefault(key, {"days": 0, "first": row["date"], "last": row["date"], "max_cusecs": 0, "max_date": ""})
        series["days"] += 1
        series["first"], series["last"] = min(series["first"], row["date"]), max(series["last"], row["date"])
        if row["discharge_cusecs"] > series["max_cusecs"]:
            series["max_cusecs"], series["max_date"] = row["discharge_cusecs"], row["date"]
    for item in stations.values():
        for series in item["series"].values():
            span = (date.fromisoformat(series["last"]) - date.fromisoformat(series["first"])).days + 1
            series["missing_days_in_span"] = span - series["days"]
    return stations


def cross_checks(rows):
    """Compare against the project's reviewed transcriptions and the other source; report, never adjust."""
    checks = {}
    reviewed = NOWSHERA_BASE / "study" / "reviewed-daily-observations.csv"
    if reviewed.is_file():
        with reviewed.open(encoding="utf-8-sig", newline="") as stream:
            earlier = {(r["station_id"], r["time"][:10]): float(r["discharge_cusecs"]) for r in csv.DictReader(stream)}
        ours = {(r["station_id"], r["time_utc"][:10]): r["discharge_cusecs"] for r in rows
                if r["source"].startswith("FFC") and r["quantity"] == "outflow" and r["time_utc"]}
        common = sorted(set(earlier) & set(ours))
        differ = [{"station_id": s, "date": d, "earlier": earlier[(s, d)], "now": ours[(s, d)]}
                  for s, d in common if abs(earlier[(s, d)] - ours[(s, d)]) > .5]
        checks["earlier_reviewed_transcription"] = {"compared": len(common), "differences": differ}
    ffc = {(r["station_id"], r["date"], r["quantity"]): r["discharge_cusecs"] for r in rows if r["source"].startswith("FFC")}
    wapda = {(r["station_id"], r["date"], r["quantity"]): r["discharge_cusecs"] for r in rows if r["source"].startswith("WAPDA")}
    pairs = {}
    for key in sorted(set(ffc) & set(wapda)):
        a, b = ffc[key], wapda[key]
        item = pairs.setdefault(f"{key[0]} {key[2]}", {"days": 0, "median_ratio_ffc_to_wapda": None, "ratios": []})
        item["days"] += 1
        if b:
            item["ratios"].append(a / b)
    for item in pairs.values():
        ratios = sorted(item.pop("ratios"))
        if ratios:
            item["median_ratio_ffc_to_wapda"] = round(ratios[len(ratios) // 2], 3)
            item["ratio_range"] = [round(ratios[0], 3), round(ratios[-1], 3)]
    checks["ffc_0600_vs_wapda_daily"] = pairs
    return checks


def observed(station_id=None):
    """Rows for one station (or a summary of all), for the API."""
    review = read_json(REVIEW)
    if not review or not TABLE.is_file() or file_hash(TABLE) != review["sha256"]:
        return None
    if station_id is None:
        return {"stations": review["stations"], "rules": review["rules"], "sha256": review["sha256"]}
    with TABLE.open(encoding="utf-8", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row["station_id"] == station_id]
    return {"station_id": station_id, "rows": rows, "rules": review["rules"], "sha256": review["sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("acquire", help="Download the WAPDA workbook and the 2022 FFC daily reports")
    sub.add_parser("build", help="Extract and review the observed daily table")
    args = parser.parse_args()
    print(json.dumps(acquire() if args.command == "acquire" else build(), indent=2))


if __name__ == "__main__":
    main()
