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


def test_wse_overlay_bins_fit_the_event_range(isolated, scenario):
    s = seed(isolated, scenario)
    path, spec = export_manifest(isolated, s)
    # A narrow valley reach: every value would fall into one fixed 100-300 m bin.
    levels = np.linspace(285, 292, 100 * 100).reshape(100, 100)
    raster(isolated / "wse.tif", values=levels)
    spec["frames"][0]["wse"] = "wse.tif"
    write_json(path, spec)
    result = publish.publish(path)
    edges = result["legend"]["wse"]
    assert len(edges) == 4 and 285 < edges[0] < edges[-1] < 292
    from PIL import Image
    pixels = np.asarray(Image.open(isolated / "results" / result["id"] / "00000-wse.png")).reshape(-1, 4)
    colours = {tuple(pixel) for pixel in pixels if pixel[3]}
    assert len(colours) == 5
    assert result["legend"]["depth"] == publish.FIELD_EDGES["depth"]


def test_restyle_wse_updates_only_overlays_and_hashes(isolated, scenario):
    s = seed(isolated, scenario)
    path, spec = export_manifest(isolated, s)
    raster(isolated / "wse.tif", values=np.linspace(285, 292, 100 * 100).reshape(100, 100))
    spec["frames"][0]["wse"] = "wse.tif"
    write_json(path, spec)
    result = publish.publish(path)
    folder = isolated / "results" / result["id"]
    # Simulate a manifest published with the old fixed bins.
    old = store.read_json(folder / "manifest.json")
    old.pop("legend")
    publish.raster_overlay(folder / "00000-wse.tif", folder / "00000-wse.png", "wse")
    old["frames"][0]["fields"]["wse"]["overlay_sha256"] = file_hash(folder / "00000-wse.png")
    write_json(folder / "manifest.json", old)
    original = file_hash(folder / "00000-wse.tif")
    summary = publish.restyle_wse(result["id"])
    restyled = store.read_json(folder / "manifest.json")
    assert summary["frames"] == 1 and restyled["legend"]["wse"] == summary["wse_edges"]
    assert file_hash(folder / "00000-wse.tif") == original
    assert restyled["frames"][0]["fields"]["wse"]["overlay_sha256"] == file_hash(folder / "00000-wse.png")
    (folder / "00000-wse.tif").write_bytes(b"changed")
    with pytest.raises(ValueError, match="missing or changed"):
        publish.restyle_wse(result["id"])


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


def test_results_list_summaries_and_serve_full_detail(isolated, monkeypatch):
    module = importlib.import_module("server.app")
    monkeypatch.setattr(module, "ROOT", isolated)
    frames = [{"time": f"2022-08-20T0{i}:00:00Z", "fields": {}} for i in range(3)]
    write_json(isolated / "results" / "current" / "manifest.json", {"id": "current", "frames": frames, "hydrographs": [{"station_id": "x"}]})
    write_json(isolated / "results" / "old" / "manifest.json", {"id": "old", "frames": [], "superseded_by": "current"})
    with TestClient(module.app) as client:
        listing = client.get("/api/results").json()
        assert listing == [{"id": "current", "frame_count": 3}]
        detail = client.get("/api/results/current").json()
        assert detail["frames"] == frames and detail["hydrographs"] == [{"station_id": "x"}]
        assert client.get("/api/results/missing").status_code == 404
        assert client.get("/api/results/..%2F..%2Fassets").status_code in {404, 422}


def test_startup_fails_jobs_interrupted_by_a_previous_process(isolated, monkeypatch):
    for job_id, state in [("1" * 32, "running"), ("2" * 32, "queued"), ("3" * 32, "published")]:
        write_json(isolated / "jobs" / job_id / "status.json", {"id": job_id, "state": state})
    module = importlib.import_module("server.app")
    monkeypatch.setattr(module, "ROOT", isolated)
    with TestClient(module.app) as client:
        running = client.get(f"/api/jobs/{'1' * 32}").json()
        assert running["state"] == "failed" and running["interrupted_state"] == "running"
        assert client.get(f"/api/jobs/{'2' * 32}").json()["state"] == "failed"
        assert client.get(f"/api/jobs/{'3' * 32}").json()["state"] == "published"


def test_failed_job_creation_releases_the_compute_lock(isolated, scenario, monkeypatch):
    module = importlib.import_module("server.app")
    monkeypatch.setattr(module, "ROOT", isolated)
    monkeypatch.setattr(module, "preflight", lambda s: {"ready": True, "scenario_sha256": "f" * 64, "checks": []})
    monkeypatch.setattr(module, "background_compute", lambda s, job_id: module.compute_lock.release())
    def failing_write(path, value):
        raise OSError("disk full")
    monkeypatch.setattr(module, "write_json", failing_write)
    payload = scenario.model_dump(mode="json")
    with TestClient(module.app, raise_server_exceptions=False) as client:
        assert client.post("/api/jobs", json=payload).status_code == 500
        assert not module.compute_lock.locked()
        monkeypatch.setattr(module, "write_json", write_json)
        assert client.post("/api/jobs", json=payload).status_code == 202
    assert not module.compute_lock.locked()


def test_prune_jobs_keeps_current_and_cited_runs(isolated, monkeypatch):
    import os
    docs = isolated / "docs"
    docs.mkdir()
    (docs / "RUN.md").write_text("The native run is under workspace/jobs/" + "c" * 32 + "/.")
    monkeypatch.setattr(worker, "DOCS", docs)
    write_json(isolated / "results" / "current" / "manifest.json", {"id": "current"})
    write_json(isolated / "results" / "old" / "manifest.json", {"id": "old", "superseded_by": "current"})
    jobs = {"a" * 32: ("published", "current", True), "b" * 32: ("published", "old", True), "c" * 32: ("published", "old", True),
            "d" * 32: ("published", "current", False), "e" * 32: ("running", None, True), "f" * 32: ("computed", None, True)}
    for job_id, (state, result_id, has_model) in jobs.items():
        write_json(isolated / "jobs" / job_id / "status.json", {"id": job_id, "state": state, "result_id": result_id})
        if has_model:
            (isolated / "jobs" / job_id / "model").mkdir()
            (isolated / "jobs" / job_id / "model" / "out.bin").write_bytes(b"x" * 1000)
    old = (isolated / "jobs" / ("d" * 32) / "status.json")
    os.utime(old, (old.stat().st_mtime - 30 * 86400,) * 2)
    plan = worker.prune_jobs(older_than_days=14)
    assert {(item["job"][0], item["remove"]) for item in plan["items"]} == {("b", "model/"), ("d", "job record")}
    assert (isolated / "jobs" / ("b" * 32) / "model").is_dir(), "dry run must not delete"
    worker.prune_jobs(older_than_days=14, apply=True)
    assert not (isolated / "jobs" / ("b" * 32) / "model").exists()
    assert (isolated / "jobs" / ("b" * 32) / "status.json").is_file()
    assert not (isolated / "jobs" / ("d" * 32)).exists()
    for kept in "acef":
        assert (isolated / "jobs" / (kept * 32) / "model").is_dir() or kept == "d"


@pytest.mark.parametrize("engine,plan", [("HEC-RAS 2D", "01"), ("LISFLOOD-FP", "screen.par")])
def test_attach_and_execute_selected_engine(isolated, scenario, monkeypatch, engine, plan):
    import sys
    from types import SimpleNamespace

    s = seed(isolated, scenario)
    s.hydraulics.engine = engine
    s.hydraulics.equations = "full SWE" if engine == "HEC-RAS 2D" else "local inertial"
    domain.prepare_domain(s)
    project = isolated / "source-model"
    project.mkdir()
    (project / ("test.p01" if engine == "HEC-RAS 2D" else plan)).write_text(
        "Synthetic adapter fixture only" if engine == "HEC-RAS 2D" else "acceleration\n"
    )
    module = importlib.import_module("server.app")
    payload = {"scenario": s.model_dump(mode="json"), "project": str(project), "plan": plan, "review": "Synthetic adapter verification only"}
    with TestClient(module.app) as client:
        response = client.post("/api/model-bindings", json=payload)
        assert response.status_code == 200, response.text
        assert response.json() == {"engine": engine, "plan": plan, "scenario_sha256": scenario_hash(s)}
        assert client.post("/api/model-bindings", json=payload, headers={"Origin": "https://unrelated.example"}).status_code == 403
        assert client.post("/api/model-bindings", json={**payload, "project": "relative-model"}).status_code == 422
        assert client.post("/api/model-bindings", json={**payload, "review": " "}).status_code == 422

    monkeypatch.setattr(worker, "runtimes", lambda: {
        "hec_ras": True, "ras_commander": True, "hec_ras_exe": "test-Ras.exe",
        "lisflood_fp": True, "lisflood_fp_exe": "test-lisflood.exe",
    })
    assert worker.preflight(s)["ready"]
    calls = []
    def init_ras(folder, executable, ras_object):
        assert Path(folder) != project
        assert (Path(folder) / "test.p01").read_bytes() == (project / "test.p01").read_bytes()
        calls.append(("ras", executable))
    def compute_ras(selected_plan, **kwargs):
        assert selected_plan == "01"
        return True
    monkeypatch.setitem(sys.modules, "ras_commander", SimpleNamespace(
        RasPrj=object, init_ras_project=init_ras,
        RasCmdr=SimpleNamespace(compute_plan=compute_ras),
    ))
    def run_lisflood(command, **kwargs):
        assert Path(kwargs["cwd"]) != project
        assert Path(command[1]).name == "screen.par"
        calls.append(("lisflood", command[0]))
    monkeypatch.setattr(worker.subprocess, "run", run_lisflood)
    job_id = "a" * 32
    worker.execute(s, job_id)
    status = store.read_json(isolated / "jobs" / job_id / "status.json")
    assert status["state"] == "computed", status
    assert calls == ([("ras", "test-Ras.exe")] if engine == "HEC-RAS 2D" else [("lisflood", "test-lisflood.exe")])


@pytest.mark.parametrize("field,value,check_key", [
    ("engine", "LISFLOOD-FP", "model_engine"),
    ("scenario_sha256", "0" * 64, "model_scenario"),
])
def test_preflight_rejects_wrong_engine_or_scenario_binding(isolated, scenario, monkeypatch, field, value, check_key):
    s = seed(isolated, scenario)
    domain.prepare_domain(s)
    project = isolated / "prepared-project"
    project.mkdir()
    (project / "test.p01").write_text("Synthetic identity fixture only")
    binding = worker.bind(s, project, "01", "Synthetic identity test")
    binding[field] = value
    write_json(isolated / "bindings" / f"{scenario_hash(s)}.json", binding)
    monkeypatch.setattr(worker, "runtimes", lambda: {"hec_ras": True, "ras_commander": True})
    check = worker.preflight(s)
    assert not check["ready"]
    assert not next(c for c in check["checks"] if c["key"] == check_key)["passed"]
