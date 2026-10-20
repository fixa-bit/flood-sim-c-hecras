"""Verify acquisition grid alignment and unambiguous daily gauge transcription."""
from datetime import date
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from server.acquire import save_mosaic
from server.acquire_bulletins import extract_table


def test_native_grid_alignment_preserves_complete_source_values(tmp_path):
    source = tmp_path / "source.tif"
    with rasterio.open(source, "w", driver="GTiff", width=20, height=20, count=1, dtype="float32", crs="EPSG:4326", transform=from_origin(71.999861111, 34.000138889, 1 / 3600, 1 / 3600), nodata=-9999) as dst:
        dst.write(np.full((1, 20, 20), 300, dtype="float32"))
    output = tmp_path / "prepared.tif"
    record = save_mosaic([source], output, [72.0001, 33.9951, 72.0049, 33.9999], nodata=-9999)
    assert record["valid_fraction"] == 1
    assert record["minimum"] == record["maximum"] == 300
    with rasterio.open(source) as src, rasterio.open(output) as prepared:
        assert (prepared.transform.c - src.transform.c) / src.res[0] == pytest.approx(round((prepared.transform.c - src.transform.c) / src.res[0]))


def table_fixture():
    header = " " * 30 + "Inflow" + " " * 14 + "Outflow" + " " * 13 + "Inflow" + " " * 14 + "Outflow"
    # The current Outflow column is distinct from historic peaks and last-year readings.
    line = "Nowshera 450,000 2010".ljust(30) + "18,000".ljust(20) + "19,000".ljust(20) + "300,000".ljust(20) + "307,000"
    return "ANNEXURE-I\nAugust 28, 2022 at 0600 Hours\n" + header + "\n" + line


def test_pdf_extraction_uses_current_outflow_and_reported_pkt_time():
    rows = extract_table(table_fixture(), date(2022, 8, 28), "test source", 4)
    assert len(rows) == 1
    assert rows[0]["discharge_cusecs"] == 307000
    assert rows[0]["discharge_m3s"] == pytest.approx(307000 * 0.028316846592)
    assert rows[0]["time"] == "2022-08-28T01:00:00+00:00"
    assert rows[0]["quality"] == "PDF column extraction; visual review required"


def test_pdf_extraction_does_not_guess_missing_header_or_time():
    assert extract_table(table_fixture().replace("0600 Hours", "time unknown"), date(2022, 8, 28), "test", 4) == []
    assert extract_table(table_fixture().replace("Outflow", "unknown"), date(2022, 8, 28), "test", 4) == []


def test_pdf_spaced_thousands_are_not_truncated_to_small_discharge():
    rows = extract_table(table_fixture().replace("307,000", "22 ,000"), date(2022, 8, 28), "test", 4)
    assert rows[0]["discharge_cusecs"] == 22000
    assert extract_table(table_fixture().replace("307,000", "61.000"), date(2022, 8, 28), "test", 4) == []


def test_first_download_waits_for_upstream_extent_before_rainfall(tmp_path, monkeypatch):
    import sys
    from server import acquire

    upstream = tmp_path / "upstream-ready.txt"

    def catchment():
        upstream.write_text("real upstream extent would be saved here", encoding="utf-8")
        return {"kind": None, "path": str(upstream)}

    def rainfall():
        assert upstream.is_file(), "Rainfall ran before catchment preparation."
        return {"kind": None, "path": str(tmp_path / "rainfall.tif")}

    monkeypatch.setattr(acquire, "BASE", tmp_path)
    monkeypatch.setattr(acquire, "assets", lambda: {})
    monkeypatch.setattr(acquire, "TASKS", {"chirps": rainfall, "catchment": catchment})
    monkeypatch.setattr(sys, "argv", ["server.acquire", "chirps", "catchment", "--workers", "2"])
    acquire.main()
    report = acquire.read_json(tmp_path / "acquisition.json")
    assert all(item["state"] == "downloaded-and-checked" for item in report["providers"].values())
