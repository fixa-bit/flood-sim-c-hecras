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


# Each hydraulic site keeps its own input catalog. Nowshera's stays at the
# original path so its accepted bindings and hashes are untouched.
SITE_CATALOGS = {"nowshera": "assets.json", "warsak": "sites/warsak/assets.json"}
DEFAULT_SITE = "nowshera"


def site_of(scenario: Scenario):
    """The catalog a scenario reads; custom outlets keep the original catalog."""
    station = scenario.outlet.station_id
    return station if station in SITE_CATALOGS else DEFAULT_SITE


def catalog_path(site=None):
    site = site or DEFAULT_SITE
    if site not in SITE_CATALOGS:
        raise ValueError(f"Unknown hydraulic site {site!r}.")
    return ROOT / SITE_CATALOGS[site]


def assets(site=None):
    return read_json(catalog_path(site), {})


def save_assets(catalog, site=None):
    write_json(catalog_path(site), catalog)


def asset_path(asset):
    path = (ROOT / asset["path"]).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Asset path leaves the workspace.")
    return path


def checked_asset(key, site=None):
    asset = assets(site).get(key)
    if not asset:
        where = f" for {site}" if site and site != DEFAULT_SITE else ""
        raise ValueError(f"Missing {key} asset{where}. Register a documented local input with the CLI.")
    path = asset_path(asset)
    if not path.is_file() or file_hash(path) != asset["sha256"]:
        raise ValueError(f"The {key} asset is missing or its hash changed; register it again.")
    return asset, path
