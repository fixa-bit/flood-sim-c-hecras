"""Isolated geometry/convergence fixtures, never observations or study inputs."""
import numpy as np
import pytest
from rasterio.transform import from_origin

from server.channel import condition_channel, warmup_review


def channel_fixture():
    dem = np.round(np.broadcast_to(300 - np.arange(40) * .1, (20, 40)).copy(), 3)
    fraction = np.zeros_like(dem)
    fraction[8:12] = 1
    surface = np.where(fraction > 0, dem, np.nan)
    return dem, fraction, surface, from_origin(1000, 3000, 100, 100)


def test_estimated_bed_preserves_all_land_and_records_its_assumptions():
    dem, fraction, surface, affine = channel_fixture()
    bed, corridor, path, report = condition_channel(dem, fraction, surface, affine, 50)
    assert np.array_equal(bed[~corridor], dem[~corridor])
    assert np.all(bed[corridor] < dem[corridor])
    assert np.all(corridor[path[:, 0], path[:, 1]])
    assert path[0, 1] == 0 and path[-1, 1] == dem.shape[1] - 1
    assert report["bed_is_estimated_not_surveyed"] is True
    assert report["floodplain_modified_cells"] == 0
    assert report["maximum_lowering_m"] < 5


def test_disconnected_water_is_rejected_instead_of_carving_across_land():
    dem, fraction, surface, affine = channel_fixture()
    fraction[:, 20] = 0
    with pytest.raises(ValueError, match="connected corridor"):
        condition_channel(dem, fraction, surface, affine, 50)


def warmup_fixture():
    seconds = 72 * 3600
    mass = np.zeros((8, 12))
    mass[:, 0] = seconds - np.arange(7, -1, -1) * 3600 + 5
    mass[:, 5] = 1e6
    mass[:, 8] = 100
    sections = np.column_stack([mass[:, 0], np.full(8, 100)])
    corridor = np.zeros((5, 7), dtype=bool)
    corridor[2] = True
    centerline = np.column_stack([np.full(7, 2), np.arange(7)])
    depth = corridor.astype(float)
    return mass, sections, depth, corridor, centerline, seconds, 100


def test_warmup_requires_steady_flow_storage_and_a_wet_channel():
    report = warmup_review(*warmup_fixture())
    assert report["passed"]
    assert report["wet_connection_inlet_to_outlet"]
    assert report["is_observed_pre_event_hydrograph"] is False


@pytest.mark.parametrize("failure", ["flow", "storage", "dry_gap"])
def test_unsettled_or_disconnected_warmup_cannot_be_published(failure):
    mass, sections, depth, corridor, centerline, seconds, baseflow = warmup_fixture()
    if failure == "flow":
        mass[-1, 8] = 90
    elif failure == "storage":
        mass[-1, 5] *= 1.05
    else:
        depth[2, 3] = 0
    with pytest.raises(ValueError, match="has not converged"):
        warmup_review(mass, sections, depth, corridor, centerline, seconds, baseflow)
