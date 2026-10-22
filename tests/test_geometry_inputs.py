"""Survey/datum/coverage acceptance and published roughness prior limits."""

from datetime import date
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from server.geometry_inputs import RULES, crosswalk, surveyed_terrain
from server.store import file_hash, read_json


def test_roughness_prior_is_classified_bounded_and_has_no_unknown_default():
    rules = read_json(RULES)
    codes = np.array([[10, 20, 30, 40, 50, 60, 80]], dtype="uint8")
    result = crosswalk(codes, rules)
    assert np.all(result["low"] <= result["n"])
    assert np.all(result["n"] <= result["high"])
    assert len(np.unique(result["n"])) == 6
    assert result["n"][0, -1] == pytest.approx(0.035)
    assert result["n"][0, 4] == pytest.approx(0.10)
    for code in [0, 70, 95, 100, 255]:
        with pytest.raises(ValueError, match="unsupported classes"):
            crosswalk(np.array([[code]]), rules)
    for code in [80.5, np.nan, np.inf]:
        with pytest.raises(ValueError, match="finite integers"):
            crosswalk(np.array([[code]]), rules)


def test_selected_roughness_cannot_exceed_its_documented_range():
    rules = read_json(RULES)
    rules["classes"][0]["n"] = 0.50
    with pytest.raises(ValueError, match="documented roughness range"):
        crosswalk(np.array([[10]]), rules)


def survey_fixture(tmp_path):
    """Synthetic contract fixture, never used in a historical simulation."""
    base = tmp_path / "base"
    base.mkdir()
    shape = (4, 5)
    affine = from_origin(770000, 3770000, 100, 100)

    def save(path, values, *, crs="EPSG:32642", transform=affine, nodata=-9999):
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            count=1,
            height=shape[0],
            width=shape[1],
            dtype=str(values.dtype),
            crs=crs,
            transform=transform,
            nodata=nodata,
        ) as dst:
            dst.write(values, 1)

    reference = np.full(shape, 300, dtype="float32")
    channel = np.zeros(shape, dtype="uint8")
    channel[1:3, :] = 1
    values = np.full(shape, 297, dtype="float32")
    save(base / "unconditioned-terrain.tif", reference)
    save(base / "channel-mask.tif", channel, nodata=0)
    terrain = tmp_path / "fixture-survey.tif"
    coverage = tmp_path / "fixture-coverage.tif"
    save(terrain, values)
    save(coverage, channel, nodata=None)
    review = {
        "source": "Synthetic unit-test fixture, not field observations",
        "survey_date": "2022-08-01",
        "survey_method": "test fixture",
        "review": "Synthetic contract check",
        "grid_aggregation_review": "Explicit 100 m test grid",
        "historical_representativeness_review": "Not an actual event survey",
        "channel_bed_measured": True,
        "is_dem_derived_bathymetry": False,
        "vertical_datum": "EGM2008",
        "source_vertical_datum": "EGM2008",
        "elevation_units": "m",
        "reviewed_boundary_slope": 0.0004,
        "terrain": terrain.name,
        "coverage": coverage.name,
        "terrain_sha256": file_hash(terrain),
        "coverage_sha256": file_hash(coverage),
    }
    path = tmp_path / "review.json"
    path.write_text(json.dumps(review), encoding="utf-8")
    return base, review, path, save, reference, channel


def test_survey_import_changes_only_declared_measured_coverage(tmp_path):
    base, review, path, _, reference, channel = survey_fixture(tmp_path)
    values, audit = surveyed_terrain(path, base)
    assert np.array_equal(values[channel == 0], reference[channel == 0])
    assert np.all(values[channel > 0] == 297)
    assert audit["bed_is_surveyed"] is True
    assert audit["resolved_channel_coverage_fraction"] == 1
    assert audit["modified_cells"] == 10


@pytest.mark.parametrize(
    "change",
    [
        {"channel_bed_measured": False},
        {"is_dem_derived_bathymetry": True},
        {"vertical_datum": "unknown"},
        {"elevation_units": "ft"},
        {"source_vertical_datum": "ellipsoidal"},
        {"grid_aggregation_review": ""},
        {"historical_representativeness_review": ""},
        {"reviewed_boundary_slope": 0},
        {"terrain_sha256": "0" * 64},
    ],
)
def test_survey_import_rejects_unreviewed_or_incompatible_geometry(tmp_path, change):
    base, review, path, *_ = survey_fixture(tmp_path)
    path.write_text(json.dumps({**review, **change}), encoding="utf-8")
    with pytest.raises(ValueError):
        surveyed_terrain(path, base)


def test_survey_import_does_not_fill_missing_channel_data_or_shift_datums(tmp_path):
    base, review, path, save, _, channel = survey_fixture(tmp_path)
    coverage = channel.copy()
    coverage[1, 2] = 0
    save(tmp_path / review["coverage"], coverage, nodata=None)
    review["coverage_sha256"] = file_hash(tmp_path / review["coverage"])
    path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="entire resolved model channel"):
        surveyed_terrain(path, base)
    save(tmp_path / review["coverage"], channel, nodata=None)
    review["coverage_sha256"] = file_hash(tmp_path / review["coverage"])
    save(
        tmp_path / review["terrain"],
        np.full(channel.shape, 297, dtype="float32"),
        transform=from_origin(770050, 3770000, 100, 100),
    )
    review["terrain_sha256"] = file_hash(tmp_path / review["terrain"])
    path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="grid exactly"):
        surveyed_terrain(path, base)
