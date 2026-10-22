"""Synthetic isolated input/integrity fixtures; never registered as study data."""
from datetime import timedelta
import json
from pathlib import Path

import numpy as np
import pytest

from server import screening
from server.models import Scenario
from server.store import file_hash, scenario_hash, write_json


def fixture_scenario():
    value = json.loads((Path(__file__).parents[1] / "examples" / "nowshera-2022.json").read_text())
    value["hydraulics"].update(engine="LISFLOOD-FP", equations="local inertial")
    value["time"]["end"] = "2022-08-20T01:00:00Z"
    return Scenario.model_validate(value)


def test_modeled_boundary_preserves_labels_and_refuses_changed_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(screening, "STUDY", tmp_path)
    source = tmp_path / "hms-nowshera-hourly-modeled.csv"
    rows = [{"time": (screening.START + timedelta(hours=i)).isoformat(), "station_id": "nowshera", "discharge_m3s": 100 + i,
             "source": "synthetic fixture, not field data", "value_type": "modeled"} for i in range(385)]
    screening.write_csv(source, rows)
    upstream = tmp_path / "upstream-hourly-interpolated.csv"
    screening.write_csv(upstream, [{**rows[0], "station_id": "warsak", "value_type": "observed"}])
    write_json(tmp_path / "routing-calibration.json", {"output_csv_sha256": file_hash(source), "boundary_csv_sha256": file_hash(upstream)})
    target = tmp_path / "combined.csv"
    times, flows, _ = screening.modeled_inflows(target)
    combined = screening._rows(target)
    assert times[-1] == screening.END
    assert len(flows) == 385
    assert combined[0]["value_type"] == "observed"
    assert all(row["value_type"] == "modeled" and row["station_id"] == "nowshera-hms" for row in combined[1:])
    source.write_text(source.read_text() + "\n")
    with pytest.raises(ValueError, match="output hash"):
        screening.modeled_inflows(target)


def test_boundary_with_internal_hourly_gap_is_rejected_even_with_new_file_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(screening, "STUDY", tmp_path)
    source = tmp_path / "hms-nowshera-hourly-modeled.csv"
    screening.write_csv(source, [{"time": (screening.START + timedelta(hours=i)).isoformat(), "discharge_m3s": 100, "value_type": "modeled"} for i in range(385) if i != 12])
    write_json(tmp_path / "routing-calibration.json", {"output_csv_sha256": file_hash(source)})
    with pytest.raises(ValueError, match="without gaps"):
        screening.modeled_inflows(tmp_path / "combined.csv")


@pytest.mark.parametrize("times, error", [([20, 3590], "complete scenario window"), ([21, 3600], "nominal timestamp")])
def test_export_refuses_truncated_engine_time_or_invented_nominal_timing(tmp_path, times, error):
    s = fixture_scenario()
    terrain = tmp_path / "computational-terrain.tif"
    terrain.write_bytes(b"isolated placeholder; validation must stop before raster export")
    write_json(tmp_path / "screening.json", {"format": screening.FORMAT, "scenario_sha256": scenario_hash(s),
        "computational_terrain_sha256": file_hash(terrain), "massint_seconds": 3600})
    output = tmp_path / "output"
    output.mkdir()
    mass = np.zeros((2, 12))
    mass[:, 0] = times
    np.savetxt(output / "nowshera.mass", mass, header="isolated mass fixture", comments="")
    np.savetxt(output / "nowshera.discharge", np.array([[times[0], 1], [times[1], 1]]), header="a\nb\nc", comments="")
    with pytest.raises(ValueError, match=error):
        screening.finish_and_publish(s, tmp_path)


def test_cached_output_refuses_a_modified_playback_overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(screening, "ROOT", tmp_path)
    s = fixture_scenario()
    folder = tmp_path / "results" / f"{s.id}-{scenario_hash(s)[:12]}"
    folder.mkdir(parents=True)
    raster = folder / "depth.tif"
    overlay = folder / "depth.png"
    raster.write_bytes(b"isolated original")
    overlay.write_bytes(b"isolated overlay")
    result = {"scenario_sha256": scenario_hash(s), "frames": [{"fields": {"depth": {
        "raster_url": "/outputs/fixture/depth.tif", "url": "/outputs/fixture/depth.png",
        "sha256": file_hash(raster), "overlay_sha256": file_hash(overlay)}}}]}
    write_json(folder / "manifest.json", result)
    assert screening.cached_result(s) == result
    overlay.write_bytes(b"changed display")
    with pytest.raises(ValueError, match="output changed"):
        screening.cached_result(s)


def test_complete_gauge_uses_one_cell_sections_covering_every_row(tmp_path):
    path = tmp_path / "section.gauge"
    screening.gauge_sections(path, 774900, 3774600, 73, 200)
    lines = path.read_text().splitlines()
    assert int(lines[0]) == 73
    sections = [line.split() for line in lines[1:]]
    assert len(sections) == 73
    assert len({float(section[1]) for section in sections}) == 73
    assert all(section[2] == "E" and float(section[3]) == 200 for section in sections)
    assert float(sections[0][1]) == 3774500
    assert float(sections[-1][1]) == 3760100
