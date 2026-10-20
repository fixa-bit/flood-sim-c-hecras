import hashlib
import json
import os
from pathlib import Path
from .models import Scenario

ROOT = Path(os.environ.get("FLOOD_WORKSPACE", Path(__file__).resolve().parents[1] / "workspace")).resolve()


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def file_hash(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scenario_hash(scenario: Scenario):
    # Canonical server serialization, also used when binding prepared engine inputs.
    raw = json.dumps(scenario.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def assets():
    return read_json(ROOT / "assets.json", {})


def asset_path(asset):
    path = (ROOT / asset["path"]).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Asset path leaves the workspace.")
    return path


def checked_asset(key):
    asset = assets().get(key)
    if not asset:
        raise ValueError(f"Missing {key} asset. Register a documented local input with the CLI.")
    path = asset_path(asset)
    if not path.is_file() or file_hash(path) != asset["sha256"]:
        raise ValueError(f"The {key} asset is missing or its hash changed; register it again.")
    return asset, path
