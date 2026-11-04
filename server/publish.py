"""Publish exported model rasters. Never rasterizes invented water surfaces."""
from datetime import datetime
from pathlib import Path
import shutil
import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from PIL import Image
from .models import Scenario
from .metrics import extent_metrics, read_hydrographs
from .store import ROOT, file_hash, read_json, scenario_hash, write_json

# Bin edges and colors are shared with the viewer legend (stored per result as
# "legend"). Dry and nodata are transparent. WSE edges are fitted to each
# event, because absolute elevations differ by hundreds of metres between reaches.
COLORS = np.array([[145, 215, 241, 200], [61, 169, 220, 215], [34, 111, 192, 225], [34, 67, 145, 235], [100, 65, 156, 240]], dtype=np.uint8)
FIELD_EDGES = {"depth": [0.3, 1, 2, 5], "wse": [100, 300, 500, 1000], "velocity": [0.5, 1, 2, 3]}
WSE_SAMPLE_PER_FRAME = 50_000
WSE_MIN_SPAN_M = 0.5


def wse_edges(paths):
    """Four class edges spanning the pooled 2nd-98th percentile of valid WSE."""
    samples = []
    for path in paths:
        with rasterio.open(path) as src:
            values = src.read(1, masked=True).astype(np.float64).compressed()
        values = values[np.isfinite(values)]
        if values.size > WSE_SAMPLE_PER_FRAME:
            values = values[:: values.size // WSE_SAMPLE_PER_FRAME + 1]
        samples.append(values)
    pooled = np.concatenate(samples) if samples else np.array([])
    if not pooled.size:
        return list(FIELD_EDGES["wse"])
    low, high = np.percentile(pooled, [2, 98])
    if high - low < WSE_MIN_SPAN_M:
        middle = (low + high) / 2
        low, high = middle - WSE_MIN_SPAN_M / 2, middle + WSE_MIN_SPAN_M / 2
    return [round(float(edge), 1) for edge in np.linspace(low, high, 6)[1:5]]


def raster_overlay(path: Path, output: Path, field="depth", edges=None):
    with rasterio.open(path) as src:
        if not src.crs or src.count != 1:
            raise ValueError("Model fields must be single-band, georeferenced rasters.")
        if src.width * src.height > 16_000_000:
            raise ValueError("Publish rasters in bounded clips of at most 16 million cells.")
        affine, width, height = calculate_default_transform(src.crs, "EPSG:4326", src.width, src.height, *src.bounds)
        # Limit the browser overlay; preserve original GeoTIFF separately for scientific use.
        scale = max(width / 1536, height / 1536, 1)
        width, height = max(1, int(width / scale)), max(1, int(height / scale))
        affine = affine @ affine.scale(scale, scale)
        values = np.full((height, width), np.nan, dtype=np.float32)
        source = src.read(1, masked=True).astype(np.float32).filled(np.nan)
        reproject(source, values, src_transform=src.transform, src_crs=src.crs, src_nodata=np.nan,
                  dst_transform=affine, dst_crs="EPSG:4326", dst_nodata=np.nan, resampling=Resampling.nearest)
        rgba = COLORS[np.digitize(np.nan_to_num(values), edges or FIELD_EDGES[field])].copy()
        valid = np.isfinite(values)
        if field in {"depth", "velocity"}:
            valid &= values > 0
        rgba[~valid] = 0
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgba).save(output)
        west, south, east, north = rasterio.transform.array_bounds(height, width, affine)
        return [west, south, east, north]


def restyle_wse(result_id: str):
    """Redraw WSE overlays of a published result with event-fitted bins.

    Original GeoTIFFs are verified and left untouched; only the derived PNG
    overlays, their hashes and the manifest legend change.
    """
    folder = (ROOT / "results" / result_id).resolve()
    if not folder.is_relative_to((ROOT / "results").resolve()):
        raise ValueError("Unknown result.")
    result = read_json(folder / "manifest.json")
    if not result:
        raise ValueError(f"No published result named {result_id}.")
    fields = [frame["fields"]["wse"] for frame in result["frames"] if "wse" in frame["fields"]]
    if not fields:
        raise ValueError("This result has no WSE rasters.")
    rasters = [folder / Path(field["raster_url"]).name for field in fields]
    for raster, field in zip(rasters, fields):
        if not raster.is_file() or file_hash(raster) != field["sha256"]:
            raise ValueError(f"Original raster {raster.name} is missing or changed; refusing to restyle.")
    edges = wse_edges(rasters)
    for raster, field in zip(rasters, fields):
        overlay = folder / Path(field["url"]).name
        field["bounds"] = raster_overlay(raster, overlay, "wse", edges)
        field["overlay_sha256"] = file_hash(overlay)
    result["legend"] = {**FIELD_EDGES, **result.get("legend", {}), "wse": edges}
    write_json(folder / "manifest.json", result)
    return {"id": result_id, "frames": len(fields), "wse_edges": edges}


def inspect_hdf(path: Path):
    import h5py
    found = []
    with h5py.File(path, "r") as hdf:
        def visit(name, item):
            if isinstance(item, h5py.Dataset) and any(key in name.lower() for key in ["water surface", "velocity", "depth", "time date stamp"]):
                found.append({"path": name, "shape": list(item.shape), "dtype": str(item.dtype)})
        hdf.visititems(visit)
    return {"sha256": file_hash(path), "datasets": found,
            "note": "Native mesh fields require RAS Mapper or a documented mesh-to-raster export, CRS, units and vertical datum. Face velocity is not cell-center velocity."}


def publish(manifest_path: Path):
    config = read_json(manifest_path)
    scenario = Scenario.model_validate(config["scenario"])
    if config["engine"] != scenario.hydraulics.engine:
        raise ValueError("Result engine differs from scenario engine.")
    if config.get("units") != {"depth": "m", "wse": "m", "velocity": "m/s"}:
        raise ValueError("Declare SI units; convert HEC-RAS US customary output before publishing.")
    if not config.get("vertical_datum") or not config.get("provenance", {}).get("model_run"):
        raise ValueError("Result requires a vertical datum and model-run provenance.")
    digest = scenario_hash(scenario)
    domain = read_json(ROOT / "domains" / digest / "domain.json")
    if not domain or config.get("terrain_sha256") != domain["clips"]["dem"]["sha256"]:
        raise ValueError("Result terrain hash must match the prepared scenario DEM clip.")
    frames = config.get("frames", [])
    if not frames:
        raise ValueError("At least one timestamped depth raster is required.")
    result_id = f"{scenario.id}-{digest[:12]}"
    folder = ROOT / "results" / result_id
    if (folder / "manifest.json").exists():
        raise ValueError("This result already exists. Use a new scenario ID to preserve provenance.")
    base = manifest_path.resolve().parent
    legend = {**FIELD_EDGES, "wse": wse_edges([(base / frame["wse"]).resolve() for frame in frames if "wse" in frame])}
    output_frames, times = [], []
    common_grid = None
    try:
        for index, frame in enumerate(frames):
            time = datetime.fromisoformat(frame["time"].replace("Z", "+00:00"))
            if time.tzinfo is None or not scenario.time.start <= time <= scenario.time.end:
                raise ValueError("Every result timestamp must lie inside the scenario window and include a timezone.")
            if times and time <= times[-1]:
                raise ValueError("Result frames must have unique, increasing timestamps.")
            times.append(time)
            if "depth" not in frame:
                raise ValueError("Every frame needs an exported model depth raster.")
            item = {"time": time.isoformat(), "fields": {}}
            reference = None
            for field in ["depth", "wse", "velocity"]:
                if field not in frame:
                    continue
                source = (base / frame[field]).resolve()
                with rasterio.open(source) as src:
                    grid = (src.crs, src.transform, src.width, src.height)
                    if reference is not None and grid != reference:
                        raise ValueError("Depth, WSE and velocity must share an identical grid.")
                    reference = grid
                    if common_grid is None:
                        common_grid = grid
                    elif common_grid != grid:
                        raise ValueError("All result frames must use the same spatial grid.")
                    if field == "depth" and np.any(src.read(1, masked=True).compressed() < 0):
                        raise ValueError("Depth contains negative valid values. Declare nodata correctly.")
                name = f"{index:05d}-{field}"
                bounds = raster_overlay(source, folder / f"{name}.png", field, legend[field])
                shutil.copy2(source, folder / f"{name}.tif")
                item["fields"][field] = {"url": f"/outputs/{result_id}/{name}.png", "raster_url": f"/outputs/{result_id}/{name}.tif", "bounds": bounds, "sha256": file_hash(source), "overlay_sha256": file_hash(folder / f"{name}.png")}
            output_frames.append(item)
        hydrographs = read_hydrographs(base / config["gauges_csv"]) if config.get("gauges_csv") else []
        for graph in hydrographs:
            if any(not scenario.time.start <= datetime.fromisoformat(p["time"]) <= scenario.time.end for p in graph["samples"]):
                raise ValueError("Gauge samples must lie inside the scenario window.")
        extent = None
        if config.get("validation_extent"):
            spec = config["validation_extent"]
            t = datetime.fromisoformat(spec["time"].replace("Z", "+00:00"))
            if t not in times or not spec.get("source"):
                raise ValueError("Extent validation requires a source and an exact matching frame time.")
            modeled = base / frames[times.index(t)]["depth"]
            with rasterio.open(base / spec["path"]) as obs, rasterio.open(modeled) as sim:
                if (obs.crs, obs.transform, obs.width, obs.height) != (sim.crs, sim.transform, sim.width, sim.height):
                    raise ValueError("Validation extent and depth must have an identical grid; reproject independently first.")
                o, m = obs.read(1, masked=True), sim.read(1, masked=True)
                extent = {**extent_metrics(o.filled(0) > 0, m.filled(0) > 0.05, ~(np.ma.getmaskarray(o) | np.ma.getmaskarray(m))), "time": spec["time"], "source": spec["source"]}
            bounds = raster_overlay(base / spec["path"], folder / "observed-extent.png")
            extent["overlay"] = {"url": f"/outputs/{result_id}/observed-extent.png", "bounds": bounds}
        gauges_pass = bool(scenario.validation.gauge_ids) and all(any(g["station_id"] == station and g["metrics"]["nse"] is not None and g["metrics"]["nse"] >= scenario.validation.target_nse and g["metrics"]["kge"] is not None and g["metrics"]["kge"] >= scenario.validation.target_kge for g in hydrographs) for station in scenario.validation.gauge_ids)
        extent_pass = extent is not None and extent["csi"] is not None and extent["csi"] >= scenario.validation.target_csi
        result = {"schema_version": 1, "id": result_id, "scenario_sha256": digest, "scenario": scenario.model_dump(mode="json"),
                  "engine": config["engine"], "terrain_sha256": config["terrain_sha256"], "vertical_datum": config["vertical_datum"],
                  "provenance": config["provenance"], "units": config["units"], "frames": output_frames, "hydrographs": hydrographs,
                  "extent_validation": extent, "legend": legend, "validation_passed": gauges_pass and extent_pass,
                  "validation_status": "targets met; independent model review still required" if gauges_pass and extent_pass else "unvalidated or targets not met"}
        write_json(folder / "manifest.json", result)
        return result
    except Exception:
        # Do not expose partially published output via the results index.
        raise
