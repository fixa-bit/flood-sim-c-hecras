from pathlib import Path
from uuid import uuid4
from threading import Lock
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Query
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from .domain import prepare_domain
from .models import Scenario, StrictModel
from pydantic import Field
from .store import ROOT, assets, read_json, write_json
from .worker import bind, execute, preflight, runtimes

app = FastAPI(title="Pakistan Flood Lab — local model services", version="1.0.0")
(ROOT / "results").mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=ROOT / "results"), name="outputs")
compute_lock = Lock()


@app.middleware("http")
async def local_mutations(request: Request, call_next):
    # Local tooling should not accept cross-site writes from arbitrary websites.
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in {"http://localhost:5174", "http://127.0.0.1:5174", "http://localhost:8010", "http://127.0.0.1:8010"}:
        return JSONResponse({"detail": "Only local development origins may mutate this workspace."}, status_code=403)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"status": "ok", "pilot": "nowshera", "runtimes": runtimes()}


@app.get("/api/assets")
def list_assets():
    return assets()


@app.get("/api/terrain/metadata")
def map_terrain():
    from .map_context import viewer_terrain_metadata
    return viewer_terrain_metadata()


@app.get("/api/terrain/{level}/{x}/{y}.bin")
def map_terrain_tile(level: int, x: int, y: int):
    from .map_context import terrain_tile
    try:
        content = terrain_tile(level, x, y)
        return Response(content, media_type="application/octet-stream", headers={"Cache-Control": "no-cache"})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/river-context")
def map_river(lon: float = Query(ge=60, le=80), lat: float = Query(ge=23, le=38)):
    from .map_context import river_context
    try:
        return river_context(lon, lat)
    except ValueError as exc:
        return {"available": False, "reason": str(exc)}


@app.get("/api/study")
def public_study():
    import csv
    from .study import STUDY
    result = {name: read_json(STUDY / filename) for name, filename in {
        "boundaries": "boundary-review.json", "moisture": "moisture-review.json", "rainfall": "rainfall-review.json", "routing": "routing-calibration.json",
        "inflow_improvement": "inflow-improvement.json"}.items()}
    geometry = read_json(ROOT / "geometry" / "latest.json")
    if geometry:
        geometry["available_cases"] = []
        for path in sorted((ROOT / "hecras" / "variants").glob("*.json")):
            case = read_json(path)
            metadata = read_json(Path(case["project"]) / "hecras-case.json", {})
            if case.get("ready") and metadata.get("roughness_zones", {}).get("fingerprint") == geometry["fingerprint"]:
                geometry["available_cases"].append({"id": case["scenario"]["id"], "label": case["label"], "result_id": case["result_id"]})
    result["geometry_roughness"] = geometry
    path = STUDY / "hms-nowshera-hourly-modeled.csv"
    result["hydrograph"] = None
    if path.exists() and result["routing"]:
        from .store import file_hash
        expected_hash = result["routing"].get("output_csv_sha256")
        if expected_hash and expected_hash != file_hash(path):
            raise HTTPException(409, "Study output changed after calibration. Recompute the study before plotting it.")
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        result["hydrograph"] = {"station_id": "nowshera", "samples": [{"time": row["time"], "simulated_m3s": float(row["discharge_m3s"]),
            "observed_m3s": float(row["observed_m3s"]) if row["observed_m3s"] else None} for row in rows],
            "metrics": result["routing"]["scores"]["validation"]}
    return result


@app.get("/api/schema")
def schema():
    return Scenario.model_json_schema()


@app.post("/api/scenarios/validate")
def validate(scenario: Scenario):
    return scenario.model_dump(mode="json")


@app.post("/api/preflight")
def check(scenario: Scenario):
    return preflight(scenario)


class ModelBindingRequest(StrictModel):
    scenario: Scenario
    project: str = Field(min_length=1)
    plan: str = Field(min_length=1)
    review: str = Field(min_length=1)


@app.post("/api/model-bindings")
def attach_model(request: ModelBindingRequest):
    try:
        project = Path(request.project)
        if not project.is_absolute():
            raise ValueError("Enter the absolute path to the prepared model folder.")
        binding = bind(request.scenario, project, request.plan, request.review)
        return {key: binding[key] for key in ["scenario_sha256", "engine", "plan"]}
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/domain")
def domain(scenario: Scenario):
    try:
        return prepare_domain(scenario)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/results")
def results():
    return [result for path in sorted((ROOT / "results").glob("*/manifest.json")) if not (result := read_json(path)).get("superseded_by")]


@app.get("/api/prepared-cases")
def list_prepared_cases():
    from .screening import prepared_cases
    hecras_case = read_json(ROOT / "hecras" / "case.json")
    variants = [read_json(path) for path in sorted((ROOT / "hecras" / "variants").glob("*.json"))]
    return prepared_cases() + ([hecras_case] if hecras_case else []) + [case for case in variants if case.get("ready")]


def background_compute(scenario, job_id):
    try:
        execute(scenario, job_id)
    finally:
        compute_lock.release()


@app.post("/api/jobs", status_code=202)
def create_job(scenario: Scenario, background_tasks: BackgroundTasks):
    check = preflight(scenario)
    if not check["ready"]:
        raise HTTPException(409, check)
    binding = read_json(ROOT / "bindings" / f"{check['scenario_sha256']}.json", {})
    public_project = Path(binding.get("project", ""))
    if (scenario.hydraulics.engine == "LISFLOOD-FP" and (public_project / "screening.json").is_file()) or (scenario.hydraulics.engine == "HEC-RAS 2D" and (public_project / "hecras-case.json").is_file()):
        if scenario.hydraulics.engine == "HEC-RAS 2D":
            from .hecras import cached_result
        else:
            from .screening import cached_result
        try:
            cached = cached_result(scenario)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if cached:
            job_id = uuid4().hex
            job = {"id": job_id, "state": "published", "scenario_sha256": check["scenario_sha256"], "result_id": cached["id"],
                   "detail": "Loaded the verified output of this exact prepared case. Exploratory and uncalibrated."}
            write_json(ROOT / "jobs" / job_id / "status.json", job)
            write_json(ROOT / "jobs" / job_id / "scenario.json", scenario.model_dump(mode="json"))
            return job
    if not compute_lock.acquire(blocking=False):
        raise HTTPException(409, "A model is already computing in this local worker.")
    job_id = uuid4().hex
    job = {"id": job_id, "state": "queued", "scenario_sha256": check["scenario_sha256"]}
    write_json(ROOT / "jobs" / job_id / "status.json", job)
    write_json(ROOT / "jobs" / job_id / "scenario.json", scenario.model_dump(mode="json"))
    background_tasks.add_task(background_compute, scenario, job_id)
    return job


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        raise HTTPException(404, "Unknown job")
    job = read_json(ROOT / "jobs" / job_id / "status.json")
    if job is None:
        raise HTTPException(404, "Unknown job")
    return job
