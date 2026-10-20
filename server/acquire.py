"""Acquire real, public Nowshera inputs. Missing observations stay missing.

Run `python -m server.acquire --help`. Downloads are resumable by completed
artifact; provenance and failures are recorded under workspace/downloads/.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import gzip
from html.parser import HTMLParser
import json
import math
import re
import shutil
import time
from pathlib import Path

import httpx
import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from shapely.geometry import Point, mapping, shape
from shapely import from_wkb, union_all

from .cli import register
from .domain import bounds_for
from .models import Scenario
from .store import ROOT, assets, file_hash, read_json, write_json

BASE = ROOT / "downloads" / "nowshera-2022"
FABDEM = "https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/N30E070-N40E080_FABDEM_V1-2.zip"
HYDRO_RIVERS_PAGE = "https://www.hydrosheds.org/products/hydrorivers"
HYDRO_BASINS_PAGE = "https://www.hydrosheds.org/products/hydrobasins"
GEO_BOUNDS = [71.72, 33.79, 72.24, 34.23]  # buffer around the 20 km pilot clip
HTTP_TIMEOUT = httpx.Timeout(90, connect=20)


def announce(message):
    print(message, flush=True)


def download(url: str, path: Path, max_bytes=1_000_000_000):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size:
        return path
    partial = path.with_suffix(path.suffix + ".part")
    for attempt in range(3):
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=HTTP_TIMEOUT, headers={"User-Agent": "IndusLabResearch/1.0 (public scientific input acquisition)"}) as response:
                response.raise_for_status()
                if int(response.headers.get("content-length", 0)) > max_bytes:
                    raise ValueError(f"Download exceeds the {max_bytes:,}-byte source limit.")
                count = 0
                with partial.open("wb") as target:
                    for block in response.iter_bytes(1024 * 1024):
                        count += len(block)
                        if count > max_bytes:
                            raise ValueError("Download exceeded its size limit.")
                        target.write(block)
            partial.replace(path)
            return path
        except (httpx.HTTPError, OSError):
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def raster_record(path: Path):
    with rasterio.open(path) as src:
        sample = src.read(masked=True)
        if sample.count() == 0:
            raise ValueError(f"{path.name} contains no valid data.")
        return {"path": str(path), "sha256": file_hash(path), "crs": str(src.crs), "bounds": list(src.bounds),
                "shape": list(sample.shape), "valid_fraction": float(sample.count() / sample.size),
                "minimum": float(sample.min()), "maximum": float(sample.max()), "band_descriptions": list(src.descriptions)}


def save_mosaic(sources, output, bounds, resolution=None, dtype=None, nodata=None):
    output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.Env(GDAL_HTTP_TIMEOUT=60, GDAL_HTTP_CONNECTTIMEOUT=15, GDAL_HTTP_MAX_RETRY=1,
                      GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", VSI_CACHE=True):
        readers = [rasterio.open(str(source)) for source in sources]
        try:
            if resolution is None:
                window = from_bounds(*bounds, transform=readers[0].transform)
                left, top = math.floor(window.col_off), math.floor(window.row_off)
                right, bottom = math.ceil(window.col_off + window.width), math.ceil(window.row_off + window.height)
                bounds = rasterio.windows.bounds(rasterio.windows.Window(left, top, right - left, bottom - top), readers[0].transform)
            image, affine = merge(readers, bounds=bounds, res=resolution, resampling=Resampling.nearest, nodata=nodata, dtype=dtype)
            if image.size > 16_000_000:
                raise ValueError("Prepared mosaic exceeds 16 million values.")
            profile = readers[0].profile.copy()
            profile.update(driver="GTiff", width=image.shape[2], height=image.shape[1], count=image.shape[0],
                           transform=affine, dtype=str(image.dtype), tiled=True, blockxsize=256, blockysize=256, compress="deflate")
            if nodata is not None:
                profile["nodata"] = nodata
            with rasterio.open(output, "w", **profile) as target:
                target.write(image)
        finally:
            for reader in readers:
                reader.close()
    return raster_record(output)


def zip_subset(url, folder, predicate):
    from remotezip import RemoteZip
    folder.mkdir(parents=True, exist_ok=True)
    output = []
    # Only selected archive members are transferred. ZIP CRC is checked on read.
    with RemoteZip(url, timeout=90) as archive:
        for info in archive.infolist():
            if not predicate(info.filename):
                continue
            path = folder / Path(info.filename).name
            output.append(path)
            if path.is_file() and path.stat().st_size == info.file_size:
                continue
            announce(f"Extracting public source member {info.filename} ({info.compress_size / 1e6:.1f} MB compressed)")
            partial = path.with_suffix(path.suffix + ".part")
            with archive.open(info) as source, partial.open("wb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
            partial.replace(path)
    if not output:
        raise ValueError("No expected members found in the provider archive.")
    return output


def fabdem():
    output = BASE / "prepared" / "fabdem-nowshera-30m-aligned.tif"
    if not output.exists():
        prefixes = ("N33E071", "N33E072", "N34E071", "N34E072")
        tiles = zip_subset(FABDEM, BASE / "raw" / "fabdem", lambda name: Path(name).name.startswith(prefixes) and name.lower().endswith(".tif"))
        save_mosaic(tiles, output, GEO_BOUNDS, nodata=-9999)
    return {"kind": "dem", "product": "FABDEM v1.2 ~30 m", "source": FABDEM,
            "license": "CC BY-NC-SA 4.0; commercial license separately", **raster_record(output),
            "notes": "Bare-earth source tiles mosaicked without synthetic filling; gauge bed/bathymetry and vertical datum still require model review."}


def worldcover():
    output = BASE / "prepared" / "worldcover-2021-nearest-30m.tif"
    urls = [f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N33E{longitude:03d}_Map.tif" for longitude in [69, 72]]
    if not output.exists():
        save_mosaic(urls, output, GEO_BOUNDS, resolution=1 / 3600, dtype="uint8", nodata=0)
    return {"kind": "landcover", "product": "ESA WorldCover 2021 v200; categorical nearest-neighbor ~30 m clip", "source": "https://esa-worldcover.org/en/data-access",
            "license": "CC BY 4.0", "source_urls": urls, **raster_record(output),
            "notes": "Native 10 m classes sampled to the terrain-scale grid. This is not an assigned Manning-n map; roughness lookup and calibration remain required."}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.urls += [value for key, value in attrs if key == "href" and value]


def hydro_url(page, token):
    response = httpx.get(page, follow_redirects=True, timeout=45)
    response.raise_for_status()
    parser = Links()
    parser.feed(response.text)
    matches = [url for url in parser.urls if "data.hydrosheds.org" in url and token.lower() in url.lower() and url.endswith(".zip")]
    if not matches:
        raise ValueError(f"Provider page no longer advertises the expected {token} archive.")
    return matches[0]


def hydrography():
    import pyogrio
    output = BASE / "prepared" / "hydrorivers-upper-kabul.geojson"
    source = hydro_url(HYDRO_RIVERS_PAGE, "HydroRIVERS_v10_as_shp")
    if not output.exists():
        archive = download(source, BASE / "raw" / "hydrorivers-asia.zip")
        folder = BASE / "raw" / "hydrorivers"
        if not list(folder.glob("**/*.shp")):
            import zipfile
            with zipfile.ZipFile(archive) as zipped:
                resolved = folder.resolve()
                if any(not (resolved / name).resolve().is_relative_to(resolved) for name in zipped.namelist()):
                    raise ValueError("Provider archive contains a path outside the extraction folder.")
                zipped.extractall(folder)
        layer = next(folder.glob("**/*.shp"))
        meta, _, geometry, data = pyogrio.raw.read(layer, bbox=(71.15, 33.7, 72.4, 34.45))
        features = []
        for index, item in enumerate(geometry):
            properties = {name: values[index].item() if hasattr(values[index], "item") else values[index] for name, values in zip(meta["fields"], data)}
            features.append({"type": "Feature", "properties": properties, "geometry": mapping(from_wkb(item))})
        if not features:
            raise ValueError("Provider river data does not intersect the upper Kabul study region.")
        write_json(output, {"type": "FeatureCollection", "features": features})
    return {"kind": "hydrography", "product": "HydroRIVERS v1.0, upper Kabul / Warsak / Nowshera", "source": source,
            "license": "HydroSHEDS license in its Technical Documentation; retain Lehner & Grill (2013) and WWF attribution", "path": str(output), "sha256": file_hash(output),
            "notes": "HydroSHEDS fallback to MERIT; line geometry supports snapping, not riverbed or structure geometry."}


def catchment():
    import pyogrio
    output = BASE / "prepared" / "hydrobasins-nowshera-candidate.geojson"
    source = hydro_url(HYDRO_BASINS_PAGE, "hybas_as_lev01-12_v1c")
    if not output.exists():
        members = zip_subset(source, BASE / "raw" / "hydrobasins", lambda name: "lev08" in name and Path(name).suffix.lower() in {".shp", ".shx", ".dbf", ".prj"})
        layer = next(path for path in members if path.suffix.lower() == ".shp")
        meta, _, geometry, fields = pyogrio.raw.read(layer, columns=["HYBAS_ID", "NEXT_DOWN", "SUB_AREA", "UP_AREA"])
        table = dict(zip(meta["fields"], fields))
        geoms = from_wkb(geometry)
        matches = [i for i, geom in enumerate(geoms) if geom.covers(Point(71.978, 34.0095))]
        if not matches:
            raise ValueError("No HydroBASINS polygon contains the pilot coordinate.")
        outlet_index = min(matches, key=lambda i: table["SUB_AREA"][i])
        upstream = {}
        for index, next_id in enumerate(table["NEXT_DOWN"]):
            upstream.setdefault(int(next_id), []).append(index)
        selected = {outlet_index}
        queue = [outlet_index]
        while queue:
            current = queue.pop()
            for index in upstream.get(int(table["HYBAS_ID"][current]), []):
                if index not in selected:
                    selected.add(index)
                    queue.append(index)
        basin = union_all(geoms[list(selected)])
        properties = {"source": source, "hybas_id": int(table["HYBAS_ID"][outlet_index]), "level": 8,
                      "subbasin_count": len(selected), "summed_subbasin_area_km2": float(sum(table["SUB_AREA"][i] for i in selected)),
                      "review_required": True, "outlet_exact": False,
                      "note": "Candidate union to the containing level-8 subbasin outlet. That outlet is not necessarily the gauge; exact gauge delineation is still required."}
        write_json(output, {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": properties, "geometry": mapping(basin)}]})
    return {"kind": "catchment", "product": "HydroBASINS v1c level-8 candidate upstream union — REVIEW REQUIRED", "source": source,
            "license": "HydroSHEDS license in its Technical Documentation; retain Lehner & Grill (2013) and WWF attribution", "path": str(output), "sha256": file_hash(output),
            "notes": "Candidate upstream extent, not exact gauge delineation. Do not use it as a reviewed model catchment without checking the outlet and all tributaries."}


def chirps():
    candidate = BASE / "prepared" / "hydrobasins-nowshera-candidate.geojson"
    if not candidate.exists():
        raise ValueError("Download the candidate upstream catchment first so rainfall covers the full contributing region.")
    upstream_bounds = shape(read_json(candidate)["features"][0]["geometry"]).bounds
    rainfall_bounds = [upstream_bounds[0] - 0.1, upstream_bounds[1] - 0.1, upstream_bounds[2] + 0.1, upstream_bounds[3] + 0.1]
    output = BASE / "prepared" / "chirps-v2-kabul-catchment-daily-20220820-20220904.tif"
    dates = [(datetime(2022, 8, 20) + timedelta(days=i)).date() for i in range(16)]
    sources = [f"https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05/2022/chirps-v2.0.{day:%Y.%m.%d}.tif.gz" for day in dates]
    if not output.exists():
        profile, bands = None, []
        for day, url in zip(dates, sources):
            archive = download(url, BASE / "raw" / "chirps" / Path(url).name, max_bytes=50_000_000)
            raster_path = archive.with_suffix("")
            if not raster_path.exists():
                with gzip.open(archive, "rb") as src, raster_path.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            with rasterio.open(raster_path) as src:
                window = from_bounds(*rainfall_bounds, transform=src.transform).round_offsets().round_lengths()
                # Expand to complete pixel boundaries so the pilot clip is covered.
                window = rasterio.windows.Window(window.col_off - 1, window.row_off - 1, window.width + 2, window.height + 2)
                bands.append(src.read(1, window=window))
                profile = src.profile.copy()
                profile.update(driver="GTiff", transform=src.window_transform(window), height=bands[-1].shape[0], width=bands[-1].shape[1], count=len(dates), compress="deflate")
        output.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output, "w", **profile) as dst:
            dst.write(np.stack(bands))
            for index, day in enumerate(dates, 1):
                dst.set_band_description(index, f"{day.isoformat()} daily precipitation / mm")
                dst.update_tags(index, date=day.isoformat(), units="mm/day", temporal_support="daily; read the CHIRPS2 day-definition documentation")
    return {"kind": "rainfall", "product": "CHIRPS v2.0 final daily, 2022-08-20 through 2022-09-04", "source": "https://www.chc.ucsb.edu/data/chirps",
            "license": "CC BY 4.0; cite Funk et al. (2015) and UCSB CHC", "source_urls": sources, **raster_record(output),
            "notes": "Historical satellite/gauge rainfall estimate over the buffered candidate full upstream catchment bounds, not GPM or observed station discharge. Catchment review, hydrologic bias correction and temporal alignment remain required."}


def soils():
    output = BASE / "prepared" / "soilgrids-0-5cm-raw-properties.tif"
    variables = ["sand", "clay", "soc", "bdod"]
    sources = [f"https://maps.isric.org/mapserv?map=/map/{prop}.map&SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage&COVERAGEID={prop}_0-5cm_mean&FORMAT=image/tiff&SUBSET=Long({GEO_BOUNDS[0]},{GEO_BOUNDS[2]})&SUBSET=Lat({GEO_BOUNDS[1]},{GEO_BOUNDS[3]})&SUBSETTINGCRS=http://www.opengis.net/def/crs/EPSG/0/4326&OUTPUTCRS=http://www.opengis.net/def/crs/EPSG/0/4326" for prop in variables]
    if not output.exists():
        arrays, reference, profile = [], None, None
        for prop, url in zip(variables, sources):
            path = download(url, BASE / "raw" / "soil" / f"{prop}-0-5cm.tif", max_bytes=20_000_000)
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
            for index, prop in enumerate(variables, 1):
                dst.set_band_description(index, f"{prop}_0-5cm_mean / native SoilGrids units")
    return {"kind": "soil", "product": "SoilGrids 2.0, raw sand/clay/SOC/bulk-density, 0–5 cm", "source": "https://isric.org/explore/soilgrids/",
            "license": "CC BY 4.0; retain ISRIC attribution", "source_urls": sources, **raster_record(output),
            "notes": "Raw modeled surface-soil properties only. Apply documented unit conversion and pedotransfer; these are not Ksat/porosity/Green-Ampt parameters and do not represent the full soil profile."}


def bulletins():
    from pypdf import PdfReader
    url = "https://www.ffc.gov.pk/wp-content/uploads/2022/08/DFSR-28-08-2022-1.pdf"
    path = download(url, BASE / "references" / "FFC-DFSR-2022-08-28.pdf", max_bytes=20_000_000)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    (path.with_suffix(".txt")).write_text(text, encoding="utf-8")
    return {"kind": None, "product": "Official FFC daily flood situation report, 2022-08-28", "source": url,
            "license": "Government of Pakistan FFC publication; retain attribution, verify reuse terms", "path": str(path), "sha256": file_hash(path),
            "notes": "Official documentary evidence; not a full time-series hydrograph. No inflow asset is fabricated from this report."}


TASKS = {"fabdem": fabdem, "worldcover": worldcover, "hydrography": hydrography, "catchment": catchment,
         "chirps": chirps, "soil": soils, "bulletins": bulletins}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tasks", nargs="*", help="Providers: " + ", ".join(TASKS) + ". Default: all public providers")
    parser.add_argument("--workers", type=int, default=3, choices=[1, 2, 3])
    args = parser.parse_args()
    if any(key not in TASKS for key in args.tasks):
        parser.error("Unknown provider; choose from " + ", ".join(TASKS))
    BASE.mkdir(parents=True, exist_ok=True)
    report_path = BASE / "acquisition.json"
    report = read_json(report_path, {"searched_directory": "D:/Projects/flood simulator", "local_model_or_data_files_found": 0, "providers": {}})
    report["updated_at"] = datetime.now(timezone.utc).isoformat()

    def record_provider(key, result=None, error=None):
        if error is not None:
            report["providers"][key] = {"state": "unavailable", "reason": str(error)}
            announce(f"UNAVAILABLE {key}: {error}")
        else:
            if result["kind"]:
                item = register(result["kind"], Path(result["path"]), result["source"], result["license"], result["product"])
                item["acquisition"] = {k: v for k, v in result.items() if k not in {"path", "kind"}}
                catalog = assets()
                catalog[result["kind"]] = item
                write_json(ROOT / "assets.json", catalog)
            report["providers"][key] = {"state": "downloaded-and-checked", **result}
            announce(f"READY {key}: {result['path']}")
        write_json(report_path, report)

    requested = list(dict.fromkeys(args.tasks or TASKS))
    # CHIRPS clipping depends on the actual upstream extent. Finish the candidate
    # catchment before reading its bounds, including on the first clean download.
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(TASKS[key]): key for key in requested if key != "chirps"}
        for future in as_completed(futures):
            key = futures[future]
            try:
                record_provider(key, result=future.result())
            except Exception as exc:
                record_provider(key, error=exc)
    if "chirps" in requested:
        try:
            record_provider("chirps", result=TASKS["chirps"]())
        except Exception as exc:
            record_provider("chirps", error=exc)
    report["not_downloaded"] = {
        "moisture": "SMAP / ERA5-Land access or a documented alternate product is required; no placeholder raster generated.",
        "inflow": "Complete timestamped Warsak and tributary/lateral hydrographs have not been located; a daily PDF is not a calibrated boundary series.",
        "hec_project": "No calibrated Nowshera HEC-RAS/HEC-HMS project is bundled with public data products.",
        "validation": "An exact-time independent flood extent is still missing. Downloaded daily FFC gauge transcriptions require visual review and do not replace full boundary/validation series."}
    catalog = assets()
    if catalog.get("dem"):
        example = Path(__file__).resolve().parents[1] / "examples" / "nowshera-2022.json"
        scenario = Scenario.model_validate_json(example.read_text(encoding="utf-8"))
        scenario.domain.dem_sha256 = catalog["dem"]["sha256"]
        if catalog.get("rainfall", {}).get("product", "").startswith("CHIRPS"):
            scenario.forcing.rainfall_product = "CHIRPS"
        scenario.provenance.notes += " Public raw inputs acquired; candidate catchment, rainfall correction and soil/Manning parameters require review. No calibrated hydraulic model or complete boundary series is implied."
        write_json(BASE / "scenario.json", scenario.model_dump(mode="json"))
        report["generated_scenario"] = str(BASE / "scenario.json")
    write_json(report_path, report)
    announce(f"Acquisition report: {report_path}")


if __name__ == "__main__":
    main()
