"""Synthetic fixtures exercise plumbing only; never shipped as Nowshera flood output."""
import json
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from fastapi.testclient import TestClient
from pydantic import ValidationError
from server.models import Scenario
from server.metrics import extent_metrics, gauge_metrics, read_hydrographs
from server.store import file_hash, scenario_hash, write_json
from server import store, domain, publish, worker, cli
import importlib


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for module in [store, domain, publish, worker, cli]:
        monkeypatch.setattr(module, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def scenario():
    s = Scenario.model_validate_json(Path("examples/nowshera-2022.json").read_text())
    s.domain.radius_km = 1
    s.forcing.bias_correction = "Gauge-driven run; rainfall unused. Synthetic test only."
    s.forcing.soil_moisture = "normal"
    return s


def raster(path, values=None, left=71.9, top=34.1, size=100):
    values = np.ones((size, size), dtype="float32") if values is None else np.asarray(values, dtype="float32")
    with rasterio.open(path, "w", driver="GTiff", width=values.shape[1], height=values.shape[0], count=1, dtype="float32", crs="EPSG:4326", transform=from_origin(left, top, 0.002, 0.002), nodata=-9999) as dst:
        dst.write(values, 1)
    return path


def seed(root, scenario):
    for kind in ["dem", "soil", "landcover"]:
        path = raster(root / f"{kind}.tif")
        cli.register(kind, path, "Synthetic test fixture", "test only", kind)
    line = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": [[71.9, 34.0095], [72.1, 34.0095]]}}]}
    basin = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [[[71.8, 33.8], [72.2, 33.8], [72.2, 34.2], [71.8, 34.2], [71.8, 33.8]]]}}]}
    for kind, data in [("hydrography", line), ("catchment", basin)]:
        path = root / f"{kind}.geojson"
        write_json(path, data)
        cli.register(kind, path, "Synthetic test fixture", "test only", kind)
    inflow = root / "inflow.csv"
    inflow.write_text("time,station_id,discharge_m3s,source,value_type\n2022-08-20T00:00:00Z,warsak,100,test,observed\n2022-09-05T00:00:00Z,warsak,200,test,observed\n")
    cli.register("inflow", inflow, "Synthetic test fixture", "test only", "boundary")
    scenario.domain.dem_sha256 = store.assets()["dem"]["sha256"]
    return scenario


def test_scenario_rejects_custom_physics(scenario):
    raw = scenario.model_dump(mode="json")
    raw["hydraulics"]["engine"] = "geometric-screening"
    with pytest.raises(ValidationError):
        Scenario.model_validate(raw)


@pytest.mark.parametrize("field,value", [("radius_km", 1000), ("mesh_m", -1), ("radius_km", float("nan"))])
def test_invalid_domain_rejected(scenario, field, value):
    raw = scenario.model_dump(mode="json")
    raw["domain"][field] = value
    with pytest.raises(ValidationError):
        Scenario.model_validate(raw)


def test_naive_and_reversed_times_rejected(scenario):
    raw = scenario.model_dump(mode="json")
    raw["time"]["start"] = "2022-08-20"
    with pytest.raises(ValidationError):
        Scenario.model_validate(raw)
    raw["time"]["start"] = "2023-08-20T00:00:00Z"
    with pytest.raises(ValidationError):
        Scenario.model_validate(raw)


def test_metrics_reference_and_undefined():
    assert gauge_metrics([1, 2, 3], [1, 2, 3])["nse"] == 1
    assert gauge_metrics([1, 2, 3], [1, 2, 3])["kge"] == 1
    assert gauge_metrics([1, 1, 1], [1, 1, 1])["nse"] is None
    assert gauge_metrics([1, np.nan], [1, 2])["kge"] is None
    result = extent_metrics([1, 1, 0], [1, 0, 1])
    assert result["csi"] == pytest.approx(1 / 3)
    assert result["pod"] == 0.5
    assert result["far"] == 0.5


def test_duplicate_gauges_rejected(isolated):
    p = isolated / "gauges.csv"
    p.write_text("time,station_id,observed_m3s,simulated_m3s\n2022-08-20T00:00:00Z,nowshera,1,1\n2022-08-20T00:00:00+00:00,nowshera,2,2\n")
    with pytest.raises(ValueError, match="Duplicate"):
        read_hydrographs(p)


def test_domain_snap_clip_and_hash_invalidation(isolated, scenario):
    s = seed(isolated, scenario)
    result = domain.prepare_domain(s)
    assert result["snapped_outlet"]["distance_m"] < 10
    assert result["clips"]["dem"]["width"] < 100
    assert result["catchment"]["type"] == "FeatureCollection"
    clipped = isolated / "domains" / scenario_hash(s) / "dem.tif"
    assert file_hash(clipped) == result["clips"]["dem"]["sha256"]
    # Changing a non-DEM input invalidates the clip cache.
    new_soil = raster(isolated / "changed-soil.tif", values=np.full((100, 100), 2))
    cli.register("soil", new_soil, "Changed test fixture", "test only", "soil")
    next_result = domain.prepare_domain(s)
    assert next_result["clips"]["soil"]["sha256"] != result["clips"]["soil"]["sha256"]


def test_missing_inputs_block_compute(isolated, scenario):
    check = worker.preflight(scenario)
    assert not check["ready"]
    assert not next(c for c in check["checks"] if c["key"] == "prepared_model")["passed"]


def test_other_station_blocked_even_with_installed_runtime(isolated, scenario):
    scenario.outlet.station_id = "tarbela"
    assert not worker.preflight(scenario)["checks"][0]["passed"]


def test_clip_refuses_partial_coverage(isolated):
    path = raster(isolated / "tiny.tif", size=2)
    with pytest.raises(ValueError, match="complete requested domain"):
        domain.clip_raster(path, isolated / "out.tif", [71, 33, 73, 35])


def test_snap_refuses_far_channel(isolated, scenario):
    seed(isolated, scenario)
    scenario.outlet.lon = 75
    with pytest.raises(ValueError, match="snap tolerance"):
        domain.snap_outlet(scenario)


def test_model_binding_and_changed_file(isolated, scenario, monkeypatch):
    s = seed(isolated, scenario)
    domain.prepare_domain(s)
    project = isolated / "prepared-project"
    project.mkdir()
    (project / "test.p01").write_text("synthetic test project; not a real RAS model")
    worker.bind(s, project, "01", "Synthetic binding test only")
    monkeypatch.setattr(worker, "runtimes", lambda: {"hec_ras": True, "ras_commander": True})
    assert worker.preflight(s)["ready"]
    (project / "test.p01").write_text("changed")
    assert not worker.preflight(s)["ready"]
    s.forcing.rainfall_multiplier = 1.3
    assert not next(c for c in worker.preflight(s)["checks"] if c["key"] == "prepared_model")["passed"]


def test_changed_registered_inflow_invalidates_model_binding(isolated, scenario, monkeypatch):
    s = seed(isolated, scenario)
    domain.prepare_domain(s)
    project = isolated / "input-hash-test"
    project.mkdir()
    (project / "test.p01").write_text("isolated input-binding fixture")
    worker.bind(s, project, "01", "Isolated source dependency test")
    monkeypatch.setattr(worker, "runtimes", lambda: {"hec_ras": True, "ras_commander": True})
    changed = isolated / "changed-inflow.csv"
    changed.write_text("time,station_id,discharge_m3s,source,value_type\n2022-08-20T00:00:00Z,warsak,200,test,modeled\n2022-09-05T00:00:00Z,warsak,200,test,modeled\n")
    cli.register("inflow", changed, "isolated changed input", "test only", "test flow")
    check = worker.preflight(s)
    assert not check["ready"]
    assert not next(item for item in check["checks"] if item["key"] == "model_assets")["passed"]


def export_manifest(root, s):
    prepared = domain.prepare_domain(s)
    path = raster(root / "depth.tif", values=np.full((100, 100), 1.5))
    spec = {"scenario": s.model_dump(mode="json"), "engine": "HEC-RAS 2D", "terrain_sha256": prepared["clips"]["dem"]["sha256"],
            "units": {"depth": "m", "wse": "m", "velocity": "m/s"}, "vertical_datum": "synthetic test datum", "provenance": {"model_run": "synthetic fixture, not scientific output"},
            "frames": [{"time": "2022-08-20T00:00:00Z", "depth": path.name}]}
    target = root / "export.json"
    write_json(target, spec)
    return target, spec


def test_publish_real_raster_pipeline_without_fake_validation(isolated, scenario):
    s = seed(isolated, scenario)
    path, _ = export_manifest(isolated, s)
    result = publish.publish(path)
    assert result["frames"][0]["fields"]["depth"]["url"].endswith(".png")
    assert result["validation_passed"] is False
    assert (isolated / "results" / result["id"] / "00000-depth.tif").is_file()


def test_validation_requires_all_named_gauges_and_independent_extent(isolated, scenario):
    s = seed(isolated, scenario)
    path, spec = export_manifest(isolated, s)
    spec["frames"] = [{"time": f"2022-08-{day}T00:00:00Z", "depth": "depth.tif"} for day in [20, 21, 22]]
    gauges = isolated / "gauges.csv"
    gauges.write_text("time,station_id,observed_m3s,simulated_m3s\n" + "".join(f"2022-08-{day}T00:00:00Z,nowshera,{value},{value}\n" for day, value in [(20, 1), (21, 2), (22, 3)]))
    spec["gauges_csv"] = gauges.name
    extent = raster(isolated / "extent.tif")
    spec["validation_extent"] = {"path": extent.name, "time": "2022-08-20T00:00:00Z", "source": "Synthetic independent test mask"}
    write_json(path, spec)
    result = publish.publish(path)
    assert result["validation_passed"] is True
    assert result["extent_validation"]["csi"] == 1
    s.id = "missing-gauge-test"
    s.validation.gauge_ids.append("attock")
    path, spec = export_manifest(isolated, s)
    spec.update(gauges_csv=gauges.name, validation_extent={"path": extent.name, "time": "2022-08-20T00:00:00Z", "source": "Synthetic mask"})
    write_json(path, spec)
    assert publish.publish(path)["validation_passed"] is False


@pytest.mark.parametrize("change,match", [("units", "SI units"), ("terrain_sha256", "terrain hash"), ("frames", "increasing")])
def test_publication_rejects_incompatible_output(isolated, scenario, change, match):
    s = seed(isolated, scenario)
    path, spec = export_manifest(isolated, s)
    if change == "units": spec[change]["depth"] = "ft"
    elif change == "frames": spec[change] *= 2
    else: spec[change] = "0" * 64
    write_json(path, spec)
    with pytest.raises(ValueError, match=match):
        publish.publish(path)


def test_api_schema_rejects_bad_scenarios_and_cross_origin(isolated, scenario, monkeypatch):
    module = importlib.import_module("server.app")
    monkeypatch.setattr(module, "ROOT", isolated)
    with TestClient(module.app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.post("/api/scenarios/validate", json=scenario.model_dump(mode="json")).status_code == 200
        assert client.post("/api/jobs", json=scenario.model_dump(mode="json")).status_code == 409
        assert client.post("/api/domain", json={}, headers={"Origin": "https://unrelated.example"}).status_code == 403
        assert client.post("/api/scenarios/validate", json={"schema_version": 9}).status_code == 422
