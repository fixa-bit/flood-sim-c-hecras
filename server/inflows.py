"""Acquire and evaluate timed upstream evidence without rewriting bound models.

python -m server.inflows all
The candidate remains separate until complete upstream/lateral evidence exists.
"""

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import unescape
import math
from pathlib import Path
import re
from uuid import uuid4

import httpx
from .acquire import BASE, download
from .metrics import gauge_metrics
from .store import file_hash, read_json, write_json
from .study import END, REVIEWED_CUSECS, START, STUDY, interpolated_boundary, write_csv
from .study_hms import compute_batch, installation, project_files

FOLDER = STUDY / "inflow-candidates" / "timed-ffc-v1"
EVIDENCE = Path(__file__).with_name("data") / "ffc-subdaily-2022.json"
CUSEC_TO_M3S = 0.028316846592
BOUNDARY_STATIONS = {"warsak", "charsadda-road"}
PDMA = BASE / "references" / "pdma-dwr-2022"
LABEL = "FFC-TIMED-SNAPSHOTS-CANDIDATE"


def rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def pdma_rows(text, source, sha256):
    """Read the named river table, preserving the absence of a timestamp."""
    day = re.search(r"lblDate[^>]*>Date:\s*(\d{2}/\d{2}/\d{4})", text)
    table = re.search(
        r'<table\b[^>]*id="ContentPlaceHolder1_dgRivers"[^>]*>(.*?)</table>', text, re.S
    )
    if not day or not table:
        raise ValueError("PDMA report is missing its dated river table.")
    report_date = datetime.strptime(day[1], "%d/%m/%Y").date().isoformat()
    result = []
    for line in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table[1], re.S):
        cells = [
            re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", cell))).strip()
            for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", line, re.S)
        ]
        if len(cells) != 4 or not re.fullmatch(r"[\d,]+", cells[2]):
            continue
        result.append(
            {
                "report_date": report_date,
                "time": "",
                "river": cells[0],
                "location": cells[1],
                "discharge_cusecs": int(cells[2].replace(",", "")),
                "status": cells[3],
                "source": source,
                "source_sha256": sha256,
                "observation_time_status": "not published in river table; excluded from model inputs",
            }
        )
    if not result:
        raise ValueError("PDMA river table contains no discharge rows.")
    return result


def acquire_pdma():
    PDMA.mkdir(parents=True, exist_ok=True)

    def fetch(identifier):
        source = f"https://rms.pdma.gov.pk/ViewDWR.aspx?DWRID={identifier}"
        path = PDMA / f"DWR-{identifier}.html"
        try:
            if not path.exists():
                response = httpx.get(source, timeout=30, follow_redirects=True)
                response.raise_for_status()
                path.write_bytes(response.content)
            sha256 = file_hash(path)
            records = pdma_rows(
                path.read_text(encoding="utf-8", errors="replace"), source, sha256
            )
            expected = (START + timedelta(days=identifier - 1102)).date().isoformat()
            if records[0]["report_date"] != expected:
                raise ValueError(
                    "Report date differs from the requested 2022 study date."
                )
            return {
                "source": source,
                "path": str(path),
                "sha256": sha256,
                "report_date": expected,
            }, records
        except (httpx.HTTPError, OSError, ValueError) as exc:
            return {"source": source, "error": str(exc)}, []

    documents, observations = [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for document, records in pool.map(fetch, range(1102, 1119)):
            documents.append(document)
            observations.extend(records)
    if observations:
        write_csv(PDMA / "untimed-reference-observations.csv", observations)
    audit = {
        "documents": documents,
        "reference_observations": len(observations),
        "accepted_boundary_observations": 0,
        "reason": "The report date is not an observation timestamp. No time is guessed.",
        "network_warning": "Adezai, Naguman and Shah Alam are Kabul distributaries; do not add their flow to Warsak again. Nested Swat stations must not be summed.",
    }
    write_json(PDMA / "source-audit.json", audit)
    return audit


def reviewed_ffc():
    evidence = read_json(EVIDENCE)
    output = []
    for record in evidence["observations"]:
        local = datetime.fromisoformat(record["reported_time_local"])
        path = BASE / "references" / "daily-ffc" / f"FFC-{local.date().isoformat()}.pdf"
        if not path.exists():
            download(record["source"], path, max_bytes=20_000_000)
        if file_hash(path) != record["source_sha256"]:
            raise ValueError(f"Reviewed FFC document changed: {path.name}.")
        output.append(
            {
                "time": local.astimezone(timezone.utc).isoformat(),
                "station_id": record["station_id"],
                "discharge_m3s": record["discharge_cusecs"] * CUSEC_TO_M3S,
                "discharge_cusecs": record["discharge_cusecs"],
                "reported_time_local": local.isoformat(),
                "source": record["source"],
                "source_sha256": record["source_sha256"],
                "page": record["page"],
                "quality": evidence["review"],
                "value_type": "observed",
            }
        )
    return output


def imported_observations(path):
    """Only reviewed, timed observations at the two independent boundaries."""
    result = []
    for record in rows(path):
        if record.get("station_id") not in BOUNDARY_STATIONS:
            raise ValueError(
                "Only Warsak and charsadda-road may enter this upstream series; nested or evaluation gauges are refused."
            )
        time = datetime.fromisoformat(record["time"].replace("Z", "+00:00"))
        if time.tzinfo is None or not START <= time <= END:
            raise ValueError(
                "Imported observations require a timezone and a timestamp inside the study window."
            )
        q = float(record["discharge"])
        if record["units"] == "cusecs":
            q *= CUSEC_TO_M3S
        elif record["units"] != "m3/s":
            raise ValueError("Discharge units must be cusecs or m3/s.")
        if not math.isfinite(q) or q < 0:
            raise ValueError("Observed discharge must be finite and nonnegative.")
        if record.get("value_type") != "observed" or not all(
            record.get(k, "").strip() for k in ["source", "review", "page_or_record"]
        ):
            raise ValueError(
                "Imports require observed values, a source, page/record and transcription review."
            )
        if not re.fullmatch(r"[a-fA-F0-9]{64}", record.get("source_sha256", "")):
            raise ValueError("A source-document SHA-256 is required.")
        result.append(
            {
                **record,
                "time": time.astimezone(timezone.utc).isoformat(),
                "discharge_m3s": q,
            }
        )
    return result


def merge_observations(baseline, additional):
    combined = {}
    for row in [*baseline, *additional]:
        if row["station_id"] not in BOUNDARY_STATIONS:
            raise ValueError(
                "A nested or evaluation gauge cannot enter the upstream inflow series."
            )
        time = datetime.fromisoformat(row["time"])
        if time.tzinfo is None:
            raise ValueError("Observation timestamps must include a timezone.")
        key = row["station_id"], time.astimezone(timezone.utc).isoformat()
        if key in combined and not math.isclose(
            float(combined[key]["discharge_m3s"]),
            float(row["discharge_m3s"]),
            rel_tol=0,
            abs_tol=1e-8,
        ):
            raise ValueError(
                f"Conflicting observations at {key}; resolve the source conflict before routing."
            )
        combined[key] = {**row, "time": key[1]}
    return sorted(combined.values(), key=lambda row: (row["station_id"], row["time"]))


def lateral_hydrograph(path, review_path):
    """Accept delivered local flow, with catchment and routing review explicit.

    Raw tributary-gauge flows need routing to the junction first. Catchments
    upstream of Warsak/Charsadda must not contribute runoff a second time.
    """
    review = read_json(Path(review_path))
    if (
        not review
        or not str(review.get("review", "")).strip()
        or not str(review.get("routing_method", "")).strip()
    ):
        raise ValueError("A documented lateral catchment/routing review is required.")
    if (
        review.get("delivery_location") != "HEC-HMS Nowshera junction"
        or review.get("includes_upstream_gauged_catchments") is not False
        or review.get("uses_nowshera_observations") is not False
    ):
        raise ValueError(
            "Laterals must be delivered at the model junction, exclude upstream gauged catchments, and not use Nowshera observations."
        )
    catchments = review.get("contributing_catchments")
    complete = review.get("all_intervening_catchments_accounted_for", False)
    if not isinstance(complete, bool):
        raise ValueError("The lateral catchment completeness flag must be a boolean.")
    if (
        not isinstance(catchments, list)
        or not catchments
        or any(not isinstance(c, str) or not c.strip() for c in catchments)
        or len(set(catchments)) != len(catchments)
    ):
        raise ValueError("List the unique independent contributing catchments.")
    observations = []
    for record in rows(path):
        if (
            record.get("station_id") != "nowshera-local-laterals"
            or record.get("units") != "m3/s"
            or record.get("value_type") != "modeled"
        ):
            raise ValueError(
                "Expected modeled nowshera-local-laterals delivered discharges in m3/s."
            )
        if not record.get("source", "").strip() or not re.fullmatch(
            r"[a-fA-F0-9]{64}", record.get("source_sha256", "")
        ):
            raise ValueError("Lateral values require source provenance and SHA-256.")
        observations.append({**record, "discharge_m3s": float(record["discharge"])})
    times = [
        datetime.fromisoformat(r["time"].replace("Z", "+00:00")) for r in observations
    ]
    if not times or any(t.tzinfo is None for t in times):
        raise ValueError("Lateral hydrographs require timezone-aware samples.")
    times.sort()
    if any(b - a > timedelta(hours=6) for a, b in zip(times, times[1:])):
        raise ValueError(
            "Lateral hydrographs require timezone-aware samples with no gaps over six hours."
        )
    hourly = interpolated_boundary(observations, "nowshera-local-laterals")
    for record in hourly:
        record["value_type"] = "modeled"
        record["method"] = (
            "reviewed local contribution delivered at HEC-HMS junction; replaces fitted constant"
        )
    return hourly, {
        "state": "reviewed time-varying lateral hydrograph replaces fitted constant",
        "measured_or_rainfall_runoff_series_available": True,
        "source_csv_sha256": file_hash(Path(path)),
        "review_sha256": file_hash(Path(review_path)),
        "all_intervening_catchments_accounted_for": complete,
        "catchment_and_routing_review": review,
    }


def prepare(observations=None, laterals=None, lateral_review=None):
    baseline_report = read_json(STUDY / "routing-calibration.json")
    boundary = STUDY / "upstream-hourly-interpolated.csv"
    if (
        not baseline_report
        or file_hash(boundary) != baseline_report["boundary_csv_sha256"]
    ):
        raise ValueError("The baseline HEC-HMS boundary hash must match its report.")
    # Recheck the daily review rather than accepting edits to an intermediate CSV.
    daily = [
        row
        for row in rows(STUDY / "reviewed-daily-observations.csv")
        if row["station_id"] in BOUNDARY_STATIONS
    ]
    expected = {
        (station, (START + timedelta(days=i)).isoformat()): q
        for station in BOUNDARY_STATIONS
        for i, q in enumerate(REVIEWED_CUSECS[station])
    }
    if len(daily) != len(expected) or {
        (r["station_id"], r["time"]): float(r["discharge_m3s"]) for r in daily
    } != {key: q * CUSEC_TO_M3S for key, q in expected.items()}:
        raise ValueError(
            "The reviewed daily observations differ from their verified transcription."
        )
    additional = reviewed_ffc()
    if observations:
        additional += imported_observations(observations)
    combined = merge_observations(daily, additional)
    # A source event at 07:30 UTC stays at 07:30 in observations.csv. Hourly
    # ordinates around it remain interpolated; they are never labeled measured.
    hourly = [
        row
        for station in sorted(BOUNDARY_STATIONS)
        for row in interpolated_boundary(combined, station)
    ]
    for row in hourly:
        row["method"] = (
            "reviewed timed gauge snapshot"
            if row["value_type"] == "observed"
            else "linear interpolation between timed snapshots; unresolved peaks remain unknown"
        )
    lateral = {
        "state": "baseline fitted constant retained only for controlled comparison",
        "measured_or_rainfall_runoff_series_available": False,
    }
    if bool(laterals) != bool(lateral_review):
        raise ValueError(
            "Supply both the lateral hydrograph and its catchment/routing review."
        )
    if laterals:
        lateral_rows, lateral = lateral_hydrograph(laterals, lateral_review)
    FOLDER.mkdir(parents=True, exist_ok=True)
    columns = [
        "time",
        "station_id",
        "discharge_m3s",
        "value_type",
        "source",
        "source_sha256",
        "page",
        "quality",
    ]
    write_csv(
        FOLDER / "observations.csv",
        [
            {
                k: r.get(
                    k,
                    r.get(
                        {"page": "page_or_record", "quality": "review"}.get(k, k), ""
                    ),
                )
                for k in columns
            }
            for r in combined
        ],
        columns,
    )
    write_csv(FOLDER / "upstream-hourly-interpolated.csv", hourly)
    coverage = {}
    for station in sorted(BOUNDARY_STATIONS):
        times = [
            datetime.fromisoformat(r["time"])
            for r in combined
            if r["station_id"] == station
        ]
        gaps = [(b - a).total_seconds() / 3600 for a, b in zip(times, times[1:])]
        coverage[station] = {
            "observations": len(times),
            "maximum_gap_hours": max(gaps),
            "complete_at_6h_or_better": max(gaps) <= 6,
        }
    if laterals:
        lateral_path = FOLDER / "lateral-hourly.csv"
        write_csv(lateral_path, lateral_rows)
        lateral["hourly_csv_sha256"] = file_hash(lateral_path)
    report = {
        "state": "inflow candidate; review coverage and lateral evidence before preparing hydraulic cases",
        "promoted_to_hydraulic_models": False,
        "additional_reviewed_observations": len(combined) - len(daily),
        "coverage": coverage,
        "complete_subdaily_upstream": all(
            r["complete_at_6h_or_better"] for r in coverage.values()
        ),
        "lateral_inflows": lateral,
        "baseline_boundary_sha256": file_hash(boundary),
        "candidate_boundary_sha256": file_hash(
            FOLDER / "upstream-hourly-interpolated.csv"
        ),
        "baseline_report_sha256": file_hash(STUDY / "routing-calibration.json"),
        "heldout_observations_sha256": file_hash(
            STUDY / "nowshera-heldout-observations.csv"
        ),
        "observations_sha256": file_hash(FOLDER / "observations.csv"),
        "reviewed_evidence_sha256": file_hash(EVIDENCE),
        "source_exclusions": read_json(EVIDENCE)["exclusions"],
        "required_data": [
            "Timestamped Warsak and Swat Khiali/Charsadda Road observations, ideally hourly and at most 6-hourly, bracketing 20 August 01:00 UTC through 5 September 01:00 UTC 2022.",
            "Timed independent lateral hydrographs (e.g. reviewed Bara/Budni/Jindi contributions) or a reviewed local rainfall-runoff HEC-HMS model. Verify gauge topology, travel times and intervening drainage before summing.",
            "PDMA report dates alone cannot establish the observation times needed for model forcing.",
        ],
        "evaluation_policy": "Reuse baseline routing coefficients without refitting; retain the baseline lateral constant unless a reviewed time-varying lateral hydrograph replaces it. Withheld Nowshera observations are for diagnostics only; this is model development, not new independent validation.",
    }
    write_json(FOLDER / "boundary-review.json", report)
    write_json(STUDY / "inflow-improvement.json", {**report, "folder": str(FOLDER)})
    return report


def evaluate():
    report = read_json(FOLDER / "boundary-review.json")
    baseline = read_json(STUDY / "routing-calibration.json")
    source = STUDY / "hms-nowshera-hourly-modeled.csv"
    candidate_path = FOLDER / "upstream-hourly-interpolated.csv"
    if (
        not report
        or not baseline
        or file_hash(candidate_path) != report["candidate_boundary_sha256"]
        or file_hash(source) != baseline["output_csv_sha256"]
    ):
        raise ValueError(
            "Input hash changed; prepare/review the candidate before evaluating."
        )
    if (
        file_hash(STUDY / "upstream-hourly-interpolated.csv")
        != report["baseline_boundary_sha256"]
    ):
        raise ValueError("Baseline inputs changed after candidate preparation.")
    if (
        file_hash(STUDY / "routing-calibration.json")
        != report["baseline_report_sha256"]
        or file_hash(STUDY / "nowshera-heldout-observations.csv")
        != report["heldout_observations_sha256"]
    ):
        raise ValueError(
            "Baseline parameters or evaluation observations changed after candidate preparation."
        )
    if file_hash(installation() / "hms.jar") != baseline["engine_jar_sha256"]:
        raise ValueError("HEC-HMS engine differs from the baseline.")
    parameters = baseline["parameters"]
    local = parameters["estimated_local_constant_m3s"]
    if report["lateral_inflows"]["measured_or_rainfall_runoff_series_available"]:
        lateral_path = FOLDER / "lateral-hourly.csv"
        if file_hash(lateral_path) != report["lateral_inflows"]["hourly_csv_sha256"]:
            raise ValueError(
                "The reviewed lateral hydrograph changed after preparation."
            )
        local = [float(r["discharge_m3s"]) for r in rows(lateral_path)]
    candidate = [
        ("TimedUpstream", parameters["warsak_k_hours"], parameters["swat_k_hours"])
    ]
    # A fresh native project prevents old DSS results from satisfying the
    # completeness check if a later compute fails before overwriting them.
    project = FOLDER / "hec-hms" / f"run-{uuid4().hex[:10]}"
    project_files(candidate, project=project, data_label=LABEL)
    output = compute_batch(
        candidate,
        local,
        "timed",
        project=project,
        boundary_csv=candidate_path,
        data_label=LABEL,
    )["TimedUpstream"]
    native_log = (project / "TimedUpstream.log").read_text(
        encoding="utf-8", errors="replace"
    )
    if (
        "Finished computing simulation run" not in native_log
        or "ERROR " in native_log
        or "FATAL " in native_log
    ):
        raise ValueError(
            "The native HEC-HMS run did not finish successfully; candidate output is not accepted."
        )
    reference = {r["time"]: float(r["discharge_m3s"]) for r in rows(source)}
    observed = rows(STUDY / "nowshera-heldout-observations.csv")
    scores = {}
    for split in ["calibration", "validation"]:
        subset = [r for r in observed if r["split"] == split]
        target = [float(r["observed_m3s"]) for r in subset]
        scores[split] = {
            "samples": len(subset),
            "baseline": gauge_metrics(target, [reference[r["time"]] for r in subset]),
            "candidate": gauge_metrics(target, [output[r["time"]] for r in subset]),
        }
    modeled = [
        {
            "time": t,
            "station_id": "nowshera",
            "discharge_m3s": q,
            "value_type": "modeled",
            "source": "HEC-HMS 4.14 TimedUpstream; "
            + report["lateral_inflows"]["state"],
        }
        for t, q in sorted(output.items())
    ]
    output_path = FOLDER / "hms-nowshera-hourly-modeled.csv"
    write_csv(output_path, modeled)
    blockers = []
    if not report["complete_subdaily_upstream"]:
        blockers.append("Complete subdaily Swat/Warsak series unavailable.")
    if not report["lateral_inflows"].get(
        "all_intervening_catchments_accounted_for", False
    ):
        blockers.append(
            "Complete reviewed time-varying lateral contributions unavailable."
        )
    result = {
        **report,
        "engine": "HEC-HMS 4.14",
        "routing_parameters_refitted": False,
        "validation_data_used_for_fitting": False,
        "fitted_lateral_constant_used": isinstance(local, (float, int)),
        "parameters": parameters,
        "scores": scores,
        "output_csv_sha256": file_hash(output_path),
        "engine_jar_sha256": baseline["engine_jar_sha256"],
        "native_project": str(project),
        "native_artifacts": [
            {"path": name, "sha256": file_hash(project / name)}
            for name in [
                "upstream.hms",
                "upstream.run",
                "upstream.gage",
                "Event.control",
                "GaugeOnly.met",
                "TimedUpstream.basin",
                "timed-inputs.dss",
                "TimedUpstream.dss",
                "TimedUpstream.log",
                "timed-compute.py",
            ]
        ],
        "heldout_observations_sha256": file_hash(
            STUDY / "nowshera-heldout-observations.csv"
        ),
        "maximum_hourly_change_m3s": max(abs(output[t] - reference[t]) for t in output),
        "baseline_peak_m3s": max(reference.values()),
        "candidate_peak_m3s": max(output.values()),
        "promotion_blockers": blockers,
    }
    write_json(FOLDER / "evaluation.json", result)
    write_json(STUDY / "inflow-improvement.json", {**result, "folder": str(FOLDER)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=["acquire", "prepare", "evaluate", "all"])
    parser.add_argument(
        "--observations",
        type=Path,
        help="Additional reviewed timed upstream observations; see docs/INFLOW_IMPROVEMENT.md.",
    )
    parser.add_argument(
        "--laterals",
        type=Path,
        help="Reviewed time-varying local flow delivered at the HMS junction, replacing the fitted constant.",
    )
    parser.add_argument(
        "--lateral-review",
        type=Path,
        help="Catchment overlap, source and routing review JSON for --laterals.",
    )
    args = parser.parse_args()
    if args.task in {"acquire", "all"}:
        audit = acquire_pdma()
        print(
            f"Preserved {audit['reference_observations']} untimed PDMA reference observations.",
            flush=True,
        )
    if args.task in {"prepare", "all"}:
        report = prepare(args.observations, args.laterals, args.lateral_review)
        print(
            f"Prepared candidate with {report['additional_reviewed_observations']} additional timed observations: {FOLDER}",
            flush=True,
        )
    if args.task in {"evaluate", "all"}:
        report = evaluate()
        score = report["scores"]["validation"]
        print(
            f"Withheld KGE: baseline {score['baseline']['kge']:.6f}; candidate {score['candidate']['kge']:.6f}. Candidate remains unpromoted.",
            flush=True,
        )


if __name__ == "__main__":
    main()
