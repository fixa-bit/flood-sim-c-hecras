"""Timed-source provenance, network exclusions, and safe local-flow delivery."""

import csv
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from server import inflows, study_hms
from server.study import END, START, interpolated_boundary, write_csv


def test_untimed_pdma_laterals_remain_reference_only():
    text = """<span id="ContentPlaceHolder1_lblDate">Date: 28/08/2022</span>
    <table id="ContentPlaceHolder1_dgRivers"><tr><td>Jindi River</td><td>Charsadda</td><td>7,299</td><td>Normal</td></tr></table>"""
    result = inflows.pdma_rows(text, "official report", "a" * 64)
    assert result[0]["report_date"] == "2022-08-28"
    assert result[0]["time"] == ""  # A report date must not become midnight/06:00.
    assert result[0]["discharge_cusecs"] == 7299
    assert "excluded" in result[0]["observation_time_status"]
    with pytest.raises(ValueError, match="dated river table"):
        inflows.pdma_rows(text.replace("lblDate", "unknown"), "source", "a" * 64)


def test_half_hour_observation_is_not_shifted_or_reported_as_hourly_measurement():
    baseline = [
        {
            "station_id": "warsak",
            "time": (START + timedelta(days=i)).isoformat(),
            "discharge_m3s": q,
            "source": "daily",
        }
        for i, q in enumerate([100, 200])
    ]
    extra = {
        "station_id": "warsak",
        "time": (START + timedelta(hours=6, minutes=30))
        .astimezone(timezone(timedelta(hours=5)))
        .isoformat(),
        "discharge_m3s": 300,
        "source": "timed report",
    }
    merged = inflows.merge_observations(baseline, [extra])
    assert merged[1]["time"] == (START + timedelta(hours=6, minutes=30)).isoformat()
    output = interpolated_boundary(merged, "warsak", START, START + timedelta(days=1))
    assert output[6]["value_type"] == output[7]["value_type"] == "modeled"
    assert output[6]["discharge_m3s"] < 300 and output[7]["discharge_m3s"] < 300
    assert output[6]["right_observation"] == merged[1]["time"]


@pytest.mark.parametrize("station", ["nowshera", "munda", "chakdara", "khwazakhela"])
def test_nested_and_validation_gauges_cannot_be_added_as_upstream_sources(station):
    with pytest.raises(ValueError, match="nested or evaluation"):
        inflows.merge_observations(
            [],
            [{"station_id": station, "time": START.isoformat(), "discharge_m3s": 100}],
        )


def test_conflicting_timed_observations_need_review():
    row = {
        "station_id": "warsak",
        "time": START.isoformat(),
        "discharge_m3s": 100,
        "source": "first",
    }
    with pytest.raises(ValueError, match="Conflicting"):
        inflows.merge_observations(
            [row], [{**row, "discharge_m3s": 101, "source": "second"}]
        )


def test_upstream_import_requires_real_times_units_and_source_review(tmp_path):
    row = {
        "time": START.isoformat(),
        "station_id": "charsadda-road",
        "discharge": 10000,
        "units": "cusecs",
        "value_type": "observed",
        "source": "official data export",
        "source_sha256": "a" * 64,
        "page_or_record": "record 1",
        "review": "Station and timestamp checked",
    }
    path = tmp_path / "observations.csv"
    write_csv(path, [row])
    result = inflows.imported_observations(path)
    assert result[0]["discharge_m3s"] == 10000 * inflows.CUSEC_TO_M3S
    for change in [
        {"time": "2022-08-20"},
        {"review": ""},
        {"value_type": "modeled"},
        {"source_sha256": ""},
        {"units": "unknown"},
    ]:
        write_csv(path, [{**row, **change}])
        with pytest.raises(ValueError):
            inflows.imported_observations(path)


def test_lateral_import_requires_delivery_and_catchment_review(tmp_path):
    path, review_path = tmp_path / "laterals.csv", tmp_path / "review.json"
    records = [
        {
            "time": (START + timedelta(hours=i)).isoformat(),
            "station_id": "nowshera-local-laterals",
            "units": "m3/s",
            "discharge": 100 + i,
            "value_type": "modeled",
            "source": "reviewed local HEC-HMS output",
            "source_sha256": "b" * 64,
        }
        for i in range(385)
    ]
    write_csv(path, records)
    review = {
        "delivery_location": "HEC-HMS Nowshera junction",
        "includes_upstream_gauged_catchments": False,
        "uses_nowshera_observations": False,
        "contributing_catchments": ["reviewed independent local catchment"],
        "routing_method": "Reviewed local HEC-HMS rainfall-runoff and reach routing",
        "review": "Topology checked",
    }
    review_path.write_text(json.dumps(review))
    result, audit = inflows.lateral_hydrograph(path, review_path)
    assert len(result) == 385 and result[-1]["time"] == END.isoformat()
    assert result[0]["discharge_m3s"] == 100 and result[-1]["discharge_m3s"] == 484
    assert all(row["value_type"] == "modeled" for row in result)
    assert audit["measured_or_rainfall_runoff_series_available"] is True
    for key in ["includes_upstream_gauged_catchments", "uses_nowshera_observations"]:
        review_path.write_text(json.dumps({**review, key: True}))
        with pytest.raises(ValueError, match="exclude upstream gauged catchments"):
            inflows.lateral_hydrograph(path, review_path)
    review_path.write_text(json.dumps(review))
    write_csv(path, [records[0], records[-1]])
    with pytest.raises(ValueError, match="six hours"):
        inflows.lateral_hydrograph(path, review_path)


def test_native_hms_receives_lateral_series_as_replacement_in_private_project(
    tmp_path, monkeypatch
):
    boundary = tmp_path / "boundaries.csv"
    write_csv(
        boundary,
        [
            {
                "time": (START + timedelta(hours=i)).isoformat(),
                "station_id": station,
                "discharge_m3s": 100,
            }
            for station in ["warsak", "charsadda-road"]
            for i in range(385)
        ],
    )
    project = tmp_path / "candidate"
    baseline = tmp_path / "original"
    baseline.mkdir()
    (baseline / "untouched.txt").write_text("bound model")
    monkeypatch.setattr(study_hms, "PROJECT", baseline)
    candidates = [("TimedUpstream", 12, 6)]
    study_hms.project_files(candidates, project=project, data_label=inflows.LABEL)
    local = np.linspace(10, 100, 385)

    def fake_engine(script, log):
        values = json.loads((project / "test-inputs.json").read_text())
        assert values["UnmeasuredLocal"] == local.tolist()  # No +732.85 residual.
        assert (
            inflows.LABEL in script.read_text()
            and inflows.LABEL in (project / "upstream.gage").read_text()
        )
        epoch = datetime(1899, 12, 31, tzinfo=timezone.utc)
        origin = int((START - epoch).total_seconds() / 60)
        write_csv(
            project / "test-outputs.csv",
            [
                {
                    "model": "TimedUpstream",
                    "hec_minutes": origin + i * 60,
                    "discharge_m3s": 200 + q,
                }
                for i, q in enumerate(local)
            ],
        )

    monkeypatch.setattr(study_hms, "run_script", fake_engine)
    result = study_hms.compute_batch(
        candidates,
        local,
        "test",
        project=project,
        boundary_csv=boundary,
        data_label=inflows.LABEL,
    )
    assert result["TimedUpstream"][START.isoformat()] == 210
    assert result["TimedUpstream"][END.isoformat()] == 300
    assert list(baseline.iterdir()) == [baseline / "untouched.txt"]
    with pytest.raises(ValueError, match="every upstream timestep"):
        study_hms.compute_batch(
            candidates, local[:-1], "invalid", project=project, boundary_csv=boundary
        )


def test_reviewed_ffc_documents_cannot_change_silently(tmp_path, monkeypatch):
    monkeypatch.setattr(inflows, "BASE", tmp_path)
    folder = tmp_path / "references" / "daily-ffc"
    folder.mkdir(parents=True)
    (folder / "FFC-2022-08-26.pdf").write_bytes(b"changed source")
    with pytest.raises(ValueError, match="document changed"):
        inflows.reviewed_ffc()
