# Cursor plan verification

The supplied plan is preserved in [cursor-plan.txt](../examples/cursor-plan.txt). This audit distinguishes working code from scientific acceptance. **No 2022 Nowshera hydraulic result has been produced or validated.**

Update: [real public input downloads](DATA_ACQUISITION.md) now include terrain, land cover, soil, hydrography, a candidate basin, historical rainfall, and official daily gauge-report references. This resolves raw-data availability for those layers; the review and calibration requirements below still apply.

Further progress: the [upstream study](STUDY_PROGRESS.md) has actually computed a 30-candidate HEC-HMS routing calibration, downloaded NOAA moisture and rain-gauge references, checked candidate rainfall correction, and added real FABDEM terrain/satellite river views. The withheld KGE target failed, and hydraulic acceptance remains open.

| Plan point | Implementation / evidence | Acceptance still required |
| --- | --- | --- |
| Separate hydrology, hydraulics, animation | `server/hydrology.py`, `server/worker.py`, `server/publish.py`, `src/components/Globe.tsx` | Review each external model and its numerical behavior |
| Start with one station | Nowshera 2022 pilot; Warsak upstream, Attock and the Indus downstream; server rejects other hydraulic outlets | Raw inputs acquired; complete reviewed boundaries, calibrated model and independent validation required before compute expands |
| Upper stations influence lower stations | Directed topology includes Warsak, Tarbela, Kohala, Akhnur and Marala; contributing boundaries editable | Topology is schematic; no assumed lag, attenuation, reservoir release or summed flow |
| FFD catalog / flood classes | 29 seed gauges; FFD links, lakh cusec → m³/s conversion, missing Exceptional class remains absent | Seed coordinates are approximate and need gauge-location verification |
| Arbitrary lat/long and extra gauges | Custom planning outlet plus extensible boundary IDs in JSON | Compute remains pilot-only; custom gauges need registry and routing review |
| Snap + catchment | Metric snap to registered linework within 2 km; downloaded HydroRIVERS used for the pilot; registered candidate catchment outlined separately | Candidate union contains 119 upstream subbasins; exact gauge delineation needs review; no automatic MERIT D8 delineation yet |
| Bounded terrain, soil, rain, cover | Six real public input layers downloaded and registered; bounded clipping, complete-coverage checks, hashes and CRS; rainfall covers the candidate upstream region | Review full catchment, time alignment, physical parameters and missing moisture; full upstream hydrology exceeds the local hydraulic domain |
| FABDEM default / fallbacks | FABDEM v1.2 downloaded, native grid preserved and hash-bound; source and license shown; fallback sources documented | Data stay outside Git; bathymetry/vertical datum need review; alternative DEM use needs an explicit schema/source change |
| SoilGrids / Saxton / initial moisture | Input registration, Green-Ampt/SCS-CN choice, SMAP or explicit wetness assumption | Pedotransfer, infiltration parameters and spatial moisture preparation remain in the reviewed hydrology model |
| GPM, CHIRPS, gauges, forecast bias | Product choice, multiplier, bias-correction notes, public STAC ingestion | Authenticated NASA/GEE or forecast adapters and automatic gauge bias correction are not included |
| ESA WorldCover → Manning n | Source selection, land-cover raster clipping, prepared-model binding | Roughness lookup and changed land-cover maps must be prepared/reviewed in the engine project |
| Versioned first-class scenario | Strict schema v1, JSON import/export, browser library, canonical hash, DEM hash, domain, UTM CRS, UTC, interval, forcings, structures, metrics | Provenance statements need documentary support; edited scenarios require model re-preparation |
| Scenario families | Historical (dates editable for 2010/2022), all published FFD classes, design storm / return period, saturated soil, release, breach, land-cover, climate multiplier | These are experiment definitions; release/breach geometry, IDF analysis and all forcings must exist in the prepared model |
| HEC-HMS hydrology | Installed 4.14; CLI runs prepared projects; public-data study generates an upstream source/reach project, computes 30 candidates, exports DSS and evaluates withheld observations | Routing KGE target failed; complete lateral hydrographs and a separately reviewed rainfall-runoff model remain required |
| HEC-RAS 2D | Installed 6.6; RAS Commander; automated exploratory Nowshera mesh/terrain/boundaries; full SWE computed, numerically checked and published; exact model binding and isolated runs. See [HEC-RAS case](HECRAS_MODEL.md) | Estimated bed, uniform roughness, sparse modeled inflows; surveyed structures, calibration and independent flood-extent validation remain unavailable |
| LISFLOOD-FP screening | Official 8.0 source archive checksum verified; local CPU/OpenMP build; same scenario/boundary intake; ACC parameter-file worker; supplied 8×8 boundary test executed | NetCDF/CUDA disabled in this build; source portability change only selects its existing Windows allocation path; quantitative benchmark validation and domain calibration still required |
| HDF5 → raster output | HDF dataset inspection; RAS Mapper / external model raster-export manifest; SI, CRS, time, grid, terrain-hash checks | Native unstructured HDF mesh rasterization remains an explicit RAS Mapper/export step; no guessed depth or face-to-cell velocity conversion |
| COG / tiles / terrain | Original GeoTIFF downloads + bounded georeferenced PNG playback; real local FABDEM heightmap terrain with source hashes and tested tile edges; satellite/map switch; optional quantized-mesh URL or ion | Automatic result COG/XYZ pyramids, RAS Tiles, quantized-mesh generation and ion publishing are not included; viewer terrain does not compute floodwater |
| Scientific animation | Cesium clock, timeline and hydrograph locked to exact frame time; depth/WSE/speed raster legend; no interpolated invented water | Player uses timestamped imagery layers rather than a tile-server `TimeDynamicImagery` implementation; no output is bundled |
| Velocity particles | Real speed raster can be displayed | Vector particles deferred until correctly exported u/v fields and documented coordinate transforms exist |
| Compare A/B | Imagery split, exact timestamp matching, differing terrain hashes flagged | Missing B frame is shown explicitly; no nearest-time substitution |
| Gauge / satellite validation | Timestamp-aligned CSV; NSE/KGE/RMSE; CSI/POD/FAR; nodata mask; acquisition-time overlay; targets | Real FFD observations and Sentinel-1/UNOSAT extent required; constant/missing observations produce null skill |
| Uncertainty / report | Imported lower/upper hydrograph band; JSON report includes inputs, assumptions, checks and selected result | No fabricated uncertainty; ensemble generation and formal report/PDF layout deferred |
| GloFAS / Flood Hub / FEWS | Source roles documented; no virtual gauge represented as an official observation | Context feeds and operational-system integration deferred |
| Unreal cinema | Optional extension only; no game-engine water added | Export integration deferred until verified rasters exist |
| No custom physics / fake inundation | Legacy geometric-screening scenarios removed; no water-plane, rainfall-as-depth or extruded flood polygons | Code tests cannot establish scientific skill |

## Verification

The [verification record](VERIFICATION.md) lists 41 passing backend tests, including six channel/initialization checks, browser checks, actual downloaded-file verification, the successful build and engine execution evidence. It records the real HEC-HMS compute and failed held-out routing target, plus a separate uncalibrated [LISFLOOD-FP public screening case](SCREENING_MODEL.md). The revised case uses a 100 m mapped channel with explicitly estimated bed depths and a converged 72-hour river warm-up excluded from playback. Surveyed geometry, accepted calibration and independent flood extent remain open.

- `npm run build` checks TypeScript and produces a static app with Cesium resources.
- `python -m pytest tests/test_pipeline.py` tests bounded clipping, source hashes, snapping, model bindings, output publication, scientific scores and API gating with **synthetic test fixtures**.
- `npm test` exercises station selection, drafts, exports, readiness, mobile layout, and clock-matched A/B playback.
- Browser screenshots are development artifacts under ignored `test-results/`. They are not flood validation evidence.

## Next scientific acceptance step

Complete and review the Nowshera 2022 study package using the acquired public layers and FFC references: exact upstream catchment, soil/infiltration and roughness parameters, Warsak **and all other contributing tributary/lateral inflows**, structures and operations, an HEC-HMS/HEC-RAS setup, reviewed gauge observations, and time-matched satellite extent. Prepare, calibrate and review it, then use the implemented worker and publication path. Software installation alone cannot supply those observations or geometry.
