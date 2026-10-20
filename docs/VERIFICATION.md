# Verification record — 20 October 2026

The follow-up now has 28 passing backend tests: 19 pipeline, five acquisition and four study/terrain tests, plus checks on the actual downloaded files. The [data acquisition record](DATA_ACQUISITION.md) documents those inputs. The [computed upstream HEC-HMS study](STUDY_PROGRESS.md) has seven calibration and eight withheld observations; validation NSE is 0.678 and KGE is 0.462, so the KGE target failed. No accepted calibrated 2-D model or validated flood output has been produced.

## Software checks

| Check | Result | Scope |
| --- | --- | --- |
| TypeScript + Vite production build | Passed | Static application, lazy Cesium component and copied Cesium assets |
| Python pipeline suite | 19 passed | Scenario schema, clipping/snap, source/cache hashes, model binding, publisher, scientific scores and local API rules |
| Python acquisition suite | 5 passed | Native raster alignment, current-column/time transcription, spaced thousands separators, refusal to guess missing headers, and catchment-before-rainfall dependency |
| Study and terrain suite | 4 passed | Observation/interpolation provenance and refusal of extrapolation, rainfall/routing withheld-data isolation, terrain tile edge continuity and orientation |
| Actual HEC-HMS routing calibration | Computed, validation failed | 30 candidates, separate final DSS inputs, 385 hourly outputs, seven training and eight withheld daily gauge pairs; no custom flow solver |
| Actual downloaded input verification | Passed | Six registered source hashes, complete terrain, native-grid preservation, rainfall coverage of the candidate upstream extent, 17 PDF hashes, 236 unique gauge snapshots and SI conversions |
| Playwright browser checks | 8 passed across final checks | Seven existing interactions plus real local terrain/river focus and the computed study panel; the three map checks were rerun after the terrain-loading fix |
| Dependency installation | Passed | Isolated Python environment, npm dependencies, Chromium, GIS/HDF tooling, RAS Commander, CMake/Ninja and LLVM-MinGW |
| HEC-RAS 6.6 installation | Passed | Authenticode valid; MSI reports successful install; `Ras.exe` detected at configured path |
| HEC-HMS 4.14 portable installation | Passed | Official portable archive extracted; executable and bundled Java/Jython detected |
| LISFLOOD-FP 8.0.3 build and execution | Passed | Official archive MD5 verified; CPU/OpenMP executable reports version and executes 8×8 boundary test |

The Python tests use small synthetic rasters and CSVs in temporary directories. The browser result test uses an explicitly synthetic UI fixture via a mocked API. None of these files are registered as Nowshera outputs.

## Installed LISFLOOD executable check

The official distribution's `testing/T002b_BCTest` was copied into `workspace/engine-checks/T002b_BCTest` and run for its supplied 100-second boundary case. It completed with exit 0 and generated 409 output files. A second parameter file selected the engine's existing `acceleration` option (local-inertial ACC) in place of `adaptoff`; that also completed with exit 0 and 409 output files. Logs are `compute.log` and `acc-compute.log` in that ignored working directory.

This establishes that the installed binary executes the selected solver on the supplied small case. It is **not** a quantitative hydraulic benchmark validation, a mass-balance acceptance report, a calibrated Pakistan model, or a historical flood replay.

## Browser review

Desktop and 390-pixel mobile layouts were inspected. The station globe, mapped geographic context, study boundary, scenario editor, empty-output states and upstream connection cards render without horizontal page overflow. Tile completion is awaited in screenshot checks. Source imagery and terrain attribution are visible. A/B frames are selected by exact timestamp; unmatched times are shown explicitly. Model time, chart cursor and raster field selection share the same selected frame.

The project uses ports 5174 and 8010 to avoid other applications. The river view now uses Esri satellite imagery, OSM as a map alternative and bundled geographic context as fallback. Downloaded FABDEM tiles are automatically served as real local heightmaps; without downloaded terrain or an explicit terrain configuration the globe remains an explicitly labeled ellipsoid. The camera focuses on mapped river water near Nowshera.

## Scientific acceptance remains open

- Authoritative gauge locations and catchment delineation have not been independently verified.
- Raw FABDEM, soil, land-cover, hydrography, candidate catchment and rainfall inputs are registered. Initial moisture, soil/infiltration and roughness parameter preparation, and rainfall correction are still required.
- No calibrated Nowshera HEC-HMS/HEC-RAS project or reviewed hydraulic mesh is available in this checkout.
- Seventeen official 2022 FFC reports and their review-required daily gauge transcriptions are available. Complete boundary hydrographs, downstream conditions, barrage/reservoir operations and independently reviewed validation series are still missing.
- No matched Sentinel-1/UNOSAT observation has been ingested.
- No Nowshera 2022 skill score, inundation map or arrival-time prediction has been claimed.

See the [point-by-point plan audit](IMPLEMENTATION_CHECKLIST.md) for implemented paths and deferred integrations, including automatic delineation, terrain/COG tiling, native mesh export, velocity particles and external operational feeds.
