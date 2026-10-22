# Public-data study and real river view

The first upstream HEC-HMS routing calibration has been **computed**, and the map now opens on actual mapped water in the Kabul River near Nowshera. A calibrated 2-D inundation model has not been accepted.

## Model actually run

`workspace/downloads/nowshera-2022/study/hec-hms/upstream.hms` is a generated HEC-HMS 4.14 project. Its final simulation is `FittedRouting`. The bundled Java/Jython and HEC-DSS libraries write real DSS inputs, compute routing and export the engine's output. No Python flow solver is used.

- Sources: Warsak and Swat/Khiali at Charsadda Road. Munda and Chakdara are nested upstream gauges and are not added again.
- The original 17 FFC PDFs were rendered into three review sheets; 49 rows for the two upstream sources and Nowshera were visually checked against those originals. Visual transcription does not establish instrument accuracy.
- A spaced thousands separator (`22 ,000`) had been truncated in the first automated extraction. The extractor now preserves it as 22,000, with a regression test. Period-separated Nowshera entries on August 20/21 remain excluded.
- The model window is August 20, 2022 at 0100 UTC through September 5 at 0100 UTC. The two daily source series are linearly interpolated to 385 hourly ordinates each. Interpolated ordinates remain labeled **modeled**, with both bracketing source reports. No extrapolation, reconstructed event peak or hourly observation is claimed.
- Thirty combinations of HEC-HMS Muskingum travel-time parameters were compared. Muskingum X is fixed at zero. An unmeasured local contribution is fitted as one nonnegative constant using calibration data only.
- Seven Nowshera observations dated August 22–28 are used for calibration. Eight observations dated August 29–September 5 are withheld from fitting. These are two periods of the same event, not independent-event validation.

| Quantity | Result |
| --- | --- |
| Warsak routing K | 12 hours |
| Swat routing K | 6 hours |
| Estimated constant local contribution | 732.848 m³/s |
| Calibration NSE / KGE | 0.938 / 0.798 |
| Validation NSE / KGE | **0.678 / 0.462** |
| Validation RMSE | 1338.764 m³/s |
| Predeclared targets | NSE ≥ 0.65 and KGE ≥ 0.60 |
| Acceptance | **Failed KGE target; retain as an exploratory routing model** |

Do not retune to the withheld period and call that same period independent validation. Further model development requires new independent observations/events. Routing discharge does not calibrate Manning roughness, bathymetry, structures, backwater, or inundation extent. The fitted local constant is not a complete tributary hydrograph.

Artifacts under `study/` include `boundary-review.json`, reviewed observations, `upstream-hourly-interpolated.csv`, `routing-calibration-candidates.csv`, `routing-calibration.json`, and `hms-nowshera-hourly-modeled.csv`. The report records engine/input/output hashes; calibration and final DSS inputs are kept separately. Model text snapshots and compute logs preserve reproducibility.

The standard hydrology adapter also recomputed `FittedRouting` in a private project copy successfully; `study/hms-cli-check.json` records that integration check. Its headless shutdown was corrected so a successful simulation does not become a Jython script-exit error.

## Moisture and rainfall work

An actual August 19, 2022 [NOAA SMOPS Climate Data Record](https://coastwatch.noaa.gov/erddap/griddap/noaacwSMcdrDaily.html) subset was downloaded for the upstream region. Its native 0.25-degree surface moisture and packed quality flags are preserved as separate GeoTIFFs and in the original NetCDF. The provider metadata gives m³/m³ and CC0-1.0. Missing pixels remain missing. This is an alternate product, not SMAP-only data, and has not been accepted as a root-zone infiltration state: the ERDDAP quality metadata lacks masks/values needed to decode its packed flags.

[NOAA GSOD](https://www.ncei.noaa.gov/data/global-summary-of-the-day/) station files for Peshawar, Saidu Sharif, Dir, Chitral and Drosh were downloaded. Only complete-24-hour precipitation flags D/F/G were retained; incomplete, trace and missing records were excluded. There are 23 calibration and 34 validation station/day pairs against CHIRPS. The ratio-of-sums candidate multiplier is **1.009908**, fitted on August 20–26 only. It did not improve withheld RMSE. It remains a regional sensitivity raster, not an accepted basin-wide correction; temporal accumulation windows, mountain coverage and gauge overlap with CHIRPS require review.

The computed HEC-HMS routing model consumes measured discharge, so rainfall, infiltration and initial soil moisture are unused in this branch. This follows [USACE's gauged-routing workflow](https://www.hec.usace.army.mil/confluence/hmsdocs/hmsguides/hms-modeling-applications/transforming-regulated-streamflow-to-unregulated-streamflow-using-hydrologic-routing/calculating-unregulated-time-series-with-a-hydrologic-model/hydrologic-routing-of-reservoir-inflow-and-outflow). Rainfall-runoff scenarios still require accepted rainfall and soil parameters. These research candidates are not registered as accepted forcings merely to unlock preflight.

## Actual river location and natural context

The default **River view** focuses near **71.97786° E, 34.00769° N**, on ESA WorldCover 2021 mapped water near the major HydroRIVERS channel. This is a camera focus, not an authoritative gauge survey. HydroRIVERS supplies the channel overlay. Select Warsak in the station catalog to inspect the upstream reach.

Satellite imagery comes from [Esri World Imagery](https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer), with provider attribution displayed. Imagery dates vary; it is contextual imagery, not 2022 flood evidence. The Map/Satellite control switches the basemap; River lines toggles the coarser HydroRIVERS overlay. River view uses an oblique camera; Domain overview preserves the wider view.

Real local topography is sampled from the downloaded FABDEM v1.2 native tiles and served as bounded 65×65 heightmaps. Level-zero through level-six source samples are preloaded to avoid a long chain of coarse requests; finer tiles are cached and stop at the declared maximum level. Shared tile-edge coordinates are tested. Sources cover approximately 71–73° E and 33–35° N; outside coverage the viewer uses an ellipsoid. Source EGM2008 heights are for visual context without a geoid conversion, and are separate from the hydraulic worker's hash-bound study clip.

The Data & provenance tab now includes the actual HEC-HMS hydrograph, withheld scores, moisture status and rainfall result. Sparse daily observations remain visible as points among the hourly modeled ordinates.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m pip install -r server\requirements-data.txt
.\.venv\Scripts\python.exe -m server.acquire
.\.venv\Scripts\python.exe -m server.acquire_bulletins
.\.venv\Scripts\python.exe -m server.study all
.\.venv\Scripts\python.exe -m server.study_hms
.\.venv\Scripts\python.exe -m pytest tests -q
.\scripts\dev.ps1
```

The original HEC-RAS case still requires its own reviewed hydraulic project. The separate **runnable public-data LISFLOOD-FP screening case** now uses a 100 m grid, a connected WorldCover river footprint, explicitly estimated bed depths and a 72-hour constant-flow warm-up before flood playback. Warm-up and flood run continuously in the external engine. Publication requires converged flow/storage and a wet inlet-to-outlet channel; warm-up frames are excluded. The earlier dry-start 200 m result had NSE/KGE 0.747/0.519 and remains preserved as a superseded experiment. Current run checks, scores and remaining limitations are recorded in the [screening-model evidence](SCREENING_MODEL.md). The channel depths are estimates, not surveyed geometry or independent calibration, and no independent flood extent is available.

Required next scientific evidence includes complete sub-daily upstream/lateral discharge and operations, reviewed channel/structure geometry and downstream conditions, calibration, and matched independent flood extent. A Sentinel-1 catalog query located relevant 2022 scenes and is saved as `study/sentinel1-search.json`; scene discovery alone is not a classified or validated flood extent.
