# Exploratory Nowshera HEC-RAS 2D case — 22 October 2026

The application includes an actual HEC-RAS 6.6 full SWE-ELM model of the Nowshera reach, driven by the previously computed HEC-HMS aggregate inflow. HEC-RAS built the mesh and property tables and computed the hydraulics. Python prepares inputs and converts native output to map rasters. This is an exploratory, uncalibrated model; neither the geometry nor roughness was fitted to the eight withheld observations.

Choose **Load runnable HEC-RAS case → Prepare & run case → Play**. The supplied LISFLOOD and HEC-RAS cases remain separate. Selecting an engine for an unchanged public case selects its prepared counterpart; custom scenario changes require a new matching model binding.

## Actual model

- Project: `workspace/hecras/0b012877e536/project/Nowshera.prj`, plan `01`.
- Full native run: the `run_project` path recorded in `workspace/hecras/0b012877e536/latest-run.json` is authoritative.
- Terrain: the existing 100 m channel-conditioned FABDEM grid, copied without changing its bytes. The bed is estimated from mapped water and Manning normal depth, not surveyed. The model perimeter sits one terrain pixel inside its coverage so HEC can sample both sides of each face.
- CRS and units: UTM 42N, SI. Vertical reference: FABDEM EGM2008 with an estimated channel-bed correction.
- Mesh: 200 m seed spacing; HEC generated **4,624 physical cells** plus its boundary ghost cells. The seed geometry is created with RAS Commander's bundled 6.6 template and native RasMapper point generator. HEC performs the geometry and face-property preprocessing.
- Roughness: uniform **Manning n = 0.04**, explicitly shown as **Prepared model** in the scenario. This is an analyst assumption, not a calibrated WorldCover roughness map. The LISFLOOD public case uses its own roughness specification.
- Inflow: the same HEC-HMS aggregate at the western boundary, in **total m³/s**. It is not LISFLOOD's discharge-per-width input. No additional tributaries are double-counted.
- Downstream: normal depth using the existing terrain-derived slope, approximately 0.000376197. Remaining outer boundaries are closed.
- Solver: native HEC-RAS 6.6 **SWE-ELM**, 30-second computation step, two solver cores, hourly output. Gravity is explicitly 9.80665 m/s² and the linear solver is PARDISO.
- Initialization: dry start on 17 August 2022 at 0100 UTC; hold the first modeled inflow constant for 72 hours. Displayed event: 20 August at 0100 UTC through 5 September at 0100 UTC. Rainfall, infiltration, evaporation and initial soil moisture are unused in this gauge-driven model.

## Computed checks and scores

| Check | Observed result |
| --- | --- |
| Native completion | Full event completed; native log identifies SWE-ELM and finished unsteady flow |
| Native / published hourly frames | 457 / **385**; warm-up excluded, event start and end retained |
| Native volume accounting error | **0.000430%**, below the publication threshold of 0.1% |
| Last six initialization hours | Outflow matches inflow at saved precision; storage range is zero at saved precision |
| Wet connection | Connected wet physical cells from upstream to downstream boundary |
| Finite native hydraulic fields | Passed |
| Maximum native face-normal velocity | 2.761 m/s; not exported as cell speed |
| Maximum rasterized depth | 13.248 m; modeled, not measured |
| Eight withheld daily discharge pairs | NSE **0.778**, KGE **0.548**, RMSE **1112.206 m³/s** |
| Independent flood extent | Unavailable; `validation_passed` is false |

The KGE target of 0.60 is still missed. These are eight withheld observations from the same historical event, not independent-event validation. The upstream HEC-HMS routing experiment also missed its KGE target. Surveyed bathymetry, structures, levee operations and independent water-level/flood-extent data remain unavailable.

`numerical-review.json` records the exact native HDF SHA-256 and checks. Publication refuses unstable or terminated runs, missing timestamps, non-finite fields, excessive volume error, unconverged initialization or missing wet connectivity. A library process-success flag alone is insufficient: native compute messages and hydraulic datasets are checked independently.

Map rasters come from the **native cell water surface** assigned by each exact mesh polygon onto the source conditioned-terrain grid. Depth is `max(WSE - terrain, 0)` within native wet cells. Ghost cells, dry-cell water surfaces and initialization frames are excluded. Gauge discharge is HEC's own **Nowshera gauge reference-line flow**, interpolated only to the original withheld daily observation times. No face-velocity-to-discharge approximation is used.

## Reproduction and portability

```powershell
.\.venv\Scripts\python.exe -m pip install -r server\requirements-hecras.txt
.\.venv\Scripts\python.exe -m server.hecras prepare
.\.venv\Scripts\python.exe -m server.hecras smoke
.\.venv\Scripts\python.exe -m server.hecras run
```

`prepare` creates the source model and records its source/engine hashes. `smoke` runs the full initialization plus six event hours in a separate copy. `run` runs a private full-event copy, performs the native checks, exports, publishes, and binds the reviewed source project. `publish` can finish publication of the closed native run named by `latest-run.json`. Existing accepted bindings with changed inputs are refused; preserve the original and prepare a new case identity.

Preserve all of `workspace/hecras/`, its native run HDF and logs, the matching binding, domain, registered inputs and `workspace/results/`. The root `requirements.txt` and server lock now include Python.NET and GeoPandas used for native model preparation. HEC-RAS itself remains an external Windows installation. The user accepted its first-use terms for this installation before the tests.

On this Windows 11 machine, WMIC was absent. Microsoft's WMIC recovery package was downloaded directly from Microsoft and installed using the official procedure linked by [USACE's HEC-RAS 6.x compatibility notice](https://www.hec.usace.army.mil/confluence/rasdocs/raski/latest/wmic-window-11-os-issue). The installer and transcript are retained in `workspace/tools/wmic_dlc/` and `workspace/temp/wmic-install.log`. Verify `wmic cpu get NumberOfCores,NumberOfLogicalProcessors` when restoring HEC-RAS 6.6 on another Windows 11 machine.

References: [USACE 2D flow-area documentation](https://www.hec.usace.army.mil/confluence/rasdocs/rasum/6.6/entering-and-editing-geometric-data/2d-flow-areas), [RAS Commander source, version 0.106.1](https://github.com/gpt-cmdr/ras-commander). The source model, native messages and hashes are the reproduction record for this particular case.

## Separate zoned-roughness case

The [geometry and roughness record](GEOMETRY_ROUGHNESS.md) describes the additional native case `nowshera-hecras-zoned-87781e7f`. It retains the estimated bed and original inflow, replacing uniform roughness with documented WorldCover priors actually present in native cell/face tables. It published 385 frames with withheld NSE/KGE 0.787315/0.557552; scientific validation remains false. Select it in **Base scenario case**. The original model documented above remains available. Surveyed bathymetry has not been obtained or substituted; the survey import path alone does not complete that requirement.
