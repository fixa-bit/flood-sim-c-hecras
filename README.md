# Flood Simulation — Pakistan flood scenarios

A local research workspace for upstream-first flood scenario preparation and georeferenced **external model output**. Nowshera is the first hydraulic pilot, with Warsak upstream and the Kabul–Indus connection at Attock downstream. Tarbela, Kohala, Akhnur and Marala are useful planning starting points. The full 29-station catalog is a reference; hydraulic compute stays limited to Nowshera until the pilot is proven.

**This is a working preparation, engine-handoff and result-review application. An upstream HEC-HMS routing experiment has been computed and fitted, but failed its withheld KGE target. It does not yet contain an accepted calibrated 2-D Nowshera model or validated 2022 flood output.** Check [every plan point and remaining requirement](docs/IMPLEMENTATION_CHECKLIST.md). The [original Cursor plan](examples/cursor-plan.txt) is preserved.

**Public input data have now been acquired:** FABDEM, WorldCover, HydroRIVERS, a candidate HydroBASINS catchment, SoilGrids, full-catchment CHIRPS rainfall, and 17 official FFC reports with review-required gauge transcriptions. See the [download inventory, file locations and remaining access requirements](docs/DATA_ACQUISITION.md). Raw inputs and sparse observations do not replace a calibrated model or independent validation.

## Quick start (Windows)

Node 24+ and Python 3.11+ are required. In PowerShell, from this checkout:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # current PowerShell session only
.\scripts\setup.ps1   # first time: .venv, Python/Node packages, Chromium
.\scripts\dev.ps1     # starts the API (8010) and the app (5174)
```

Open **http://127.0.0.1:5174**. The API runs on **8010**; ports 5173/8000 may belong to other projects. Setup creates an isolated `.venv`, installs packages and Chromium, and keeps download caches and temporary files on the project drive. `server/requirements.txt` defines the supported top-level dependencies; `requirements.txt` is the exact installed package snapshot.

For separate terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8010
npm run dev -- --host 127.0.0.1
```

The local API is designed for loopback use, not public hosting. Browser drafts live in localStorage. Scientific inputs, engine projects and outputs live under ignored `workspace/`; export the JSON scenario for reproducibility. Large source datasets and licensed inputs do not belong in Git.

To transfer the current installation, use the [data and engine transfer guide](requirement_data.txt) and [exact Python package snapshot](requirements.txt). Git carries source and configuration; the ignored `workspace/` data, engine installations and computed results need a separate transfer or reproduction.

## Using the app

### Runnable public cases

**A runnable public-data 2D screening case is available:** select **Load runnable public case → Prepare & run case → Play**. The revised case uses a 100 m grid, a mapped river corridor with explicitly estimated bed depths, and 72 hours of steady-flow initialization before the displayed flood period. The external LISFLOOD-FP engine retains flow and depth continuously; warm-up frames are excluded from playback. Publication requires converged river flow, wet inlet-to-outlet connectivity and numerical checks. Surveyed bathymetry and independent flood-extent validation remain unavailable. See [model inputs, actual checks and reproduction](docs/SCREENING_MODEL.md). The original HEC-RAS example still requires its own prepared RAS project.

**A separate HEC-RAS 2D case is also available:** select **Load runnable HEC-RAS case → Prepare & run case → Play**. It uses HEC-RAS 6.6's full SWE-ELM solver, the existing HEC-HMS inflow, a 200 m mesh, estimated channel terrain, and 72 hours of initialization. Its full event has been computed and published as 385 hourly frames. See [HEC-RAS inputs, numerical checks, limitations and reproduction](docs/HECRAS_MODEL.md). Both engines have separate prepared cases and results; neither case is calibrated or independently validated.

### Example scenarios

The **Example scenarios** section above the river map loads two editable starting points: **Nowshera 2022** with upstream gauge boundaries, and **Wetter monsoon +30%** with saturated soil. Each has a separate draft ID and can be saved or exported as JSON. They load scenario inputs; hydraulic compute still requires the data and prepared model to pass readiness checks.

### Run a scenario case

**Run a scenario case** applies a case without filling each editor field. Select the current scenario, an example, or a saved draft; optionally choose a JSON file or expand **Paste or adjust case values**. A full exported scenario replaces the base. A partial object such as `{"name":"Wetter test","forcing":{"rainfall_multiplier":1.5}}` overlays those nested fields on the selected base; arrays replace entire lists. Unspecified values are inherited, not inferred from prose. The server rejects invalid or unknown fields before changing the editor. A null DEM hash uses the registered terrain; explicit hashes remain unchanged.

Choose **Load case values** to review/save the result, or **Prepare & run case** to validate, prepare its domain, check all prerequisites, and submit compute if ready. Missing requirements appear next to the runner; a blocked case never submits a job. Existing model bindings still apply only to their exact scenario and input hashes, so changing rainfall, dates, geometry or other values requires a matching prepared engine project. This automates input loading and preparation, not hydraulic model construction. Playback still requires published timestamped model rasters.

### Engine choice and your own model

**Engine for this run** lets you choose **HEC-RAS 2D** (full SWE) or **LISFLOOD-FP** (local inertial), overriding the engine in the selected case or JSON. Leave **Use engine from case or JSON** selected to preserve its engine. When a supplied public case is selected, choosing an engine selects its own prepared case, mesh and model settings. Custom drafts retain their inputs and require matching model preparation. Load the values to review the choice in **Hydraulic model → Compute engine**. For your own model, **Attach prepared model** accepts an absolute project folder, plan number (`01` for HEC-RAS) or parameter file (`screen.par` for LISFLOOD), and a model review reference. Attachment records the exact scenario, input hashes and engine. Both supplied public cases publish map rasters automatically; other projects need a documented raster exporter. Previously published public results are reused only after their raster and overlay hashes pass verification.

## What is installed in this environment

- HEC-RAS **6.6**: `D:\FloodTools\HEC-RAS-6.6\Ras.exe`, installed from the [official USACE download](https://www.hec.usace.army.mil/software/hec-ras/download.aspx), with valid Authenticode signature and successful MSI log.
- HEC-HMS **4.14** portable: `workspace/tools/hec-hms/HEC-HMS-4.14`, including its Java runtime, from [USACE](https://www.hec.usace.army.mil/software/hec-hms/downloads.aspx).
- LISFLOOD-FP **8.0.3** CPU/OpenMP build: `workspace/tools/lisflood-build/lisflood.exe`, from the [official 8.0 archive](https://zenodo.org/records/4073011). Archive MD5 matches `00602cbba617a50a34478495d2688add`. NetCDF/CUDA are disabled. A portability change in `utility.cpp` adds `__MINGW32__` to its two existing Windows allocation guards; it does not alter solver equations. LLVM-MinGW, CMake and Ninja were installed locally to build it.
- RAS Commander, Rasterio/GDAL, NumPy, PyProj, Shapely, HDF5, Pillow, FastAPI, pytest, and Playwright/Chromium.

Local engine paths are stored in ignored `workspace/runtimes.json`. On another machine, install the official tools and set `HEC_RAS_EXE`, `HEC_HMS_EXE`, and `LISFLOOD_FP_EXE`, or create the same runtime JSON keys (`hec_ras_exe`, `hec_hms_exe`, `lisflood_fp_exe`). HEC license/first-run prerequisites may need completion under the user that computes models.

The previously full C: drive prevented installation. Its pip download cache was preserved under `workspace/cache/pip-from-c` to free space; no source data was deleted.

## Scientific workflow

### 1. Define a scenario

Start with [examples/nowshera-2022.json](examples/nowshera-2022.json), or use the editor. Choose dates, domain radius, mesh, UTC output interval, rainfall product and bias correction, soil state, upstream inflows, structures, engine, and skill targets. Eight experiment families are available. A return period, release or breach label is a definition requiring real parameters in the prepared model.

FFD classes are discharge targets in lakh cusecs, converted to m³/s using `1 lakh cusecs = 2831.6846592 m³/s`. They do not define stage, hydrograph shape, arrival time or extent. Missing published classes remain missing. The [FFD source](https://ffd.pmd.gov.pk/flood-limits) was checked on 20 October 2026. Coordinates are approximate until snapped and independently reviewed.

### 2. Register real inputs

Activate the venv, or replace `python` with `.\.venv\Scripts\python.exe` in the commands below:

```powershell
.\.venv\Scripts\Activate.ps1
python -m server.cli register dem D:\data\fabdem.tif --source "Bristol FABDEM v1.2, tile IDs and date" --license "CC BY-NC-SA 4.0" --product "FABDEM v1.2"
python -m server.cli register hydrography D:\data\channels.geojson --source "MERIT-derived channel export, processing reference" --license "ODbL 1.0" --product "MERIT-Hydro"
python -m server.cli register catchment D:\data\basin.geojson --source "Reviewed upstream basin delineation" --license "Source-specific terms" --product "MERIT basin"
```

Register `soil`, `moisture`, `rainfall`, `landcover`, `inflow`, and `validation` similarly. Every registration copies the input and stores source, product, license and SHA-256. Refresh assets in the UI to bind the source DEM hash, then export the updated scenario. FABDEM's [noncommercial license](https://research-information.bris.ac.uk/en/datasets/fabdem-v1-2/) must be respected; commercial use needs separate licensing. MERIT offers [CC BY-NC or ODbL terms](https://global-hydrodynamics.github.io/MERIT_Hydro/).

Raster inputs are georeferenced GeoTIFFs. Hydrography is RFC 7946 WGS84 LineString/MultiLineString FeatureCollection; catchments are Polygon/MultiPolygon FeatureCollections. The basin must represent the **full contributing upstream catchment**. The study rectangle is a bounded hydraulic clip, not a watershed.

Boundary CSV columns:

```csv
time,station_id,discharge_m3s,source,value_type
```

Use timezone-bearing ISO timestamps, m³/s, a documentary source, and `observed` or `modeled`. Each selected upstream boundary must span the scenario window. No sample discharges are supplied. Other tributary/lateral contributions belong in the reviewed external model. Google virtual gauges are estimates, not FFD observations.

Public STAC COG ingestion clips only the requested domain:

```powershell
python -m server.cli stac-import scenario.json https://provider.example/stac/item.json elevation --kind dem --license "Provider license"
```

The example URL is a placeholder; use the actual item's asset key and declared source. Authenticated NASA/GEE downloads require your provider access outside this adapter. SoilGrids pedotransfer, rainfall bias adjustment and roughness lookup must be documented in the prepared hydrology/hydraulic project.

### 3. Prepare domain and hydrology

```powershell
python -m server.cli domain scenario.json
python -m server.cli preflight scenario.json
```

The service snaps within 2 km of supplied real channels, clips rasters in their native CRS, checks complete coverage, enforces a memory limit, and caches artifacts by scenario and input hashes. It accepts a supplied delineated basin; it does not infer a catchment from a bounding box. Any input or scenario edit invalidates corresponding preparation.

For a reviewed HEC-HMS project with an existing simulation run:

```powershell
python -m server.cli compute-hms scenario.json D:\models\Kabul\Kabul.hms --run "2022 event" --installation "D:\Projects\flood sim cursor\workspace\tools\hec-hms\HEC-HMS-4.14" --review "Study report section: basin, meteorology, infiltration, transform, routing, controls and calibration"
```

It runs HMS in a private project copy using the bundled Java/Jython API. Review logs and export its DSS hydrographs to the documented SI boundary CSV. An installed engine does not create, calibrate or verify a basin model. Rain-on-grid also requires prepared infiltration, rainfall and moisture inputs in the hydraulic project.

### 4. Bind and compute hydraulics

Prepare mesh, terrain, structures, boundary conditions, timestep, infiltration and outputs in HEC-RAS 2D (full SWE). The same hydrology can feed a LISFLOOD-FP ACC screening project. Bind the exact reviewed project to the exported scenario:

```powershell
python -m server.cli bind scenario.json D:\models\Nowshera --plan 01 --review "Reviewed study/model reference including boundary mapping, datum, mesh, structures, stability and mass balance"
```

For LISFLOOD, `--plan` names the prepared `.par` file inside its project directory. The worker does not edit an unrelated engine model to guess how a changed scenario should be applied. Re-prepare and bind after edits. The app's readiness check verifies actual source hashes, full time coverage, domain artifacts, runtime availability, model binding and unchanged project files. A private compute copy preserves the original project. Computed is distinct from published and validated.

### 5. Export and publish results

HEC-RAS writes [native mesh fields to HDF5](https://www.hec.usace.army.mil/confluence/rasdocs/r2dum/6.4/viewing-2d-or-1d-2d-output-using-hec-ras-mapper/2d-output-file-hdf5-binary-file). Inspect fields with:

```powershell
python -m server.cli inspect-hdf D:\models\Nowshera\Nowshera.p01.hdf
```

Export timestamped depth, water surface and optional speed GeoTIFFs from RAS Mapper or a documented external exporter. Convert US customary units to SI before publication. Do not treat face-normal velocities as cell speeds. Preserve CRS and vertical datum, and use a common grid across fields and frames.

Create an export manifest beside the rasters with this structure, replacing placeholders:

```json
{
  "scenario": { "...": "complete exported schema-v1 scenario object" },
  "engine": "HEC-RAS 2D",
  "terrain_sha256": "SHA-256 of the prepared domain DEM clip, not the source mosaic",
  "units": { "depth": "m", "wse": "m", "velocity": "m/s" },
  "vertical_datum": "documented datum shared with terrain",
  "provenance": {
    "model_run": "engine version, project/run ID, review reference and source output hash"
  },
  "frames": [
    {
      "time": "2022-08-20T00:00:00Z",
      "depth": "depth-000.tif",
      "wse": "wse-000.tif",
      "velocity": "speed-000.tif"
    }
  ],
  "gauges_csv": "aligned-gauges.csv",
  "validation_extent": {
    "path": "observed-extent.tif",
    "time": "2022-08-20T00:00:00Z",
    "source": "Exact satellite product ID, date, preprocessing and validation provenance"
  }
}
```

`gauges_csv`, `validation_extent`, WSE and velocity are optional. Depth and genuine model provenance are required. Gauge CSV columns are `time,station_id,observed_m3s,simulated_m3s` with optional `lower_m3s,upper_m3s`. Missing values are blank. Extent pixels are 0=dry, positive=observed wet, declared nodata=unknown. Align its grid independently and use the exact acquisition/model time.

```powershell
python -m server.cli publish export.json
```

Publication checks scenario/terrain/engine agreement, SI declarations, timestamps and grids; creates bounded PNG overlays and retains original GeoTIFFs. It computes scores only from supplied independent data. NSE/KGE are null for insufficient/constant observations. The observed mask is shown only at its acquisition time. A result meets targets only if **every named gauge** and the independent flood extent pass; passing scores still require model review.

### 6. Playback and compare

Refresh the workspace, select **Model results**, choose HEC-RAS as **Result A** and LISFLOOD as **Compare B**. The default comparison requires exact timestamps. For the supplied cases choose **Compare times → Nearest frame within 60 seconds**, since LISFLOOD's adaptive steps produce timestamps a few seconds after the hour. The A/B split slider compares the original rasters on the same map; actual A/B timestamps and the signed offset are shown beneath it. No temporal interpolation or retimestamping is performed, and a frame farther than 60 seconds away remains missing. The main timeline and hydrograph follow A. Imported uncertainty bounds are displayed without inventing an ensemble. The viewer renders depth/WSE/speed rasters and never computes water. The supplied cases differ in mesh spacing, roughness and boundary extent; their differences are not solely an engine comparison.

**Playback controls:** choose **1× / 4× / 16×** beside the timeline (1× shows one frame every 0.8 s). When focus is not in a form field, **Space** plays or pauses, **← / →** step one frame and **Shift + ← / →** step ten. Depth and speed use fixed legend bins. Water-surface (WSE) bins are fitted to each result: five equal classes across the 2nd–98th percentile of its WSE values, stored as `legend` in the result manifest. Results published before this change keep fixed WSE bins until restyled (see Maintenance).

### 7. Exposure and tributaries

Below a selected result, **Exposure at this model time** shows how many residents (WorldPop 2022) live in cells the model shows under ≥ 0.3 m and ≥ 1 m of water, the event peak, and which mapped health, school and emergency facilities (OpenStreetMap) are flooded. The map buttons **Population**, **Population 3D**, **Facilities** and **Tributaries** draw the same layers on the terrain. **Population 3D** raises a column of residents for every ~500 m cell that fills red from the ground as residents come under water during playback. Flooded facilities turn red with their depth. **Streams entering the model** lists every real stream crossing the model edge and whether the model gives it any water. These layers never enter a hydraulic model, and the counts are model-derived, not casualty or displacement estimates. Method, sources and findings, including the unrepresented Kalpani tributary: [exposure and tributary audit](docs/EXPOSURE_AND_TRIBUTARIES.md).

```powershell
.\.venv\Scripts\python.exe -m server.exposure acquire            # WorldPop 2022 + OSM facilities
.\.venv\Scripts\python.exe -m server.exposure compute <result-id>  # optional; the API computes on demand
.\.venv\Scripts\python.exe -m server.tributaries names            # OSM waterway names (labels only)
.\.venv\Scripts\python.exe -m server.tributaries audit <result-id>
```

### 8. Warsak below-dam site

Warsak is a second hydraulic site with its own input catalog (`workspace/sites/warsak/assets.json`); Nowshera's catalog and bindings are untouched. Terrain, land cover, rivers, catchment, soil, the below-dam model area and the mapped-water channel are prepared, and a numerical smoke test passed. The model runs once a continuous Warsak Dam release record (ordinates at most 3 hours apart) is registered; the public 2022 readings are too sparse. Selecting **Warsak** shows its own example scenario. Details: [Warsak site](docs/WARSAK_SITE.md).

```powershell
.\.venv\Scripts\python.exe -m server.warsak acquire     # inputs into the Warsak catalog
.\.venv\Scripts\python.exe -m server.warsak geometry    # domain, grid, corridor; no inflow used
.\.venv\Scripts\python.exe -m server.warsak status      # what is ready, what is missing
.\.venv\Scripts\python.exe -m server.cli register inflow <release.csv> --site warsak --source <...> --license <...> --product <...>
.\.venv\Scripts\python.exe -m server.warsak build       # condition, write and bind the LISFLOOD case
```

### 9. Warsak snapshots checked against Sentinel-1

Steady LISFLOOD runs below Warsak Dam at observed FFC releases, compared with Sentinel-1 water maps from (nearly) the same time: 25 Aug 2022 (calibration; image 16 minutes after the 59,000-cusec reading) and 5 Sep (independent validation). Roughness was swept and barely matters; the estimated channel bed is the main limit. Results publish speed and a hazard count, and the app shows the satellite score and overlay. Details: [satellite calibration](docs/SATELLITE_CALIBRATION.md).

```powershell
.\.venv\Scripts\python.exe -m server.satellite 2022-08-25 2022-09-05
.\.venv\Scripts\python.exe -m server.warsak_snapshot sweep
.\.venv\Scripts\python.exe -m server.warsak_snapshot publish
```

### 10. Observed 2022 flows

One reviewed table of measured 2022 discharges at 25 stations: FFC daily reports (06:00 inflow/outflow, 1 Jul–11 Sep) and the WAPDA river-flow workbook (daily Tarbela, Nowshera, Mangla and Marala, all of 2022). Measured values only; unreadable lines are left out and listed. The **Simulation** tab shows them as **Observed 2022 flows** for the selected station. These are once-a-day values for display and model checking, not model forcing. Details: [observed flows](docs/OBSERVED_FLOWS_2022.md).

```powershell
.\.venv\Scripts\python.exe -m server.observations acquire
.\.venv\Scripts\python.exe -m server.observations build
```

Without terrain configuration the globe explicitly uses an ellipsoid. Optional `VITE_CESIUM_ION_TOKEN` enables World Terrain as **context only**. `VITE_LOCAL_TERRAIN_URL` should point to quantized-mesh terrain built from the same prepared FABDEM clip; automatic terrain tiling is a remaining integration. Copy `.env.example` to `.env` and restart Vite. Keep credentials out of Git.

## Checks

```powershell
npx oxlint
npm run build
.\.venv\Scripts\python.exe -m pytest   # all Python tests; temp files stay under workspace\temp
# With the app and API running:
npm test
```

GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs lint, the production build and the Python tests on pushes to `main` and on pull requests. The Python tests need no `workspace/` data. Browser tests use the local workspace and engines, so they run locally only.

Tests use temporary **synthetic fixtures** and mocked imagery solely to test contracts and interaction. They do not constitute a Pakistan flood simulation, a benchmark validation, or a historical replay. No test output is shipped as real research data.

## Maintenance

```powershell
python -m server.cli restyle-wse <result-id> [<result-id> ...]
python -m server.cli prune-jobs              # dry run: lists what would be removed
python -m server.cli prune-jobs --apply
```

`restyle-wse` redraws a published result's WSE overlays with bins fitted to its own range. It first verifies every original GeoTIFF hash, changes only the derived PNGs, their hashes and the manifest `legend`, and leaves the rasters untouched.

`prune-jobs` removes job data that no current result depends on: engine copies (`model/`) whose published result is superseded or missing, and cache-hit job records older than `--older-than-days` (default 14). It never touches queued or running jobs, unpublished `computed` or `failed` jobs, or any job ID cited in `docs/`. Without `--apply` it only reports.

If the API stops while a job is queued or running, that job is marked `failed` at the next API start, with a note to resubmit.

## Public-data follow-up

The [upstream study record](docs/STUDY_PROGRESS.md) describes the HEC-HMS model actually computed, withheld validation scores, moisture/rainfall preparation and the real river/terrain viewer. The default River view centers on the Kabul channel near Nowshera with satellite imagery and local FABDEM topography. Hydraulic calibration remains open because the routing experiment did not meet all validation targets.

The [shared inflow improvement record](docs/INFLOW_IMPROVEMENT.md) adds three verified timed Warsak readings and a separate real HEC-HMS comparison. Run `python -m server.inflows all` and inspect **Data & provenance → Inflow improvement candidate**. Withheld routing KGE improves from 0.462 to 0.469; complete timed Swat/lateral evidence remains unavailable, so published HEC-RAS/LISFLOOD cases have not been replaced. Reviewed routed lateral hydrographs can replace the fitted constant through the new import path.

The [geometry and roughness follow-up](docs/GEOMETRY_ROUGHNESS.md) adds **Base scenario case → HEC-RAS · zoned roughness · estimated bed**. Its full native run published 385 frames with documented spatial roughness and withheld hydraulic KGE 0.558. Surveyed bathymetry is still missing. `python -m server.geometry_inputs run` reproduces this separate case; `--survey` accepts a reviewed terrain/coverage bundle after datum, units, hash and coverage checks. Data & provenance displays the priors and survey status.

The [detailed bathymetry investigation](docs/BATHYMETRY_INVESTIGATION.md) identifies specific survey-project leads, archives public ICESat-2 water-level/photon previews, and evaluates a constrained estimated-bed alternative. No bed measurements have been accepted; the existing terrain remains estimated.
