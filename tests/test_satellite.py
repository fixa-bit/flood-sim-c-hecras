"""Synthetic backscatter checks for the Sentinel-1 water-mask method."""
import numpy as np

from server.satellite import aggregate, bayes_threshold, classify


def test_minimum_error_threshold_sits_between_water_and_land():
    rng = np.random.default_rng(0)
    water = rng.normal(-18, 2, 5000)
    land = rng.normal(-8, 2, 50000)
    threshold, stats = bayes_threshold(water, land)
    assert -14 < threshold < -12  # equal-variance classes cross at the midpoint, -13 dB
    assert stats["water_mean_db"] < threshold < stats["land_mean_db"]


def test_water_needs_both_bands_low_and_unusable_pixels_are_never_dry():
    rng = np.random.default_rng(1)
    shape = (40, 40)
    vv = rng.normal(-8, 1, shape)
    vh = rng.normal(-14, 1, shape)
    river = np.zeros(shape, bool)
    river[10:20, :] = True  # exactly model-grid row 1
    vv[river] = rng.normal(-20, 1, river.sum())
    vh[river] = rng.normal(-26, 1, river.sum())
    vh[30, 5] = -26  # low VH alone is not water
    usable = np.ones(shape, bool)
    usable[:, 32:] = False  # e.g. radar shadow: 80% of model column 3
    land = ~river & usable
    land[5:25, :] = False  # land labels kept away from the river
    water, thresholds = classify(vv, vh, usable, river, land)
    assert water[river & usable].all() and not water[30, 5]
    assert not water[:, 32:].any()
    assert thresholds["mapped_water_called_water"] == 1.0
    assert thresholds["distant_land_called_water"] == 0.0

    observed, usable_fraction, wet_fraction = aggregate(water, usable, 10)
    assert observed.shape == (4, 4)  # 10 x 10 native pixels per model cell
    assert (observed[1, :3] == 1).all()  # the river row is observed wet
    assert (observed[[0, 2, 3], :3] == 0).all()  # land rows observed dry
    assert (observed[:, 3] == 255).all()  # 80% unusable: not observable, not dry
    assert np.allclose(usable_fraction[:, 3], .2)
    assert np.allclose(wet_fraction[1, :3], 1.0)
