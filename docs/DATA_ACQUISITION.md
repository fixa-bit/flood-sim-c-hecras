# Nowshera data acquisition — 20 October 2026

Follow-up: the [upstream study record](STUDY_PROGRESS.md) adds a computed HEC-HMS routing calibration, NOAA SMOPS moisture and GSOD rainfall candidates, and the actual river/terrain view. These additions have explicit acceptance results; the moisture and rainfall candidates are not accepted forcings, and the routing model failed its withheld KGE target.

`D:\Projects\flood simulator` was checked recursively (excluding installed packages, Git internals and npm caches). It contains the older simulator source and browser cache code, but no HEC-RAS/HMS projects, terrain GeoTIFFs, soil/rainfall rasters, gauge CSVs or model outputs. Its browser terrain loader also has explicit synthetic fallbacks; these were not imported as real study data.

Public real data were downloaded into:

```text
D:\Projects\flood sim cursor\workspace\downloads\nowshera-2022
```

The six prepared layers are registered in `workspace/assets.json`, so the lab's Data & provenance view picks them up after refresh. The app displays the actual registered product, source, license and acquisition notes, including fallback products and review limitations.

| Input | Downloaded artifact in `prepared/` | Source / important interpretation |
| --- | --- | --- |
| Bare-earth terrain | `fabdem-nowshera-30m-aligned.tif` | Four native 30 m tiles from [Bristol FABDEM v1.2](https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn/); source grid preserved; no synthetic filling. CC BY-NC-SA 4.0. |
| Land cover | `worldcover-2021-nearest-30m.tif` | [ESA WorldCover 2021 v200](https://esa-worldcover.org/en/data-access), sampled from native 10 m COGs using nearest-neighbor categories. CC BY 4.0. This is not a calibrated Manning map. |
| River network | `hydrorivers-upper-kabul.geojson` | [HydroRIVERS v1.0](https://www.hydrosheds.org/products/hydrorivers), covering Warsak, Nowshera and the adjacent upper Kabul region. HydroSHEDS license and attribution apply. This is the documented fallback to MERIT. |
| Candidate catchment | `hydrobasins-nowshera-candidate.geojson` | [HydroBASINS v1c](https://www.hydrosheds.org/products/hydrobasins), union of 119 upstream level-8 subbasins. The containing subbasin's outlet is not necessarily the gauge: exact gauge delineation remains to be reviewed. |
| Surface soil properties | `soilgrids-0-5cm-raw-properties.tif` | [ISRIC SoilGrids](https://isric.org/explore/soilgrids/), four raw bands: sand, clay, soil organic carbon, bulk density, at 0–5 cm. CC BY 4.0. Unit conversion, deeper soil profile and pedotransfer/infiltration parameters remain to be prepared. |
| Historical rainfall | `chirps-v2-kabul-catchment-daily-20220820-20220904.tif` | [UCSB CHIRPS v2.0 final daily archive](https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05/2022/), 16 daily bands covering the buffered candidate full upstream catchment, rather than only the local hydraulic domain. Correct temporal interpretation and bias correction remain required. |

Original downloaded sources are retained under `raw/`. `acquisition.json` preserves provider URLs, licenses, raster statistics, hashes and limitations. `scenario.json` is a generated data-preparation scenario bound to the actual DEM hash and CHIRPS product; it is not a calibrated engine project.

## Official historical gauge evidence

Seventeen [Federal Flood Commission](https://www.ffc.gov.pk/) daily flood situation reports, dated **20 August through 5 September 2022**, are saved under `references/daily-ffc/`, with extracted text beside the original PDFs. The [28 August report](https://www.ffc.gov.pk/wp-content/uploads/2022/08/DFSR-28-08-2022-1.pdf) provides an independently accessible example.

Files:

- `references/ffc-bulletin-index.json`: each document's URL, hash and extraction status.
- `references/ffc-gauge-snapshots-20220820-20220905.csv`: **236** transcribed daily snapshots across **14** stations, including Warsak, Nowshera, Tarbela, Mangla, Marala, Munda and Chakdara. Rows preserve page, source line, original cusecs, converted m³/s and the reported local time.
- `references/ffc-observed-gauges-review-required.csv`: normalized observed-data columns for later alignment with real modeled discharge; simulated values remain blank.

The extractor uses the **current Outflow** column rather than previous-year flows or historical peaks. Reported 0600 local snapshots are represented as 0100 UTC, with the PKT assumption retained explicitly. Two Nowshera entries in the 20/21 August source documents use ambiguous period-separated values (`61.000` and `60.000`); they are omitted instead of silently changing them to thousands. These CSV transcriptions require visual review and are not registered as complete model boundary hydrographs. In particular, daily snapshots do not capture event peaks or resolve all tributary/lateral contributions.

## Verification and remaining requirements

Run:

```powershell
.\.venv\Scripts\python.exe -m server.verify_data
```

`data-verification.json` records source hash checks, finite raster values, CRS/domain coverage, expected categorical classes, native terrain grid alignment, unique gauge timestamps, SI conversions, and actual domain clipping/snap. No synthetic data are inserted when a provider input is unavailable.

SMAP/ERA5-Land initial moisture is still missing. This machine has no configured Earthdata token/netrc or CDS API configuration. [NASA requires Earthdata authentication for science files](https://nsidc.org/data/user-resources/help-center/understanding-nsidc-daac-earthdata-cloud-s3-buckets-and-paths), and [CDS requires an account/API key and dataset terms](https://cds.climate.copernicus.eu/en/how-to-api). Credentials should be configured with the provider, not pasted into the repository.

MERIT-Hydro itself requires [registration and an issued download password](https://global-hydrodynamics.github.io/MERIT_Hydro/); the public HydroSHEDS fallback was acquired instead. A calibrated Nowshera HEC-RAS/HMS model, complete reviewed upstream boundary conditions, and a matched independent satellite flood extent are still required. The public [2022 Copernicus rapid-mapping activations](https://mapping.emergency.copernicus.eu/news/information-bulletin-162-the-copernicus-emergency-management-service-monitors-the-flooding-event-in-pakistan/) cover southern areas, so they were not mislabeled as Nowshera validation.

## Reproduce downloads

```powershell
.\.venv\Scripts\python.exe -m pip install -r server\requirements-data.txt
.\.venv\Scripts\python.exe -m server.acquire
.\.venv\Scripts\python.exe -m server.acquire_bulletins
```

The data helper downloads only required FABDEM/HydroBASINS ZIP members and bounded WorldCover windows; completed source artifacts are retained for repeat runs. Large data and provider access files stay outside Git under ignored `workspace/`.
