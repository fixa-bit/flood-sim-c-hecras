"""Run a prepared HEC-HMS project using its bundled Java/Jython API."""
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4
from .models import Scenario
from .store import ROOT, file_hash, scenario_hash, write_json


def compute_hms(scenario: Scenario, project_file: Path, run_name: str, installation: Path, review: str):
    project_file = project_file.resolve()
    installation = installation.resolve()
    java = installation / "jre" / "bin" / "java.exe"
    if project_file.suffix.lower() != ".hms" or not project_file.is_file() or not java.is_file():
        raise ValueError("Supply an existing .hms project and an HEC-HMS installation with bundled Java.")
    if not review.strip() or not run_name.strip():
        raise ValueError("A reviewed hydrology model and an existing simulation run name are required.")
    folder = ROOT / "hydrology" / uuid4().hex
    target = folder / "model"
    shutil.copytree(project_file.parent, target)
    inputs = [{"path": p.relative_to(target).as_posix(), "sha256": file_hash(p)} for p in target.rglob("*") if p.is_file()]
    script = folder / "compute.py"
    script.write_text("from hms.model.JythonHms import *\nfrom java.lang import System\n" + f"OpenProject({project_file.stem!r}, {target.as_posix()!r})\nCompute({run_name!r})\nSystem.exit(0)\n", encoding="utf-8")
    jars = f"{installation / 'hms.jar'};{installation / 'lib' / '*'}"
    libraries = f"{installation / 'bin'};{installation / 'bin' / 'gdal'};{installation / 'bin' / 'hdf'}"
    environment = os.environ.copy()
    environment["PATH"] = libraries + ";" + str(installation / "bin" / "taudem") + ";" + environment.get("PATH", "")
    environment["GDAL_DATA"] = str(installation / "bin" / "gdal" / "gdal-data")
    environment["PROJ_LIB"] = str(installation / "bin" / "gdal" / "projlib")
    command = [str(java), "-Djava.awt.headless=true", "-Dpython.import.site=false", f"-Dpython.path={jars}", f"-Djava.library.path={libraries}", "-classpath", jars, "hms.Hms", "-s", str(script)]
    with (folder / "compute.log").open("w", encoding="utf-8") as log:
        completed = subprocess.run(command, cwd=installation, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=86400)
    text = (folder / "compute.log").read_text(encoding="utf-8", errors="replace")
    if completed.returncode != 0 or "ERROR " in text or "Exception" in text:
        raise RuntimeError(f"HEC-HMS compute did not finish cleanly. Inspect {folder / 'compute.log'}")
    result = {"state": "compute-finished-review-required", "scenario_sha256": scenario_hash(scenario), "run": run_name, "review": review,
              "inputs": inputs, "log": str(folder / "compute.log"), "note": "Review HMS logs and export DSS inflow hydrographs as documented SI boundary CSV. No automatic calibration or rainfall-to-depth conversion."}
    write_json(folder / "manifest.json", result)
    return result
