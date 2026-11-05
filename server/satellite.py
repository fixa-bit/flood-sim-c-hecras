"""Observed water extents from Sentinel-1 RTC backscatter. Run `python -m server.satellite --help`.

Satellite water is a calibration and validation target, never model forcing.
Each mask is built on the hydraulic model's own grid, so it can be compared
cell for cell with modelled depth. Every threshold and mask is recorded.

Method (per scene, identical for every scene):
1. Windowed read of the RTC gamma0 VV and VH bands over the model window
   (Microsoft Planetary Computer `sentinel-1-rtc`, anonymous SAS token).
2. 10*log10, then a 3x3 median filter against speckle.
3. Minimum-error (Bayes) thresholds on VV and VH between two Gaussian
   classes trained on independent labels: WorldCover-mapped water, and usable
   land more than 300 m from any mapped water. Otsu is unsuitable here: water
   is under 1% of the window and the turbulent, sediment-laden Kabul has a
   wide backscatter spread, so no histogram has a clean valley. Thresholds are
   bounded to plausible ranges (VV -20..-10 dB, VH -28..-15 dB). Water = both
   bands below threshold, applied to every usable pixel.
4. Unusable pixels are excluded, not called dry: slope > 10 deg (radar shadow
   and layover), WorldCover built-up (SAR misses flooding between buildings),
   more than 15 m above the nearest mapped water, and missing backscatter.
5. Aggregation to the 100 m model grid: a cell is valid when >= 50% of its
   pixels are usable; it is observed wet when >= 50% of its usable pixels are water.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path

import httpx
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import from_bounds
from scipy.ndimage import distance_transform_edt, median_filter

from .store import ROOT, checked_asset, file_hash, read_json, write_json

SEARCH = ROOT / "downloads" / "nowshera-2022" / "study" / "sentinel1-search.json"
TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-1-rtc"
NATIVE_M = 10
VV_BOUNDS_DB = (-20.0, -10.0)
VH_BOUNDS_DB = (-28.0, -15.0)
LAND_DISTANCE_M = 300
MAX_SLOPE_DEG = 10.0
MAX_HEIGHT_ABOVE_WATER_M = 15.0
BUILT_UP = 50
WATER_CLASS = 80
VALID_FRACTION = .5
WET_FRACTION = .5
METHOD_VERSION = "s1-rtc-bayes-landcover-v3"


def bayes_threshold(water, land):
    """Where two Gaussian class densities (equal priors) cross, between the class means."""
    water, land = water[np.isfinite(water)], land[np.isfinite(land)]
    if water.size < 100 or land.size < 100:
        raise ValueError("Too few labelled pixels for a threshold.")
    mw, ml = float(water.mean()), float(land.mean())
    # A spread below 0.01 dB only happens with synthetic data; keep the densities finite.
    sw, sl = max(float(water.std()), .01), max(float(land.std()), .01)
    if not mw < ml:
        raise ValueError("Mapped water is not darker than land; the scene cannot be thresholded.")
    xs = np.linspace(mw, ml, 2001)
    pw = np.exp(-.5 * ((xs - mw) / sw) ** 2) / sw
    pl = np.exp(-.5 * ((xs - ml) / sl) ** 2) / sl
    return float(xs[int(np.argmin(np.abs(pw - pl)))]), {"water_mean_db": mw, "water_std_db": sw,
                                                        "land_mean_db": ml, "land_std_db": sl}


def bounded(value, limits):
    return float(min(max(value, limits[0]), limits[1]))


def classify(vv_db, vh_db, usable, water_label, land_label):
    """Water where both polarisations are below their bounded minimum-error thresholds."""
    water_label, land_label = water_label & usable, land_label & usable
    raw_vv, vv_stats = bayes_threshold(vv_db[water_label], vv_db[land_label])
    raw_vh, vh_stats = bayes_threshold(vh_db[water_label], vh_db[land_label])
    t_vv, t_vh = bounded(raw_vv, VV_BOUNDS_DB), bounded(raw_vh, VH_BOUNDS_DB)
    water = usable & (vv_db < t_vv) & (vh_db < t_vh)
    return water, {"vv_db": t_vv, "vh_db": t_vh, "vv_raw_db": raw_vv, "vh_raw_db": raw_vh,
                   "vv_clamped": t_vv != raw_vv, "vh_clamped": t_vh != raw_vh, "vv_classes": vv_stats, "vh_classes": vh_stats,
                   "training_pixels": {"water": int(water_label.sum()), "land": int(land_label.sum())},
                   # Share of each training class the rule assigns to water (in-sample, both bands).
                   "mapped_water_called_water": float(water[water_label].mean()),
                   "distant_land_called_water": float(water[land_label].mean())}


def aggregate(water, usable, factor):
    """Native pixels -> model cells by block fractions (exact integer factor)."""
    rows, cols = water.shape[0] // factor, water.shape[1] // factor
    shape = (rows, factor, cols, factor)
    usable_fraction = usable[:rows * factor, :cols * factor].reshape(shape).mean(axis=(1, 3))
    water_count = water[:rows * factor, :cols * factor].reshape(shape).sum(axis=(1, 3))
    usable_count = usable[:rows * factor, :cols * factor].reshape(shape).sum(axis=(1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        wet_fraction = np.where(usable_count > 0, water_count / usable_count, 0.0)
    valid = usable_fraction >= VALID_FRACTION
    observed = np.full(valid.shape, 255, dtype="uint8")
    observed[valid] = (wet_fraction[valid] >= WET_FRACTION).astype("uint8")
    return observed, usable_fraction, wet_fraction


def _items(date):
    features = read_json(SEARCH)["features"]
    chosen = [f for f in features if f["properties"]["datetime"].startswith(date)]
    if not chosen:
        raise ValueError(f"No stored Sentinel-1 RTC item on {date}.")
    return chosen


def _read_band(items, band, token, grid):
    """Mosaic one band of all items of a pass onto the native-resolution grid (first valid wins)."""
    transform, shape, crs = grid
    output = np.full(shape, np.nan, dtype="float32")
    west, top = transform.c, transform.f
    east, bottom = west + shape[1] * NATIVE_M, top - shape[0] * NATIVE_M
    with rasterio.Env(GDAL_HTTP_TIMEOUT=90, GDAL_HTTP_MAX_RETRY=3, GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        for item in items:
            with rasterio.open(item["assets"][band]["href"] + "?" + token) as src:
                b = transform_bounds(crs, src.crs, west, bottom, east, top)
                window = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
                data = src.read(1, window=window, boundless=True, fill_value=src.nodata if src.nodata is not None else 0).astype("float32")
                data[(data <= 0) | (data == src.nodata)] = np.nan
                part = np.full(shape, np.nan, dtype="float32")
                reproject(data, part, src_transform=src.window_transform(window), src_crs=src.crs, src_nodata=np.nan,
                          dst_transform=transform, dst_crs=crs, dst_nodata=np.nan, resampling=Resampling.nearest)
            fill = np.isnan(output) & np.isfinite(part)
            output[fill] = part[fill]
    return output


def _ancillary(site, grid):
    """Slope, built-up and height above nearest mapped water on the native grid."""
    transform, shape, crs = grid
    _, dem_path = checked_asset("dem", site)
    _, cover_path = checked_asset("landcover", site)
    dem = np.full(shape, np.nan, dtype="float32")
    cover = np.zeros(shape, dtype="uint8")
    with rasterio.open(dem_path) as src:
        reproject(rasterio.band(src, 1), dem, dst_transform=transform, dst_crs=crs, dst_nodata=np.nan,
                  resampling=Resampling.bilinear)
    with rasterio.open(cover_path) as src:
        reproject(rasterio.band(src, 1), cover, dst_transform=transform, dst_crs=crs, resampling=Resampling.nearest)
    dzdy, dzdx = np.gradient(np.nan_to_num(dem, nan=float(np.nanmean(dem))), NATIVE_M)
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    mapped_water = cover == WATER_CLASS
    if not mapped_water.any():
        raise ValueError("No WorldCover water in the window to reference heights against.")
    distance, (rows, cols) = distance_transform_edt(~mapped_water, return_indices=True)
    height_above_water = dem - dem[rows, cols]
    return {"slope_deg": slope, "built_up": cover == BUILT_UP, "height_above_water_m": height_above_water,
            "mapped_water": mapped_water, "dem_finite": np.isfinite(dem),
            "distant_land": distance * NATIVE_M > LAND_DISTANCE_M}


def build(site, date, model_grid, output_dir):
    """Observed water mask for one scene on a model grid (west, bottom, east, top, cell, crs)."""
    west, bottom, east, top, cell, crs = model_grid
    factor = round(cell / NATIVE_M)
    if factor * NATIVE_M != cell:
        raise ValueError("Model cell size must be a multiple of the 10 m native resolution.")
    shape = (round((top - bottom) / NATIVE_M), round((east - west) / NATIVE_M))
    grid = (from_origin(west, top, NATIVE_M, NATIVE_M), shape, crs)
    items = _items(date)
    token = httpx.get(TOKEN_URL, timeout=30).json()["token"]
    vv = _read_band(items, "vv", token, grid)
    vh = _read_band(items, "vh", token, grid)
    with np.errstate(divide="ignore", invalid="ignore"):
        vv_db = median_filter(10 * np.log10(vv), size=3)
        vh_db = median_filter(10 * np.log10(vh), size=3)
    ancillary = _ancillary(site, grid)
    reasons = {
        "no_backscatter": ~(np.isfinite(vv_db) & np.isfinite(vh_db)),
        "steep_shadow_layover": ancillary["slope_deg"] > MAX_SLOPE_DEG,
        "built_up": ancillary["built_up"],
        "high_above_water": ancillary["height_above_water_m"] > MAX_HEIGHT_ABOVE_WATER_M,
        "no_terrain": ~ancillary["dem_finite"],
    }
    excluded = np.zeros(shape, bool)
    for mask in reasons.values():
        excluded |= mask
    usable = ~excluded
    water, thresholds = classify(vv_db, vh_db, usable, ancillary["mapped_water"], ancillary["distant_land"])
    observed, usable_fraction, wet_fraction = aggregate(water, usable, factor)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_transform = from_origin(west, top, cell, cell)
    extent_path = output_dir / "observed-extent.tif"
    with rasterio.open(extent_path, "w", driver="GTiff", width=observed.shape[1], height=observed.shape[0], count=1,
                       dtype="uint8", crs=crs, transform=model_transform, nodata=255, compress="deflate") as dst:
        dst.write(observed, 1)
        dst.update_tags(meaning="1 observed water, 0 observed dry, 255 not observable", method=METHOD_VERSION)
    native_path = output_dir / "water-10m.tif"
    native = np.where(usable, water.astype("uint8"), 255).astype("uint8")
    with rasterio.open(native_path, "w", driver="GTiff", width=shape[1], height=shape[0], count=1, dtype="uint8",
                       crs=crs, transform=grid[0], nodata=255, compress="deflate") as dst:
        dst.write(native, 1)
    review_png(vv_db, water, excluded, output_dir / "review.png")
    item = items[0]
    record = {
        "method": METHOD_VERSION, "site": site, "date": date,
        "acquired": [{"id": i["id"], "datetime": i["properties"]["datetime"],
                      "orbit": i["properties"].get("sat:orbit_state"), "relative_orbit": i["properties"].get("sat:relative_orbit"),
                      "vv": i["assets"]["vv"]["href"], "vh": i["assets"]["vh"]["href"],
                      "vv_checksum": i["assets"]["vv"].get("file:checksum"), "vh_checksum": i["assets"]["vh"].get("file:checksum")}
                     for i in items],
        "time": item["properties"]["datetime"].replace("Z", "+00:00"),
        "source": "Sentinel-1 RTC gamma0 (Microsoft Planetary Computer sentinel-1-rtc); contains modified Copernicus Sentinel data 2022",
        "license": next((link["href"] for link in item["links"] if link["rel"] == "license"), None),
        "thresholds": thresholds,
        "rules": {"median_filter": "3x3", "threshold": "minimum-error between Gaussian classes: WorldCover water vs usable land "
                  f"> {LAND_DISTANCE_M} m from mapped water", "vv_bounds_db": VV_BOUNDS_DB, "vh_bounds_db": VH_BOUNDS_DB,
                  "max_slope_deg": MAX_SLOPE_DEG, "max_height_above_mapped_water_m": MAX_HEIGHT_ABOVE_WATER_M,
                  "excluded_landcover": "WorldCover 50 built-up", "valid_cell_fraction": VALID_FRACTION,
                  "wet_cell_fraction": WET_FRACTION},
        "native": {"pixels": int(water.size), "usable": int(usable.sum()), "water": int(water.sum()),
                   "excluded_by": {name: int(mask.sum()) for name, mask in reasons.items()}},
        "model_grid": {"bounds": [west, bottom, east, top], "cell_m": cell, "crs": crs, "shape": list(observed.shape),
                       "valid_cells": int((observed != 255).sum()), "observed_wet_cells": int((observed == 1).sum())},
        "files": {"observed_extent": {"path": extent_path.relative_to(ROOT).as_posix(), "sha256": file_hash(extent_path)},
                  "water_10m": {"path": native_path.relative_to(ROOT).as_posix(), "sha256": file_hash(native_path)},
                  "review_png": (output_dir / "review.png").relative_to(ROOT).as_posix()},
        "built_at": datetime.now().astimezone().isoformat(),
    }
    write_json(output_dir / "mask.json", record)
    return record


def review_png(vv_db, water, excluded, path, scale=4):
    """Backscatter in grey, water in blue, excluded pixels tinted red; for visual review."""
    from PIL import Image
    grey = np.clip((np.nan_to_num(vv_db, nan=-30) + 25) / 25, 0, 1)
    rgb = np.stack([grey, grey, grey], axis=-1)
    rgb[excluded] = rgb[excluded] * .55 + np.array([.45, .05, .05])
    rgb[water] = np.array([.15, .45, 1.0])
    image = Image.fromarray((rgb[::scale, ::scale] * 255).astype("uint8"))
    image.save(path)


def main():
    from . import warsak
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dates", nargs="+", help="Scene dates, e.g. 2022-08-25 2022-09-05")
    args = parser.parse_args()
    geometry = read_json(warsak.GEOMETRY / "geometry.json")
    if not geometry:
        raise ValueError("Prepare the Warsak geometry first.")
    grid = geometry["summary"]["grid"]
    west, bottom, east, top = grid["bounds"]
    for date in args.dates:
        record = build(warsak.SITE, date, (west, bottom, east, top, grid["cell_m"], grid["crs"]),
                       warsak.SITE_DIR / "satellite" / date)
        print(json.dumps({key: record[key] for key in ["date", "time", "thresholds", "native", "model_grid"]}, indent=2))


if __name__ == "__main__":
    main()
