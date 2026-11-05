"""Warsak site: the Kabul River below Warsak Dam. Run `python -m server.warsak --help`.

Prepares every model input that does not depend on the dam release:
terrain, land cover, rivers, catchment, soil, the hydraulic domain and the
mapped-water channel corridor. The inflow is deliberately not supplied. The
2022 Warsak record available publicly is 20 timed FFC readings with gaps of
up to 24 hours, and the project owner chose to wait for a continuous record
instead of interpolating those. `status` reports what is ready and what is
still missing; nothing here computes water.

The reservoir above the dam is outside the model. Modelling it would need
the Kabul inflow from Afghanistan and the dam's gate operations, neither of
which is available. The model starts below the dam, where the Warsak gauge
measures the release that becomes its upstream boundary.
"""
import argparse
import csv
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

import math

import numpy as np
from pyproj import Transformer
from rasterio.transform import from_origin
from rasterio.warp import Resampling
from shapely import from_wkb, union_all
from shapely.geometry import Point, box, mapping, shape
from .tributaries import transform

from .acquire import BASE as NOWSHERA_BASE, download, hydro_url, HYDRO_BASINS_PAGE, raster_record, save_mosaic
from .cli import register
from .store import ROOT, assets, checked_asset, file_hash, read_json, write_json

SITE = "warsak"
BASE = ROOT / "downloads" / "warsak-2022"
SITE_DIR = ROOT / "sites" / SITE
# Buffer around the app's 20 km Warsak window (71.145-71.579 E, 33.981-34.340 N).
BOUNDS = [71.10, 33.94, 71.62, 34.38]
# Station catalogue position of the Warsak gauge (FFD flood limits; Warsak Dam).
OUTLET = (71.3619, 34.1608)
WORLDCOVER = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N33E069_Map.tif"
SOIL_VARIABLES = ["sand", "clay", "soc", "bdod"]
REQUIRED = ["dem", "landcover", "hydrography", "catchment", "soil"]
# The model starts below the dam. A FABDEM/WorldCover profile along HydroRIVERS
# shows the reservoir surface at ~388-390 m to 71.353 E, the dam drop by
# 71.360 E, then a narrow hill-confined reach; mapped water is continuous from
# ~71.39 E at 342-344 m. The western edge sits where the river has left that
# reach, about 4 km below the dam. The dam release enters there.
MODEL_WEST_LON = 71.40
# Major Kabul reaches here drain 68,500-69,200 km^2 (HydroRIVERS UPLAND_SKM);
# the Swat junction (>83,000 km^2) is outside the window.
MAJOR_UPLAND_KM2 = 60000
MESH_M = 100
# The app's Warsak window: 20 km around the station.
RADIUS_KM = 20
EDGE_MARGIN_M = 600
GRID_ALIGNMENT_M = 200
WATER_FRACTION = .25
GEOMETRY = SITE_DIR / "geometry"
LISFLOOD = SITE_DIR / "lisflood"
FORMAT = "warsak-below-dam-acc-v1"
WARMUP_SECONDS = 72 * 3600
CHANNEL_MANNING_N = .035
# The project owner declined interpolating the sparse public readings (gaps up
# to 24 h). A record is accepted only when consecutive ordinates inside the
# event window are at most this far apart; the engine then interpolates
# linearly between them, as for any LISFLOOD boundary.
MAX_GAP_HOURS = 3
LIMITATIONS = [
    "Exploratory channel-conditioned LISFLOOD-FP ACC model of the Kabul below Warsak Dam; not calibrated or an operational forecast.",
    "The reservoir above the dam is not modelled. The only upstream boundary is the registered Warsak release, entered about 4 km below the dam.",
    "WorldCover water footprints and a monotone FABDEM water-surface profile define estimated channel geometry. Bed levels use rectangular Manning normal depths at the first release value; they are not surveyed.",
    "100 m terrain averaging, estimated bathymetry, assumed land-cover roughness, zero rainfall/infiltration and a free downstream boundary are explicit screening assumptions.",
    "Tributaries entering from the hills north and south of the reach receive no inflow; see the tributary audit of the published result.",
    "A 72-hour constant-flow numerical warm-up precedes the displayed period and is excluded from publication.",
    "No downstream gauge lies inside the window, so there are no discharge skill scores; no matched satellite flood extent is available.",
]


def _soil_url(prop):
    west, south, east, north = BOUNDS
    return (f"https://maps.isric.org/mapserv?map=/map/{prop}.map&SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage"
            f"&COVERAGEID={prop}_0-5cm_mean&FORMAT=image/tiff&SUBSET=Long({west},{east})&SUBSET=Lat({south},{north})"
            "&SUBSETTINGCRS=http://www.opengis.net/def/crs/EPSG/0/4326&OUTPUTCRS=http://www.opengis.net/def/crs/EPSG/0/4326")


def dem():
    output = BASE / "prepared" / "fabdem-warsak-30m.tif"
    tiles = [NOWSHERA_BASE / "raw" / "fabdem" / f"{name}_FABDEM_V1-2.tif" for name in ["N33E071", "N34E071"]]
    if any(not tile.is_file() for tile in tiles):
        raise ValueError("FABDEM tiles N33E071/N34E071 are missing; run python -m server.acquire fabdem first.")
    if not output.exists():
        save_mosaic(tiles, output, BOUNDS, nodata=-9999)
    return output, {"source": "https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/",
                    "license": "CC BY-NC-SA 4.0; commercial license separately",
                    "product": "FABDEM v1.2 ~30 m, Warsak clip"}


def landcover():
    output = BASE / "prepared" / "worldcover-2021-warsak-nearest-30m.tif"
    if not output.exists():
        save_mosaic([WORLDCOVER], output, BOUNDS, resolution=1 / 3600, dtype="uint8", nodata=0)
    return output, {"source": "https://esa-worldcover.org/en/data-access", "license": "CC BY 4.0",
                    "product": "ESA WorldCover 2021 v200; categorical nearest-neighbor ~30 m Warsak clip"}


def hydrography():
    # The upper-Kabul HydroRIVERS extract already spans Warsak (71.15-72.40 E).
    source = NOWSHERA_BASE / "prepared" / "hydrorivers-upper-kabul.geojson"
    if not source.is_file():
        raise ValueError("Run python -m server.acquire hydrography first; the upper-Kabul extract covers Warsak.")
    return source, {"source": "https://www.hydrosheds.org/products/hydrorivers",
                    "license": "HydroSHEDS license in its Technical Documentation; retain Lehner & Grill (2013) and WWF attribution",
                    "product": "HydroRIVERS v1.0, upper Kabul / Warsak / Nowshera"}


def catchment():
    import pyogrio
    output = BASE / "prepared" / "hydrobasins-warsak-candidate.geojson"
    layer = NOWSHERA_BASE / "raw" / "hydrobasins" / "hybas_as_lev08_v1c.shp"
    if not layer.is_file():
        raise ValueError("HydroBASINS level 8 is missing; run python -m server.acquire catchment first.")
    source = hydro_url(HYDRO_BASINS_PAGE, "hybas_as_lev01-12_v1c")
    if not output.exists():
        meta, _, geometry, fields = pyogrio.raw.read(layer, columns=["HYBAS_ID", "NEXT_DOWN", "SUB_AREA", "UP_AREA"])
        table = dict(zip(meta["fields"], fields))
        geoms = from_wkb(geometry)
        matches = [i for i, geom in enumerate(geoms) if geom.covers(Point(*OUTLET))]
        if not matches:
            raise ValueError("No HydroBASINS polygon contains the Warsak coordinate.")
        outlet_index = min(matches, key=lambda i: table["SUB_AREA"][i])
        upstream = {}
        for index, next_id in enumerate(table["NEXT_DOWN"]):
            upstream.setdefault(int(next_id), []).append(index)
        selected, queue = {outlet_index}, [outlet_index]
        while queue:
            for index in upstream.get(int(table["HYBAS_ID"][queue.pop()]), []):
                if index not in selected:
                    selected.add(index)
                    queue.append(index)
        properties = {"source": source, "hybas_id": int(table["HYBAS_ID"][outlet_index]), "level": 8,
                      "subbasin_count": len(selected),
                      "summed_subbasin_area_km2": float(sum(table["SUB_AREA"][i] for i in selected)),
                      "review_required": True, "outlet_exact": False,
                      "note": "Candidate union to the level-8 subbasin containing the Warsak gauge position; not exact dam delineation."}
        write_json(output, {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": properties, "geometry": mapping(union_all(geoms[list(selected)]))}]})
    return output, {"source": source,
                    "license": "HydroSHEDS license in its Technical Documentation; retain Lehner & Grill (2013) and WWF attribution",
                    "product": "HydroBASINS v1c level-8 candidate upstream union of Warsak — REVIEW REQUIRED"}


def soil():
    import rasterio
    output = BASE / "prepared" / "soilgrids-0-5cm-warsak.tif"
    if not output.exists():
        arrays, reference, profile = [], None, None
        for prop in SOIL_VARIABLES:
            path = download(_soil_url(prop), BASE / "raw" / "soil" / f"{prop}-0-5cm.tif", max_bytes=20_000_000)
            with rasterio.open(path) as src:
                grid = (src.crs, src.transform, src.width, src.height)
                if reference is not None and grid != reference:
                    raise ValueError("SoilGrids property grids differ; alignment needs review.")
                reference, profile = grid, src.profile.copy()
                arrays.append(src.read(1))
        output.parent.mkdir(parents=True, exist_ok=True)
        profile.update(driver="GTiff", count=len(arrays), compress="deflate")
        with rasterio.open(output, "w", **profile) as dst:
            dst.write(np.stack(arrays))
            for index, prop in enumerate(SOIL_VARIABLES, 1):
                dst.set_band_description(index, f"{prop}_0-5cm_mean / native SoilGrids units")
    return output, {"source": "https://isric.org/explore/soilgrids/", "license": "CC BY 4.0; retain ISRIC attribution",
                    "product": "SoilGrids 2.0, raw sand/clay/SOC/bulk-density, 0–5 cm, Warsak clip"}


TASKS = {"dem": dem, "landcover": landcover, "hydrography": hydrography, "catchment": catchment, "soil": soil}


def acquire(kinds=None):
    """Download or clip each input and register it in the Warsak catalog only."""
    records = {}
    for kind in kinds or TASKS:
        path, meta = TASKS[kind]()
        record = register(kind, path, meta["source"], meta["license"], meta["product"], site=SITE)
        if path.suffix == ".tif":
            record["check"] = {k: v for k, v in raster_record(path).items() if k in {"crs", "bounds", "valid_fraction"}}
        records[kind] = record
    return records


def scenario(inflow_sha256=None, engine="LISFLOOD-FP"):
    """The Warsak below-dam case. Its window is the app's 20 km Warsak window."""
    from .models import Scenario
    values = json.loads((Path(__file__).resolve().parents[1] / "examples" / "nowshera-2022.json").read_text(encoding="utf-8"))
    lon, lat = OUTLET
    values.update(id="warsak-below-dam-2022", name="Warsak · Kabul below the dam (2022)")
    values["outlet"] = {"station_id": SITE, "lat": lat, "lon": lon, "crs": "EPSG:4326"}
    values["domain"].update(radius_km=RADIUS_KM, mesh_m=MESH_M, dem_sha256=checked_asset("dem", SITE)[0]["sha256"])
    values["time"].update(start="2022-08-20T01:00:00Z", end="2022-09-05T01:00:00Z", output_interval_minutes=60)
    values["forcing"].update(mode="inflow_hydrograph", rainfall_product="CHIRPS", soil_moisture="normal",
        upstream_station_ids=[SITE], inflow_asset=inflow_sha256,
        bias_correction="Gauge-driven: the Warsak Dam release is the only upstream boundary. Rainfall, infiltration and soil moisture are unused.")
    values["hydraulics"].update(engine=engine, equations="local inertial" if engine == "LISFLOOD-FP" else "full SWE",
                                manning_source="ESA WorldCover")
    values["validation"].update(gauge_ids=[])
    values["provenance"].update(created_at="2026-11-04T00:00:00Z",
        purpose="Exploratory below-dam Kabul River case at Warsak; uncalibrated and unvalidated.",
        notes="The reservoir above the dam is not modelled: its inflow from Afghanistan and the dam's gate operations are unavailable. "
              "The model starts about 4 km below the dam and is forced only by the Warsak release. No downstream gauge lies inside the window, "
              "so there are no discharge skill scores.",
        sources=["https://ffd.pmd.gov.pk/flood-limits", "https://data.bris.ac.uk/data/dataset/s5hqmjcdj8yo2ibzi9b4ew3sn",
                 "https://esa-worldcover.org/en/data-access", "https://www.hydrosheds.org/"])
    return Scenario.model_validate(values)


def _grid(s):
    crs = s.domain.model_crs
    forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    center_x, center_y = forward(s.outlet.lon, s.outlet.lat)
    half = s.domain.radius_km * 1000 - EDGE_MARGIN_M
    west_x, _ = forward(MODEL_WEST_LON, s.outlet.lat)
    west = math.ceil(west_x / GRID_ALIGNMENT_M) * GRID_ALIGNMENT_M
    east = math.floor((center_x + half) / GRID_ALIGNMENT_M) * GRID_ALIGNMENT_M
    bottom = math.ceil((center_y - half) / GRID_ALIGNMENT_M) * GRID_ALIGNMENT_M
    top = math.floor((center_y + half) / GRID_ALIGNMENT_M) * GRID_ALIGNMENT_M
    dims = (round((top - bottom) / MESH_M), round((east - west) / MESH_M))
    return crs, forward, (west, bottom, east, top), from_origin(west, top, MESH_M, MESH_M), dims


def _crossings(forward, bounds):
    west, bottom, east, top = bounds
    area = box(west, bottom, east, top)
    points = []
    for feature in read_json(checked_asset("hydrography", SITE)[1])["features"]:
        if feature["properties"].get("UPLAND_SKM", 0) < MAJOR_UPLAND_KM2:
            continue
        hit = transform(forward, shape(feature["geometry"])).intersection(area.boundary)
        points += list(hit.geoms) if hit.geom_type == "MultiPoint" else [hit] if hit.geom_type == "Point" else []
    western = [p for p in points if abs(p.x - west) < .01]
    eastern = [p for p in points if abs(p.x - east) < .01]
    other = [p for p in points if p not in western and p not in eastern]
    if len(western) != 1 or len(eastern) != 1 or other:
        raise ValueError(f"Expected one major-channel entry on the west edge and one exit on the east edge; "
                         f"found {len(western)} west, {len(eastern)} east, {len(other)} elsewhere.")
    return western[0], eastern[0]


def prepare_geometry():
    """Domain clip, computational grid, mapped-water corridor and boundaries. No inflow used."""
    from .channel import channel_profile, water_sources
    from .domain import prepare_domain
    from .screening import MANNING, _tiff, _warp
    from .store import scenario_hash
    s = scenario()
    domain = prepare_domain(s)
    crs, forward, bounds, affine, dims = _grid(s)
    west, bottom, east, top = bounds
    native = ROOT / "domains" / scenario_hash(s)
    dem_values = np.round(_warp(native / "dem.tif", dims, affine, crs, Resampling.average), 3)
    cover = _warp(native / "landcover.tif", dims, affine, crs, Resampling.mode).astype("int16")
    unknown = set(np.unique(cover)) - MANNING.keys()
    if unknown:
        raise ValueError(f"Unmapped land-cover classes: {sorted(unknown)}")
    roughness = np.array([MANNING[int(v)] for v in cover.ravel()], dtype="float32").reshape(dims)
    fraction, surface = water_sources(native / "dem.tif", native / "landcover.tif", dims, affine, crs)
    profile = channel_profile(dem_values, fraction, surface, affine)
    corridor = profile["corridor"]
    entry, exit_ = _crossings(forward, bounds)
    target_row = round((top - entry.y) / MESH_M - .5)
    candidates = [row for row in range(dims[0]) if abs(row - target_row) * MESH_M < 1500 and corridor[row, 0]]
    if not candidates:
        raise ValueError("No mapped-water corridor cell near the HydroRIVERS entry on the west edge.")
    row = min(candidates, key=lambda r: abs(r - target_row))
    low = high = row
    while low > 0 and corridor[low - 1, 0]:
        low -= 1
    while high + 1 < dims[0] and corridor[high + 1, 0]:
        high += 1
    inlet = {"side": "W", "y_low": top - (high + 1) * MESH_M, "y_high": top - low * MESH_M,
             "width_m": (high - low + 1) * MESH_M, "rows": [low, high],
             "hydrorivers_entry": list(entry.coords)[0], "hydrorivers_exit": list(exit_.coords)[0]}
    GEOMETRY.mkdir(parents=True, exist_ok=True)
    _tiff(GEOMETRY / "unconditioned-terrain.tif", dem_values, affine, crs, "m EGM2008")
    _tiff(GEOMETRY / "channel-water-fraction.tif", fraction, affine, crs, "fraction")
    _tiff(GEOMETRY / "channel-mask.tif", corridor.astype("float32"), affine, crs, "boolean")
    _tiff(GEOMETRY / "floodplain-roughness.tif", roughness, affine, crs, "Manning n before channel assignment")
    np.save(GEOMETRY / "water-surface-reference.npy", surface)
    widths, levels = profile["widths"], profile["levels"]
    summary = {
        "grid": {"crs": crs, "cell_m": MESH_M, "shape": list(dims), "bounds": list(bounds),
                 "west_edge_lon": MODEL_WEST_LON, "area_km2": dims[0] * dims[1] * MESH_M ** 2 / 1e6},
        "corridor": {"cells": int(corridor.sum()), "length_m": float(profile["chainage"][-1]),
                     "width_range_m": [float(widths.min()), float(widths.max())],
                     "reference_surface_m": [float(levels[0]), float(levels[-1])], "slope": profile["slope"]},
        "inlet": inlet,
        "downstream": {"side": "E", "type": "FREE", "slope": profile["slope"],
                       "method": "monotone mapped-water surface drop divided by centerline distance; assumption, not surveyed normal slope"},
    }
    record = {
        "summary": summary,
        "scenario_sha256_without_inflow": scenario_hash(s),
        "domain": {"snapped_outlet": domain["snapped_outlet"], "catchment_status": domain["catchment_status"]},
        "inputs": {kind: checked_asset(kind, SITE)[0]["sha256"] for kind in REQUIRED},
        "files": {path.name: file_hash(path) for path in sorted(GEOMETRY.glob("*")) if path.suffix in {".tif", ".npy"}},
        "profile": [{"chainage_m": float(c), "width_m": float(w), "reference_surface_m": float(z)}
                    for c, w, z in zip(profile["centers"], widths, levels)],
        "centerline_grid_rows_columns": profile["path_rc"].tolist(),
        "roughness": {str(k): v for k, v in MANNING.items()},
        "awaiting": "Warsak Dam release record. Bed lowering uses Manning normal depth at its first value, "
                    "so the channel is conditioned only once that record is registered.",
    }
    write_json(GEOMETRY / "geometry.json", record)
    (GEOMETRY / "REVIEW.md").write_text(
        "# Warsak below-dam geometry: preparation review\n\n"
        "Exploratory and uncalibrated. Nothing here computes water.\n\n"
        f"- Grid: {dims[1]} x {dims[0]} cells at {MESH_M} m in {crs}, from {MODEL_WEST_LON} E (about 4 km below Warsak Dam) "
        "to the east edge of the app's 20 km Warsak window, over its full north-south extent.\n"
        "- The reservoir above the dam is not modelled (no inflow from Afghanistan, no gate operations).\n"
        f"- Mapped water: WorldCover >= {WATER_FRACTION:.0%} water fraction; one connected west-to-east corridor of "
        f"{int(corridor.sum())} cells, about {profile['chainage'][-1] / 1000:.1f} km along its centerline.\n"
        f"- Upstream boundary: the corridor cells on the west edge nearest the HydroRIVERS entry, {inlet['width_m']:.0f} m wide.\n"
        f"- Downstream boundary: free outflow at the mapped-water surface slope, {profile['slope']:.7f}.\n"
        "- Not yet done: bed lowering (needs the first release value), boundary file, engine project and binding.\n",
        encoding="utf-8")
    return record


def release_series():
    """The registered Warsak release, checked for coverage and gaps. Never filled in."""
    asset, path = checked_asset("inflow", SITE)
    s = scenario()
    start, end = s.time.start, s.time.end
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row["station_id"] == SITE]
    if not rows:
        raise ValueError("The registered inflow has no rows for station_id 'warsak'.")
    series = sorted((datetime.fromisoformat(row["time"].replace("Z", "+00:00")), float(row["discharge_m3s"]), row["value_type"])
                    for row in rows)
    times = [item[0] for item in series]
    if times[0] > start or times[-1] < end:
        raise ValueError(f"The Warsak release must cover {start.isoformat()} to {end.isoformat()}; it covers {times[0].isoformat()} to {times[-1].isoformat()}.")
    first = max(i for i, t in enumerate(times) if t <= start)
    last = min(i for i, t in enumerate(times) if t >= end)
    window = series[first:last + 1]
    gaps = [(b[0] - a[0]).total_seconds() / 3600 for a, b in zip(window, window[1:])]
    if gaps and max(gaps) > MAX_GAP_HOURS:
        worst = max(range(len(gaps)), key=gaps.__getitem__)
        raise ValueError(f"The Warsak release has a {gaps[worst]:.1f} h gap after {window[worst][0].isoformat()}; "
                         f"at most {MAX_GAP_HOURS} h is accepted. Sparse readings are not interpolated into a boundary.")
    return [item[0] for item in window], np.array([item[1] for item in window]), asset


def _checked_geometry():
    geometry = read_json(GEOMETRY / "geometry.json")
    if not geometry:
        raise ValueError("Prepare the Warsak geometry first: python -m server.warsak geometry")
    current = {kind: checked_asset(kind, SITE)[0]["sha256"] for kind in REQUIRED}
    if geometry["inputs"] != current or any(file_hash(GEOMETRY / name) != digest for name, digest in geometry["files"].items()):
        raise ValueError("Warsak inputs or geometry files changed; prepare the geometry again.")
    return geometry, current


def _write_project(project, s, times, flows, geometry, sim_seconds=None, conditioning_m3s=None,
                   floodplain_multiplier=1.0, channel_n=CHANNEL_MANNING_N, velocity=False):
    """Condition the channel and write the engine inputs.

    The bed is conditioned at `conditioning_m3s` (default: the first release
    value). Snapshot runs pass one fixed reference flow so every calibration
    and validation run shares identical terrain.
    """
    from .channel import condition_channel
    from .screening import _ascii, _tiff, gauge_sections
    import rasterio
    crs, _, bounds, affine, dims = _grid(s)
    west, bottom, east, top = bounds
    with rasterio.open(GEOMETRY / "unconditioned-terrain.tif") as src:
        raw_dem = src.read(1)  # float32, as prepared; rounding must reproduce it exactly
    with rasterio.open(GEOMETRY / "channel-water-fraction.tif") as src:
        fraction = src.read(1)
    with rasterio.open(GEOMETRY / "floodplain-roughness.tif") as src:
        roughness = src.read(1)
    surface = np.load(GEOMETRY / "water-surface-reference.npy")
    baseflow = float(flows[0])
    dem, water, centerline, channel = condition_channel(raw_dem.copy(), fraction, surface, affine,
                                                        float(conditioning_m3s or baseflow))
    with rasterio.open(GEOMETRY / "channel-mask.tif") as src:
        if not np.array_equal(src.read(1) > 0, water):
            raise ValueError("The conditioned corridor differs from the prepared geometry.")
    roughness = roughness * float(floodplain_multiplier)
    roughness[water] = float(channel_n)
    inlet = geometry["summary"]["inlet"]
    slope = geometry["summary"]["downstream"]["slope"]
    project.mkdir(parents=True, exist_ok=True)
    _tiff(project / "unconditioned-terrain.tif", raw_dem, affine, crs, "m EGM2008")
    _tiff(project / "channel-mask.tif", water.astype("float32"), affine, crs, "boolean")
    _tiff(project / "channel-lowering.tif", raw_dem - dem, affine, crs, "m estimated bed correction")
    _tiff(project / "computational-terrain.tif", dem, affine, crs, "m EGM2008")
    write_json(project / "channel-geometry.json", {**channel, "centerline_grid_rows_columns": centerline.tolist()})
    _ascii(project / "terrain.asc", dem, affine)
    _ascii(project / "roughness.asc", roughness, affine)
    (project / "terrain.prj").write_text(rasterio.crs.CRS.from_string(crs).to_wkt(), encoding="utf-8")
    (project / "boundaries.bci").write_text(
        f"W {inlet['y_low']:.3f} {inlet['y_high']:.3f} QVAR release\nE {bottom:.3f} {top:.3f} FREE {slope:.9f}\n", encoding="ascii")
    width = inlet["width_m"]
    start = s.time.start
    with (project / "inflow.bdy").open("w", encoding="ascii", newline="\n") as stream:
        # Floodplain QVAR is discharge per unit width (m2/s), not total m3/s.
        stream.write(f"Warsak release divided by {width:.3f} m inlet width; constant-flow warm-up first\nrelease\n{len(times) + 1} seconds\n")
        stream.write(f"{baseflow / width:.12f} 0.000\n")
        for time, discharge in zip(times, flows):
            stream.write(f"{discharge / width:.12f} {WARMUP_SECONDS + (time - start).total_seconds():.3f}\n")
    gauge_col = dims[1] - 3
    gauge_sections(project / "warsak.gauge", west + (gauge_col + .5) * MESH_M, top, dims[0], MESH_M)
    duration = sim_seconds or WARMUP_SECONDS + (s.time.end - start).total_seconds()
    (project / "screen.par").write_text(
        f"DEMfile terrain.asc\nmanningfile roughness.asc\nresroot warsak\ndirroot output\nsim_time {duration:.3f}\ninitial_tstep 20\n"
        "massint 3600\nsaveint 3600\nacceleration\nbcifile boundaries.bci\nbdyfile inflow.bdy\ngaugefile warsak.gauge\n"
        + ("voutput\n" if velocity else ""), encoding="ascii")
    return {"crs": crs, "bounds": bounds, "dims": dims, "channel": channel, "centerline": centerline, "water": water,
            "baseflow": baseflow, "width": width, "gauge_col": gauge_col}


def build_lisflood():
    """Condition the channel, write and bind the LISFLOOD project. Requires a registered release."""
    from .domain import prepare_domain
    from .store import scenario_hash
    from .worker import bind, preflight, runtimes
    times, flows, inflow = release_series()
    s = scenario(inflow_sha256=inflow["sha256"])
    geometry, current = _checked_geometry()
    engine = Path(runtimes()["lisflood_fp_exe"])
    if not engine.is_file():
        raise ValueError("LISFLOOD-FP is not installed/configured.")
    domain = prepare_domain(s)
    fingerprint = hashlib.sha256(json.dumps({"format": FORMAT, "inputs": current, "inflow": inflow["sha256"],
        "geometry": geometry["files"], "engine": file_hash(engine)}, sort_keys=True).encode()).hexdigest()
    project = LISFLOOD / fingerprint[:12] / "project"
    written = _write_project(project, s, times, flows, geometry)
    west = written["bounds"][0]
    config = {"format": FORMAT, "site": SITE, "resroot": "warsak", "scenario_sha256": scenario_hash(s),
        "source_terrain_sha256": domain["clips"]["dem"]["sha256"], "computational_terrain_sha256": file_hash(project / "computational-terrain.tif"),
        "inflow_asset_sha256": inflow["sha256"], "warmup_seconds": WARMUP_SECONDS, "baseflow_m3s": written["baseflow"],
        "channel_geometry": written["channel"], "channel_geometry_sha256": file_hash(project / "channel-geometry.json"),
        "channel_mask_sha256": file_hash(project / "channel-mask.tif"), "engine_sha256": file_hash(engine),
        "grid": {"crs": written["crs"], "shape": list(written["dims"]), "cell_m": MESH_M, "bounds": list(written["bounds"])},
        "upstream": {**geometry["summary"]["inlet"], "station_id": SITE, "units_in_bdy": "m2/s", "max_gap_hours": MAX_GAP_HOURS},
        "downstream": geometry["summary"]["downstream"],
        "gauge": {"station_id": "warsak-east-edge", "easting": west + (written["gauge_col"] + 1) * MESH_M, "segments": written["dims"][0],
                  "method": "sum of signed eastward one-cell section outputs across every grid row near the east edge; modelled outflow, not a gauge"},
        "gauge_comparison": "Modelled outflow near the east edge only; no downstream observations exist inside the window, so no skill scores.",
        "validation_status": "Exploratory below-dam screening; uncalibrated, no downstream gauge or flood-extent validation",
        "roughness": geometry["roughness"], "channel_manning_n": CHANNEL_MANNING_N, "limitations": LIMITATIONS, "massint_seconds": 3600}
    write_json(project / "warsak-screening.json", config)
    (project / "REVIEW.md").write_text("# Warsak below-dam LISFLOOD-FP case: preparation review\n\n" + "\n\n".join(LIMITATIONS)
        + f"\n\nRelease: {len(times)} ordinates, at most {MAX_GAP_HOURS} h apart, divided by the {written['width']:.0f} m inlet width. "
        "The engine interpolates linearly between ordinates. This is a preparation review, not independent expert validation.\n", encoding="utf-8")
    write_json(project.parent / "scenario.json", s.model_dump(mode="json"))
    bind(s, project, "screen.par", str(project / "REVIEW.md"))
    check = preflight(s)
    case = {"fingerprint": fingerprint, "label": "Runnable · Warsak below-dam screening", "scenario": s.model_dump(mode="json"),
            "project": str(project), "limitations": LIMITATIONS, "ready": check["ready"]}
    if not case["ready"]:
        raise ValueError(f"Prepared Warsak case failed preflight: {[c for c in check['checks'] if not c['passed']]}")
    write_json(LISFLOOD / "case.json", case)
    return case


def smoke(discharge_m3s, hours_after_warmup=6):
    """Numerical check of the real geometry with a constant TEST flow. Never bound or published.

    Runs the 72-hour warm-up plus a few hours in a scratch folder and reports
    whether the river wets, connects and settles. The test flow is an input to
    a numerical check only; it is not a 2022 release and produces no result.
    """
    import os
    import subprocess
    from uuid import uuid4
    from .channel import warmup_review
    from .worker import runtimes
    geometry, _ = _checked_geometry()
    s = scenario()
    folder = SITE_DIR / "smoke" / uuid4().hex[:8]
    times = [s.time.start, s.time.start + timedelta(hours=hours_after_warmup)]
    flows = np.array([float(discharge_m3s)] * 2)
    total = WARMUP_SECONDS + hours_after_warmup * 3600
    written = _write_project(folder, s, times, flows, geometry, sim_seconds=total)
    (folder / "SMOKE-TEST-ONLY.txt").write_text(
        f"Numerical smoke test with a constant test flow of {discharge_m3s} m3/s. Not a 2022 release, not bound, never published.\n",
        encoding="utf-8")
    with (folder / "engine.log").open("w") as log:
        run = subprocess.run([runtimes()["lisflood_fp_exe"], "screen.par"], cwd=folder, env={**os.environ, "OMP_NUM_THREADS": "2"},
                             stdout=log, stderr=subprocess.STDOUT, timeout=3600)
    if run.returncode:
        raise RuntimeError(f"LISFLOOD-FP exited with {run.returncode}; see {folder / 'engine.log'}")
    mass = np.loadtxt(folder / "output" / "warsak.mass", skiprows=1, ndmin=2)
    sections = np.loadtxt(folder / "output" / "warsak.discharge", skiprows=3, ndmin=2)
    first_index = int(np.flatnonzero(mass[:, 0] >= WARMUP_SECONDS)[0])
    depth = np.loadtxt(sorted((folder / "output").glob("warsak-*.wd"))[first_index], skiprows=6, ndmin=2)
    try:
        review = warmup_review(mass, sections, depth, written["water"], written["centerline"], WARMUP_SECONDS, float(discharge_m3s))
    except ValueError as exc:
        review = {"passed": False, "detail": str(exc)}
    result = {"folder": str(folder), "test_flow_m3s": float(discharge_m3s), "completed_seconds": float(mass[-1, 0]),
              "requested_seconds": total, "relative_mass_error": float(abs(mass[:, 10]).sum() / max(float(np.trapezoid(mass[:, 6], mass[:, 0])), 1)),
              "maximum_depth_m": float(depth.max()), "wet_area_km2_at_5cm": float((depth > .05).sum() * MESH_M ** 2 / 1e6),
              "warmup_review": review, "note": "Numerical smoke test only; not a result."}
    write_json(folder / "smoke-review.json", result)
    return result


def prepared_cases():
    case = read_json(LISFLOOD / "case.json")
    return [case] if case and case.get("ready") else []


def cached_result(s):
    from .screening import cached_result as screening_cached
    return screening_cached(s)


def finish_and_publish(s, project):
    from .screening import finish_and_publish as publish_screening
    return publish_screening(s, project, marker="warsak-screening.json", fmt=FORMAT)


def status():
    """What is ready for the Warsak model, and what is still missing."""
    catalog = assets(SITE)
    inputs = {}
    for kind in REQUIRED + ["inflow"]:
        try:
            asset, _ = checked_asset(kind, SITE)
            inputs[kind] = {"ready": True, "product": asset["product"], "sha256": asset["sha256"]}
        except ValueError as exc:
            inputs[kind] = {"ready": False, "detail": str(exc)}
    geometry = read_json(SITE_DIR / "geometry" / "geometry.json")
    return {
        "site": SITE,
        "inputs": inputs,
        "geometry": {"ready": bool(geometry) and geometry.get("inputs") == {k: v.get("sha256") for k, v in inputs.items() if k in REQUIRED},
                     **({"summary": geometry["summary"]} if geometry else {})},
        "inflow_needed": {
            "station_id": SITE,
            "what": "Warsak Dam release (Kabul River at Warsak), timestamped, in m³/s, covering 2022-08-20T01:00Z to 2022-09-05T01:00Z",
            "format": "CSV with columns time (ISO 8601 with timezone), station_id, discharge_m3s, source, value_type (observed or modeled)",
            "register": "python -m server.cli register inflow <file.csv> --site warsak --source <...> --license <...> --product <...>",
            "max_gap_hours": MAX_GAP_HOURS,
            "then": "python -m server.warsak build",
        },
        "ready_to_build_lisflood": all(item["ready"] for item in inputs.values()) and bool(geometry),
        "lisflood_case": bool(prepared_cases()),
        "hec_ras": "Not prepared yet: the mesh and boundary lines are built after the LISFLOOD case runs.",
        "catalog_keys": sorted(catalog),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    get = sub.add_parser("acquire", help="Download/clip Warsak inputs into the Warsak catalog")
    get.add_argument("kinds", nargs="*", help=", ".join(TASKS) + " (default: all)")
    sub.add_parser("geometry", help="Prepare the domain, grid and mapped-water corridor (no inflow used)")
    sub.add_parser("build", help="Build and bind the LISFLOOD case once a Warsak release is registered")
    test = sub.add_parser("smoke", help="Numerical check of the geometry with a constant TEST flow (never published)")
    test.add_argument("discharge_m3s", type=float)
    sub.add_parser("status", help="Report what is ready and what is still missing")
    args = parser.parse_args()
    if args.command == "acquire":
        unknown = [kind for kind in args.kinds if kind not in TASKS]
        if unknown:
            parser.error(f"Unknown inputs {unknown}; choose from {sorted(TASKS)}")
        result = acquire(args.kinds or None)
    elif args.command == "geometry":
        result = prepare_geometry()
        result = {key: result[key] for key in ["summary", "domain", "awaiting"]}
    elif args.command == "smoke":
        result = smoke(args.discharge_m3s)
    elif args.command == "build":
        result = {key: value for key, value in build_lisflood().items() if key != "scenario"}
    else:
        result = status()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
