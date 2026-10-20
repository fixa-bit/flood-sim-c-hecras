"""Boundary provenance, withheld-data isolation, and real terrain tile alignment."""
from datetime import datetime, timedelta, timezone
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from server.study import interpolated_boundary, fit_rainfall_factor, TRAIN_END
from server.study_hms import select_parameters
from server.map_context import height_tile, tile_bounds


def test_boundary_interpolation_preserves_observations_and_labels_estimates():
    start = datetime(2022, 8, 20, 1, tzinfo=timezone.utc)
    rows = [{"station_id": "warsak", "time": start.isoformat(), "discharge_m3s": "100", "source": "first PDF"},
            {"station_id": "warsak", "time": (start + timedelta(days=1)).isoformat(), "discharge_m3s": "340", "source": "second PDF"}]
    output = interpolated_boundary(rows, "warsak", start, start + timedelta(days=1))
    assert output[0]["value_type"] == output[-1]["value_type"] == "observed"
    assert output[12]["discharge_m3s"] == 220
    assert output[12]["value_type"] == "modeled"
    assert output[12]["source"] == "first PDF" and output[12]["right_source"] == "second PDF"
    with pytest.raises(ValueError, match="extrapolation refused"):
        interpolated_boundary(rows, "warsak", start - timedelta(hours=1), start + timedelta(days=1))
    with pytest.raises(ValueError, match="unique"):
        interpolated_boundary(rows + [rows[0]], "warsak", start, start + timedelta(days=1))


def test_rainfall_fit_never_uses_validation_values():
    rows = [{"date": "2022-08-25", "chirps_mm": 10.0, "gauge_mm": 20.0} for _ in range(8)]
    validation = [{"date": "2022-08-28", "chirps_mm": 200.0, "gauge_mm": 1.0}]
    assert fit_rainfall_factor(rows + validation) == 2
    validation[0]["gauge_mm"] = 100000
    assert fit_rainfall_factor(rows + validation) == 2
    with pytest.raises(ValueError, match="Insufficient"):
        fit_rainfall_factor(validation)


def test_routing_parameter_selection_ignores_heldout_observations():
    times = [(TRAIN_END - timedelta(days=i)).isoformat() for i in [3, 2, 1]]
    observed = [{"time": time, "observed_m3s": str(value)} for time, value in zip(times, [110, 220, 330])]
    heldout = {"time": TRAIN_END.isoformat(), "observed_m3s": "10000"}
    candidates = [("good", 3, 6), ("bad", 6, 12)]
    outputs = {"good": dict(zip(times, [100, 210, 320])), "bad": dict(zip(times, [300, 200, 100]))}
    first, _ = select_parameters(candidates, outputs, observed + [heldout])
    heldout["observed_m3s"] = "1"
    second, _ = select_parameters(candidates, outputs, observed + [heldout])
    assert first == second
    assert first["model"] == "good" and first["estimated_local_constant_m3s"] == 10


def test_terrain_neighbour_tiles_share_identical_source_heights_at_edge(tmp_path):
    path = tmp_path / "source.tif"
    rows, columns = np.mgrid[:400, :400]
    values = (500 + rows * .2 + columns * .1).astype("float32")
    with rasterio.open(path, "w", driver="GTiff", width=400, height=400, count=1, dtype="float32", crs="EPSG:4326", transform=from_origin(71, 35, .005, .005), nodata=-9999) as dst:
        dst.write(values, 1)
    level = 10
    width = 180 / 2 ** level
    x, y = int((71.8 + 180) / width), int((90 - 34.1) / width)
    west = np.frombuffer(height_tile("test", (str(path),), level, x, y), dtype="<f4").reshape(65, 65)
    east = np.frombuffer(height_tile("test", (str(path),), level, x + 1, y), dtype="<f4").reshape(65, 65)
    assert np.isfinite(west).all() and west.min() > 500
    np.testing.assert_allclose(west[:, -1], east[:, 0], atol=1e-3)
    assert west[0, 0] < west[-1, 0]  # north/south row order preserved
    with pytest.raises(ValueError):
        tile_bounds(15, x, y)
