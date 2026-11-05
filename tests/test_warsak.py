"""Synthetic fixture for the Warsak site plumbing; never shipped as model output.

A small west-to-east valley with one mapped river stands in for Warsak, so the
whole preparation path (site catalog, domain, corridor, project, binding,
preflight) runs without the real inputs or a dam-release record.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from server import cli, domain, engines, store, warsak, worker
from server.store import write_json

LON, LAT = 71.0, 34.0
STEP = 1 / 3600  # ~30 m, like FABDEM


@pytest.fixture
def site(tmp_path, monkeypatch):
    for module in [store, cli, domain, worker, warsak]:
        monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(warsak, "SITE_DIR", tmp_path / "sites" / "warsak")
    monkeypatch.setattr(warsak, "GEOMETRY", tmp_path / "sites" / "warsak" / "geometry")
    monkeypatch.setattr(warsak, "LISFLOOD", tmp_path / "sites" / "warsak" / "lisflood")
    monkeypatch.setattr(warsak, "OUTLET", (LON, LAT))
    monkeypatch.setattr(warsak, "RADIUS_KM", 3)
    monkeypatch.setattr(warsak, "MODEL_WEST_LON", LON + .005)
    engine = tmp_path / "tools" / "lisflood.exe"
    engine.parent.mkdir(parents=True)
    engine.write_bytes(b"synthetic engine stand-in")
    monkeypatch.setenv("LISFLOOD_FP_EXE", str(engine))
    inputs = tmp_path / "inputs"
    inputs.mkdir()

    half = .06
    width = height = round(2 * half / STEP)
    transform = from_origin(LON - half, LAT + half, STEP, STEP)
    lats = LAT + half - (np.arange(height) + .5) * STEP
    lons = LON - half + (np.arange(width) + .5) * STEP
    river = np.abs(lats - LAT) < .0015  # ~330 m wide mapped water band
    # Ground falls 2 m/km eastward; the river sits 3 m below its banks.
    east_km = (lons - lons[0]) * 92.4
    elevation = 340 - 2 * east_km[None, :] + 6 * np.abs(lats - LAT)[:, None] / half
    elevation = elevation - 3 * river[:, None]
    cover = np.where(river[:, None], 80, 40) * np.ones((1, width))

    def raster(name, values, dtype, nodata):
        path = inputs / name
        with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1, dtype=dtype,
                           crs="EPSG:4326", transform=transform, nodata=nodata) as dst:
            dst.write(values.astype(dtype), 1)
        return path

    line = {"type": "LineString", "coordinates": [[LON - half, LAT], [LON + half, LAT]]}
    write_json(inputs / "rivers.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"UPLAND_SKM": 69000, "HYRIV_ID": 1, "NEXT_DOWN": 0}, "geometry": line}]})
    write_json(inputs / "basin.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [[
            [LON - 1, LAT - 1], [LON + 1, LAT - 1], [LON + 1, LAT + 1], [LON - 1, LAT + 1], [LON - 1, LAT - 1]]]}}]})
    for kind, path in [("dem", raster("dem.tif", elevation, "float32", -9999)),
                       ("landcover", raster("cover.tif", cover, "uint8", 0)),
                       ("soil", raster("soil.tif", np.full((height, width), 30), "int16", -1)),
                       ("hydrography", inputs / "rivers.geojson"), ("catchment", inputs / "basin.geojson")]:
        cli.register(kind, path, "synthetic test fixture", "test only", f"synthetic {kind}", site="warsak")
    return tmp_path


def release_csv(path, hours_apart):
    start = datetime(2022, 8, 20, 1, tzinfo=timezone.utc)
    rows = ["time,station_id,discharge_m3s,source,value_type"]
    time, index = start - timedelta(hours=hours_apart), 0
    while time <= start + timedelta(days=16, hours=hours_apart):
        rows.append(f"{time.isoformat()},warsak,{1100 + 5 * index},synthetic test fixture,observed")
        time += timedelta(hours=hours_apart)
        index += 1
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_warsak_site_prepares_without_inflow_and_leaves_nowshera_untouched(site):
    record = warsak.prepare_geometry()
    summary = record["summary"]
    assert summary["corridor"]["cells"] > 0 and summary["corridor"]["slope"] > 0
    assert summary["inlet"]["side"] == "W" and summary["inlet"]["width_m"] >= 300
    assert record["awaiting"].startswith("Warsak Dam release record")
    status = warsak.status()
    assert status["geometry"]["ready"] and not status["inputs"]["inflow"]["ready"]
    assert not status["ready_to_build_lisflood"]
    # The Warsak catalog is separate; Nowshera's original catalog was never written.
    assert not (site / "assets.json").exists()
    with pytest.raises(ValueError, match="Missing inflow asset for warsak"):
        warsak.build_lisflood()


def test_warsak_build_binds_a_runnable_case_from_a_dense_release(site, tmp_path):
    warsak.prepare_geometry()
    cli.register("inflow", release_csv(tmp_path / "release.csv", 1), "synthetic test fixture", "test only",
                 "synthetic hourly release", site="warsak")
    case = warsak.build_lisflood()
    assert case["ready"]
    s = warsak.scenario(inflow_sha256=store.assets("warsak")["inflow"]["sha256"])
    project = warsak.LISFLOOD / case["fingerprint"][:12] / "project"
    assert engines.public_case("LISFLOOD-FP", project).module_name == "warsak"
    assert worker.preflight(s)["ready"]
    bci = (project / "boundaries.bci").read_text()
    assert bci.startswith("W ") and " QVAR release" in bci and "\nE " in bci
    bdy = (project / "inflow.bdy").read_text().splitlines()
    assert bdy[1] == "release" and int(bdy[2].split()[0]) == len(bdy) - 3
    assert warsak.prepared_cases()[0]["label"] == "Runnable · Warsak below-dam screening"


def test_warsak_refuses_sparse_releases(site, tmp_path):
    warsak.prepare_geometry()
    cli.register("inflow", release_csv(tmp_path / "sparse.csv", 24), "synthetic test fixture", "test only",
                 "synthetic daily release", site="warsak")
    with pytest.raises(ValueError, match="24.0 h gap"):
        warsak.build_lisflood()
