# Verification record — 22 October 2026

The production build and 41 backend tests were repeated on 22 October. The recorded external-engine flood calculation was completed on 20 October; its immutable outputs are reused after hash verification.

The follow-up has **41 passing backend tests**: 20 pipeline, five acquisition, four study/terrain, six screening integrity and six channel/initialization checks. The [data acquisition record](DATA_ACQUISITION.md) documents the actual inputs. The [computed upstream HEC-HMS study](STUDY_PROGRESS.md) has seven calibration and eight withheld observations; its validation NSE/KGE remain 0.678/0.462. The revised [LISFLOOD-FP case](SCREENING_MODEL.md) uses a 100 m mapped channel, explicitly estimated bed depths and a 72-hour river warm-up, excluded from its 384 published flood frames. The complete run passed convergence, wet-connectivity and numerical checks. Withheld NSE/KGE improved to **0.797/0.577**, with KGE still below 0.60; no accepted calibrated 2-D model or validated flood extent is claimed.

## Software checks

| Check | Result | Scope |
| --- | --- | --- |
| TypeScript + Vite production build | Passed | Static application, lazy Cesium component and copied Cesium assets |
| Python pipeline suite | 20 passed | Scenario schema, clipping/snap, source/cache hashes, model binding including changed inflows, publisher, scientific scores and local API rules |
| Python acquisition suite | 5 passed | Native raster alignment, current-column/time transcription, spaced thousands separators, refusal to guess missing headers, and catchment-before-rainfall dependency |
| Study and terrain suite | 4 passed | Observation/interpolation provenance and refusal of extrapolation, rainfall/routing withheld-data isolation, terrain tile edge continuity and orientation |
| Screening integrity suite | 6 passed | Modeled-versus-observed labels, changed source hashes, internal hourly gaps, incomplete/nominal engine timing, altered overlays and complete gauge sections |
| Channel and initialization suite | 6 passed | Estimated-bed provenance, unchanged terrain outside mapped water, rejection of disconnected water, stable initialization, and refusal of unstable outflow/storage or a dry channel gap |
| Actual HEC-HMS routing calibration | Computed, validation failed | 30 candidates, separate final DSS inputs, 385 hourly outputs, seven training and eight withheld daily gauge pairs; no custom flow solver |
| Actual downloaded input verification | Passed | Six registered source hashes, complete terrain, native-grid preservation, rainfall coverage of the candidate upstream extent, 17 PDF hashes, 236 unique gauge snapshots and SI conversions |
| Case runner and example browser checks | 10 passed, with final corrected-case checks rerun | Case loading, partial/file JSON, invalid inputs, blocked compute, exact pipeline payloads, stale edits, desktop/mobile and real prepared-case Run → Play |
| Earlier map/study checks | 8 passed across earlier final checks | Existing interactions, real terrain/river focus and computed upstream study panel |
| Dependency installation | Passed | Isolated Python environment, npm dependencies, Chromium, GIS/HDF tooling, RAS Commander, CMake/Ninja and LLVM-MinGW |
| HEC-RAS 6.6 installation | Passed | Authenticode valid; MSI reports successful install; `Ras.exe` detected at configured path |
| HEC-HMS 4.14 portable installation | Passed | Official portable archive extracted; executable and bundled Java/Jython detected |
| LISFLOOD-FP 8.0.3 build and execution | Passed | Official archive MD5 verified; CPU/OpenMP executable reports version and executes 8×8 boundary test |
| Actual Nowshera screening computation | Published, unvalidated | Continuous 72-hour warm-up plus 16-day flood; 457 native / 384 published frames; wet channel connected at playback start; numerical volume error 0.0003893%; withheld NSE/KGE 0.797/0.577; independent extent unavailable |

The Python tests use small synthetic rasters and CSVs in temporary directories. The generic browser result test uses an explicitly synthetic UI fixture via a mocked API; the prepared-case browser test uses the actual hash-verified local engine output. Synthetic fixtures are never registered as Nowshera study data.

## Installed LISFLOOD executable check

The official distribution's `testing/T002b_BCTest` was copied into `workspace/engine-checks/T002b_BCTest` and run for its supplied 100-second boundary case. It completed with exit 0 and generated 409 output files. A second parameter file selected the engine's existing `acceleration` option (local-inertial ACC) in place of `adaptoff`; that also completed with exit 0 and 409 output files. Logs are `compute.log` and `acc-compute.log` in that ignored working directory.

This establishes that the installed binary executes the selected solver on the supplied small case. It is **not** a quantitative hydraulic benchmark validation, a mass-balance acceptance report, a calibrated Pakistan model, or a historical flood replay.

## Browser review

Desktop and 390-pixel mobile layouts were inspected. The station globe, mapped geographic context, study boundary, scenario editor, empty-output states and upstream connection cards render without horizontal page overflow. Tile completion is awaited in screenshot checks. Source imagery and terrain attribution are visible. A/B frames are selected by exact timestamp; unmatched times are shown explicitly. Model time, chart cursor and raster field selection share the same selected frame.

The revised warmed-river case passed the desktop browser check on 22 October in 25.2 seconds: real readiness, verified-result handoff, successful initial and mid-period computed water imagery, completed map tiles and advancing Play. The initial screenshot shows water through the mapped river before the flood expands. Cached-output verification may take longer with a cold disk, so that browser check allows up to 120 seconds for handoff. Satellite/street layers are requested separately; slow imagery falls back during any loading period to bundled context with local terrain and computed flood rasters. Full basin outlines are opt-in. Browser and Python test files, transformation caches and npm downloads use the project drive because the system C: drive is full.

The project uses ports 5174 and 8010 to avoid other applications. The river view now uses Esri satellite imagery, OSM as a map alternative and bundled geographic context as fallback. Downloaded FABDEM tiles are automatically served as real local heightmaps; without downloaded terrain or an explicit terrain configuration the globe remains an explicitly labeled ellipsoid. The camera focuses on mapped river water near Nowshera.

## Scientific acceptance remains open

- Authoritative gauge locations and catchment delineation have not been independently verified.
- Raw FABDEM, soil, land-cover, hydrography, candidate catchment and rainfall inputs are registered. Initial moisture, soil/infiltration and roughness parameter preparation, and rainfall correction are still required.
- HEC-HMS routing and an uncalibrated, channel-conditioned LISFLOOD-FP grid with numerical river initialization are available. Channel depths are estimates. An accepted calibrated HEC-RAS project and independently reviewed surveyed hydraulic geometry remain unavailable.
- Seventeen official 2022 FFC reports and their review-required daily gauge transcriptions are available. Complete boundary hydrographs, downstream conditions, barrage/reservoir operations and independently reviewed validation series are still missing.
- No matched Sentinel-1/UNOSAT observation has been ingested.
- The screening model's computed depths and failed held-out skill are explicitly labeled. No validated inundation map or observed arrival-time prediction is claimed.

See the [point-by-point plan audit](IMPLEMENTATION_CHECKLIST.md) for implemented paths and deferred integrations, including automatic delineation, terrain/COG tiling, native mesh export, velocity particles and external operational feeds.

## 22 October 2026 — computed HEC-RAS follow-up

The separate [HEC-RAS 6.6 full SWE case](HECRAS_MODEL.md) has now been built, run for the complete event, checked and published as 385 hourly depth/WSE frames. It has a native Nowshera reference-line hydrograph and automatic raster publication. The existing LISFLOOD case remains available. Native volume accounting error was 0.000430%; initialization and wet connectivity checks passed. Withheld NSE/KGE are 0.778/0.548, so KGE still misses the target and independent extent validation remains unavailable.

The production build and dependency consistency checks pass. **52 Python tests and 20 browser tests pass**, including native-output rejection checks and the real prepared HEC-RAS selection, job submission, original raster delivery and playback flow. Lint has the seven existing React warnings. All 38 readiness checks for the prepared HEC-RAS case pass. The first full browser run had an intermittent JSON-import timing failure; that test passed on an isolated rerun and the final complete browser run passed all 20 tests.

Windows 11's missing WMIC component was restored using Microsoft's package linked by USACE. The user explicitly accepted HEC-RAS's first-use terms before native computing. See the model record for original file locations, exact native HDF hash, assumptions and reproduction commands.

## 22 October 2026 — shared inflow candidate

- Visually checked page 1 of the original FFC 26–28 August 2022 PDFs. Added the three explicitly timed Warsak readings to `server/data/ffc-subdaily-2022.json`, retaining PKT/UTC times, units, page numbers and verified PDF SHA-256 values.
- `python -m server.inflows all` downloaded/preserved 17 KP PDMA daily reports with 288 river reference rows. Their observation times are absent; no times were invented and none of those rows entered the model.
- Native HEC-HMS 4.14 computed 385 event ordinates in a separate candidate project with the original routing coefficients and local constant. Withheld NSE/KGE/RMSE: baseline 0.678277 / 0.461787 / 1338.764 m³/s; candidate 0.686689 / 0.469270 / 1321.145 m³/s. This is further development on the same event, not new independent validation. Full timed Swat/lateral evidence is unresolved; neither hydraulic result was replaced.
- A separate native HEC-HMS integration fixture replaced the constant with a local-flow series containing an explicitly synthetic +100 m³/s pulse. All 385 junction responses matched the expected change exactly (maximum error 0.0 m³/s). This numerical test is not historical data or a published simulation. Evidence: `workspace/temp/native-lateral-check.json`.
- `python -m pytest tests -q`: 63 passed; existing dependency deprecation warnings remain. Tests cover time/units/provenance requirements, untimed report exclusion, nested/evaluation gauge rejection, source conflicts, missing lateral coverage, PDF hash changes, and replacement of the constant in private HMS inputs.
- `npm run build` passed. `npm run lint` passed with the seven existing React warnings. `npm test -- tests/browser/study.spec.ts`: 1 passed, including real API candidate scores, unpublished status, terrain rendering and mobile overflow. Screenshot: `test-results/upstream-routing-study.png`.
- Both current HEC-RAS and LISFLOOD cases returned ready=true from `/api/preflight`. Original boundary and shared HMS output hashes still match their baseline calibration report. API restarted on port 8010 and exposes the candidate under `/api/study`; Data & provenance displays it and Export study includes its audit.
