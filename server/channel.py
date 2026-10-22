"""Public-data channel conditioning, with estimated (never surveyed) bed levels.

WorldCover supplies the water footprint; FABDEM supplies a reference water-surface
profile. Rectangular Manning normal depths at the initial modeled flow estimate
the missing bed. This is an explicit hydraulic-geometry assumption, not fitting to
the withheld discharge observations or a hydraulic flow solver.
"""
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from scipy.ndimage import distance_transform_edt, label
from scipy.optimize import isotonic_regression
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree


def water_sources(dem_path, cover_path, dims, affine, crs):
    with rasterio.open(dem_path) as dem, rasterio.open(cover_path) as cover:
        categories = np.zeros((dem.height, dem.width), dtype="int16")
        reproject(rasterio.band(cover, 1), categories, src_transform=cover.transform,
                  src_crs=cover.crs, dst_transform=dem.transform, dst_crs=dem.crs,
                  resampling=Resampling.nearest)
        water = categories == 80
        elevations = dem.read(1, masked=True).astype("float32").filled(np.nan)
        elevations[~water] = np.nan
        fraction = np.zeros(dims, dtype="float32")
        surface = np.full(dims, np.nan, dtype="float32")
        for source, dest, nodata in [(water.astype("float32"), fraction, None), (elevations, surface, np.nan)]:
            reproject(source, dest, src_transform=dem.transform, src_crs=dem.crs,
                      src_nodata=nodata, dst_transform=affine, dst_crs=crs,
                      dst_nodata=np.nan, resampling=Resampling.average)
    if not np.isfinite(fraction).all():
        raise ValueError("The water footprint does not cover the computational grid.")
    return fraction, surface


def normal_depth(discharge, width, slope, manning=.035):
    """Solve rectangular Manning conveyance, without using event validation data."""
    if not all(np.isfinite([discharge, width, slope, manning])) or min(discharge, width, slope, manning) <= 0:
        raise ValueError("Normal depth requires positive finite flow, width, slope and roughness.")
    low, high = 0., 100.
    def conveyance(depth):
        area = width * depth
        return area / manning * (area / (width + 2 * depth)) ** (2 / 3) * slope ** .5
    if conveyance(high) < discharge:
        raise ValueError("Estimated channel depth exceeds the supported 100 m bracket.")
    for _ in range(70):
        middle = (low + high) / 2
        if conveyance(middle) < discharge:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def condition_channel(dem, fraction, surface, affine, discharge):
    cell = float(affine.a)
    components, _ = label(fraction >= .25)  # Four-connected resolved water only.
    west = set(components[:, 0]) - {0}
    east = set(components[:, -1]) - {0}
    spans = west & east
    if len(spans) != 1:
        raise ValueError("Mapped water must contain one unambiguous west-to-east connected corridor.")
    corridor = components == spans.pop()
    rows, cols = np.where(corridor)
    if not np.isfinite(surface[corridor]).all():
        raise ValueError("Mapped channel lacks reference water-surface elevations.")
    indexes = np.full(dem.shape, -1, dtype=int)
    indexes[rows, cols] = np.arange(len(rows))
    clearance = distance_transform_edt(np.pad(corridor, 1))[1:-1, 1:-1]
    a, b, costs = [], [], []
    # A water-confined, center-preferring path supplies longitudinal chainage.
    # It never draws a channel through dry land to connect disconnected masks.
    for dr, dc in [(0, 1), (1, 0), (1, 1), (1, -1)]:
        rr, cc = rows + dr, cols + dc
        valid = (rr >= 0) & (rr < dem.shape[0]) & (cc >= 0) & (cc < dem.shape[1])
        source = np.flatnonzero(valid)
        target = indexes[rr[valid], cc[valid]]
        keep = target >= 0
        source, target = source[keep], target[keep]
        cost = cell * np.hypot(dr, dc) * (1 + 1 / (clearance[rows[source], cols[source]] + clearance[rows[target], cols[target]]))
        a.extend(source); b.extend(target); costs.extend(cost)
        a.extend(target); b.extend(source); costs.extend(cost)
    graph = csr_matrix((costs, (a, b)), shape=(len(rows), len(rows)))
    start_candidates = np.flatnonzero(cols == 0)
    start = int(start_candidates[len(start_candidates) // 2])
    distances, predecessors = dijkstra(graph, indices=start, return_predecessors=True)
    exits = np.flatnonzero(cols == dem.shape[1] - 1)
    end = int(exits[np.argmin(distances[exits])])
    path = [end]
    while path[-1] != start:
        previous = int(predecessors[path[-1]])
        if previous < 0 or len(path) > len(rows):
            raise ValueError("Mapped-water centerline cannot reach its upstream entry.")
        path.append(previous)
    path = np.array(path[::-1])
    path_rc = np.column_stack([rows[path], cols[path]])
    chainage = np.r_[0., np.cumsum(np.linalg.norm(np.diff(path_rc, axis=0), axis=1) * cell)]
    nearest = cKDTree(path_rc).query(np.column_stack([rows, cols]))[1]
    positions = chainage[nearest]
    edges = np.linspace(0, chainage[-1], max(3, int(np.ceil(chainage[-1] / 500))) + 1)
    bins = np.minimum(np.searchsorted(edges, positions, side="right") - 1, len(edges) - 2)
    centers = (edges[:-1] + edges[1:]) / 2
    widths, levels, counts = [], [], []
    for index in range(len(centers)):
        selected = bins == index
        counts.append(int(selected.sum()))
        widths.append(selected.sum() * cell ** 2 / (edges[index + 1] - edges[index]))
        levels.append(float(np.percentile(surface[rows[selected], cols[selected]], 25)) if selected.any() else np.nan)
    widths, levels = np.array(widths), np.array(levels)
    if not np.isfinite(levels).all() or np.any(widths < cell):
        raise ValueError("A channel profile segment lacks enough mapped-water support.")
    # Remove DEM water-surface steps/upslope noise along flow direction. No
    # floodplain elevations or withheld observations enter this operation.
    levels = isotonic_regression(levels, weights=np.array(counts, dtype=float), increasing=False).x
    slope = float((levels[0] - levels[-1]) / (centers[-1] - centers[0]))
    if not 0 < slope < .02:
        raise ValueError("Mapped water-surface profile does not support a downstream slope.")
    depths = np.array([normal_depth(discharge, width, slope) for width in widths])
    estimated = np.interp(positions, centers, levels - depths)
    conditioned = dem.copy()
    conditioned[rows, cols] = np.minimum(dem[rows, cols], estimated)
    conditioned = np.round(conditioned, 3)
    if not np.array_equal(conditioned[~corridor], dem[~corridor]):
        raise ValueError("Channel conditioning changed terrain outside the mapped-water corridor.")
    report = {"method": "WorldCover >=25% water-fraction connected corridor; water-confined centerline; 500 m profile bins; monotone FABDEM water surface minus rectangular Manning normal depth at initial HMS flow",
        "bed_is_estimated_not_surveyed": True, "water_fraction_threshold": .25,
        "discharge_m3s": float(discharge), "channel_manning_n": .035, "slope": slope,
        "length_m": float(chainage[-1]), "water_cells": int(corridor.sum()),
        "modified_cells": int(np.count_nonzero(conditioned != dem)), "floodplain_modified_cells": 0,
        "maximum_lowering_m": float((dem - conditioned).max()),
        "width_range_m": [float(widths.min()), float(widths.max())],
        "normal_depth_range_m": [float(depths.min()), float(depths.max())],
        "profile": [{"chainage_m": float(c), "width_m": float(w), "reference_surface_m": float(z), "normal_depth_m": float(d)} for c, w, z, d in zip(centers, widths, levels, depths)]}
    return conditioned, corridor, path_rc, report


def warmup_review(mass, sections, first_depth, corridor, centerline, seconds, baseflow):
    recent = (mass[:, 0] >= seconds - 6 * 3600) & (mass[:, 0] <= seconds + 20.001)
    samples = mass[recent]
    flows = sections[recent, 1:].sum(axis=1)
    if len(samples) < 6:
        raise ValueError("Warm-up lacks six hours of convergence diagnostics.")
    q_error = float(np.max(np.abs(samples[:, 8] - baseflow)) / baseflow)
    section_error = float(np.max(np.abs(flows - baseflow)) / baseflow)
    storage_change = float(np.ptp(samples[:, 5]) / max(float(samples[-1, 5]), 1))
    wet = first_depth > .05
    components, _ = label(wet & corridor)
    connected = bool((set(components[:, 0]) & set(components[:, -1])) - {0})
    center_wet = float(np.mean(wet[centerline[:, 0], centerline[:, 1]]))
    review = {"duration_seconds": seconds, "constant_initial_modeled_flow_m3s": baseflow,
        "is_observed_pre_event_hydrograph": False, "convergence_window_hours": 6,
        "maximum_outflow_relative_error": q_error, "maximum_gauge_relative_error": section_error,
        "relative_storage_range": storage_change, "outflow_and_gauge_limit": .02, "storage_limit": .01,
        "centerline_wet_fraction": center_wet, "wet_connection_inlet_to_outlet": connected,
        "first_frame_wet_cells": int(wet.sum()),
        "passed": q_error <= .02 and section_error <= .02 and storage_change <= .01 and connected and center_wet >= .95}
    if not review["passed"]:
        raise ValueError(f"River warm-up has not converged; refusing flood publication: {review}")
    return review
