"""Execute hash-bound external engine projects; never generate water in Python."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
from .models import Scenario
from .store import ROOT, assets, checked_asset, file_hash, read_json, scenario_hash, write_json


def runtimes():
    config = read_json(ROOT / "runtimes.json", {})
    ras = os.environ.get("HEC_RAS_EXE", config.get("hec_ras_exe", ""))
    if not ras:
        candidates = list((ROOT / "tools").glob("**/Ras.exe"))
        ras = str(candidates[0]) if candidates else ""
    hms = os.environ.get("HEC_HMS_EXE", config.get("hec_hms_exe", ""))
    lisflood = os.environ.get("LISFLOOD_FP_EXE", config.get("lisflood_fp_exe", ""))
    return {"hec_ras": bool(ras and Path(ras).is_file()), "hec_ras_exe": ras,
            "ras_commander": importlib.util.find_spec("ras_commander") is not None,
            "hec_hms": bool(hms and Path(hms).is_file()) or any((ROOT / "tools").glob("**/HEC-HMS.exe")),
            "lisflood_fp": bool(lisflood and Path(lisflood).is_file()), "lisflood_fp_exe": lisflood}


def preflight(s: Scenario):
    checks = []
    def add(key, passed, detail):
        checks.append({"key": key, "passed": bool(passed), "detail": detail})
    add("pilot", s.outlet.station_id == "nowshera", "Nowshera is the first hydraulic pilot; other stations and custom outlets support planning only.")
    required = ["dem", "hydrography", "catchment", "soil", "landcover"]
    required += ["inflow"] if s.forcing.mode == "inflow_hydrograph" else ["rainfall"]
    if s.forcing.soil_moisture == "SMAP":
        required += ["moisture"]
    for key in required:
        try:
            asset, _ = checked_asset(key)
            add(key, True, f"{asset['source']} · SHA-256 verified")
        except ValueError as exc:
            add(key, False, str(exc))
    dem = assets().get("dem")
    add("dem_hash", dem and s.domain.dem_sha256 == dem["sha256"], "Bind the scenario to the registered source DEM SHA-256.")
    digest = scenario_hash(s)
    domain = read_json(ROOT / "domains" / digest / "domain.json")
    hashes = {key: asset["sha256"] for key, asset in assets().items() if key in {"dem", "soil", "moisture", "rainfall", "landcover", "hydrography", "catchment"}}
    domain_valid = domain and domain.get("catchment") and domain.get("input_hashes") == hashes
    if domain_valid:
        domain_valid = all((ROOT / "domains" / digest / item["file"]).is_file() and file_hash(ROOT / "domains" / digest / item["file"]) == item["sha256"] for item in domain["clips"].values())
    add("domain", domain_valid, "Prepare the exact scenario domain with a snapped outlet and supplied catchment delineation. Input hashes must still match.")
    if s.forcing.mode == "inflow_hydrograph" and "inflow" in assets():
        from datetime import datetime
        coverage = assets()["inflow"].get("metadata", {}).get("coverage", {})
        selected = s.forcing.upstream_station_ids or [s.outlet.station_id]
        covered = all(station in coverage and datetime.fromisoformat(coverage[station][0]) <= s.time.start and datetime.fromisoformat(coverage[station][1]) >= s.time.end for station in selected)
        add("boundary_coverage", covered, "Every selected inflow boundary must cover the full model time window in m³/s; contributing lateral inflows remain part of the model review.")
    add("bias_correction", s.forcing.bias_correction.strip(), "Document rainfall bias correction, or explain why rainfall is unused for a gauge-driven run.")
    if s.forcing.inflow_asset:
        add("inflow_hash", assets().get("inflow", {}).get("sha256") == s.forcing.inflow_asset, "The selected inflow SHA-256 must match the registered boundary file.")
    add("structures", all(item.specification.strip() for item in s.hydraulics.structures), "Structures need geometry, operation and breach/release timing in the prepared model.")
    if s.kind == "design_storm":
        add("idf", "idf" in s.provenance.notes.lower(), "Document the local IDF source and design hyetograph; an entered return period is not evidence.")
    binding = read_json(ROOT / "bindings" / f"{digest}.json")
    add("prepared_model", binding, f"Attach a reviewed {s.hydraulics.engine} project in Hydraulic model, or use `python -m server.cli bind`. Scenario edits require a matching model binding.")
    if binding:
        add("model_engine", binding.get("engine") == s.hydraulics.engine, "The prepared model must use the selected simulation engine.")
        add("model_scenario", binding.get("scenario_sha256") == digest, "The prepared model must match the exact scenario being submitted.")
        if binding.get("asset_hashes") is not None:
            add("model_assets", all(assets().get(key, {}).get("sha256") == digest for key, digest in binding["asset_hashes"].items()), "Registered model inputs must match the prepared project's source hashes.")
        for item in binding["files"]:
            path = Path(binding["project"]) / item["path"]
            add(f"model:{item['path']}", path.is_file() and file_hash(path) == item["sha256"], "Prepared model input hash must match its binding.")
    runtime = runtimes()
    if s.hydraulics.engine == "HEC-RAS 2D":
        add("runtime", runtime["hec_ras"] and runtime["ras_commander"], "Installed HEC-RAS and ras-commander[compute] are required.")
        if binding and (Path(binding["project"]) / "hecras-case.json").is_file():
            from .hecras import FORMAT
            config = read_json(Path(binding["project"]) / "hecras-case.json")
            add("hecras_format", config.get("format") == FORMAT, "Use the current prepared HEC-RAS public case.")
            add("hecras_engine", runtime["hec_ras"] and file_hash(Path(runtime["hec_ras_exe"])) == config.get("engine_sha256"), "This exploratory HEC case requires the exact engine build recorded during preparation.")
    else:
        add("runtime", runtime["lisflood_fp"], "Set LISFLOOD_FP_EXE to a locally installed LISFLOOD-FP executable.")
        if binding and (Path(binding["project"]) / "screening.json").is_file():
            config = read_json(Path(binding["project"]) / "screening.json")
            from .screening import FORMAT
            add("screening_format", config.get("format") == FORMAT, "Use the current prepared public case with channel conditioning, river warm-up and a complete discharge cross-section; earlier preparation versions are superseded.")
            add("screening_engine", runtime["lisflood_fp"] and file_hash(Path(runtime["lisflood_fp_exe"])) == config.get("engine_sha256"), "Exploratory screening requires the exact engine build recorded in its preparation review.")
    return {"scenario_sha256": digest, "ready": all(c["passed"] for c in checks), "checks": checks}


def bind(s: Scenario, project: Path, plan: str, review: str):
    if not review.strip():
        raise ValueError("A model review document/reference is required.")
    project = project.resolve()
    if not project.is_dir():
        raise ValueError("Project directory does not exist.")
    import re
    if s.hydraulics.engine == "HEC-RAS 2D" and not re.fullmatch(r"\d{2}", plan):
        raise ValueError("HEC-RAS plan number must contain exactly two digits.")
    if s.hydraulics.engine == "LISFLOOD-FP":
        parameter = (project / plan).resolve()
        if not parameter.is_relative_to(project) or not parameter.is_file():
            raise ValueError("LISFLOOD parameter file must be inside its project.")
        keys = {line.split()[0].lower() for line in parameter.read_text(encoding="utf-8-sig").splitlines() if line.strip() and not line.lstrip().startswith("#")}
        if "acceleration" not in keys or "fv1" in keys or "dg2" in keys:
            raise ValueError("The screening adapter requires a reviewed local-inertial ACC project (acceleration flag).")
    files = []
    # A complete snapshot detects changed terrain and DSS as well as text inputs.
    for path in project.rglob("*"):
        if path.is_file():
            files.append({"path": path.relative_to(project).as_posix(), "sha256": file_hash(path)})
    if not files or s.hydraulics.engine == "HEC-RAS 2D" and not list(project.glob(f"*.p{plan}")):
        raise ValueError("Prepared project is empty or the requested RAS plan is missing.")
    value = {"scenario_sha256": scenario_hash(s), "project": str(project), "plan": plan, "review": review, "files": files, "engine": s.hydraulics.engine,
             "asset_hashes": {key: value["sha256"] for key, value in assets().items() if key != "validation"}}
    write_json(ROOT / "bindings" / f"{scenario_hash(s)}.json", value)
    return value


def execute(s: Scenario, job_id: str):
    folder = ROOT / "jobs" / job_id
    status_path = folder / "status.json"
    try:
        check = preflight(s)
        if not check["ready"]:
            raise ValueError("Preflight failed. Prepare the missing data and model inputs first.")
        binding = read_json(ROOT / "bindings" / f"{scenario_hash(s)}.json")
        screening = Path(binding["project"]) / "screening.json"
        hecras_case = Path(binding["project"]) / "hecras-case.json"
        if (s.hydraulics.engine == "LISFLOOD-FP" and screening.is_file()) or (s.hydraulics.engine == "HEC-RAS 2D" and hecras_case.is_file()):
            if s.hydraulics.engine == "HEC-RAS 2D":
                from .hecras import cached_result
            else:
                from .screening import cached_result
            cached = cached_result(s)
            if cached:
                write_json(status_path, {"id": job_id, "state": "published", "scenario_sha256": scenario_hash(s), "result_id": cached["id"],
                    "detail": "Loaded the verified output of this exact prepared case. Exploratory and uncalibrated."})
                return
        write_json(status_path, {"id": job_id, "state": "running", "scenario_sha256": scenario_hash(s)})
        project = folder / "model"
        shutil.copytree(binding["project"], project)
        if s.hydraulics.engine == "HEC-RAS 2D":
            from ras_commander import RasPrj, init_ras_project, RasCmdr
            ras = RasPrj()
            init_ras_project(str(project), runtimes()["hec_ras_exe"], ras_object=ras)
            success = RasCmdr.compute_plan(binding["plan"], ras_object=ras, verify=True, max_runtime=86400, num_cores=2)
            if not success:
                raise RuntimeError("HEC-RAS did not report a successful compute. Inspect its model logs.")
            if (project / "hecras-case.json").is_file():
                from .hecras import finish_and_publish
                result = finish_and_publish(s, project)
                write_json(status_path, {"id": job_id, "state": "published", "scenario_sha256": scenario_hash(s), "result_id": result["id"],
                    "detail": "HEC-RAS full SWE completed; native numerical checks passed and timestamped rasters are available. Exploratory and uncalibrated."})
                return
        else:
            parameter = project / binding["plan"]
            if not parameter.resolve().is_relative_to(project.resolve()) or not parameter.is_file():
                raise ValueError("LISFLOOD parameter file must be inside the prepared project.")
            with (folder / "engine.log").open("w", encoding="utf-8") as log:
                subprocess.run([runtimes()["lisflood_fp_exe"], str(parameter)], cwd=project, check=True, timeout=86400, stdout=log, stderr=subprocess.STDOUT,
                               env={**os.environ, "OMP_NUM_THREADS": "2"}, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if (project / "screening.json").is_file():
                from .screening import finish_and_publish
                result = finish_and_publish(s, project)
                write_json(status_path, {"id": job_id, "state": "published", "scenario_sha256": scenario_hash(s), "result_id": result["id"],
                    "detail": "External engine completed; numerical checks passed and timestamped output is available. Exploratory and uncalibrated."})
                return
        write_json(status_path, {"id": job_id, "state": "computed", "scenario_sha256": scenario_hash(s),
                                 "detail": "Engine compute finished. Export and publish timestamped model rasters before playback; model review is required."})
    except Exception as exc:
        write_json(status_path, {"id": job_id, "state": "failed", "detail": str(exc)})
