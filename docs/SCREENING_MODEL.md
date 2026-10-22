# Nowshera public-data screening with an initialized river

The current prepared LISFLOOD-FP case uses a **100 m channel-conditioned grid and a 72-hour constant-flow warm-up before the displayed flood period**. It replaces the earlier 200 m, initially dry terrain-only case. The river must already be wet and flowing through the reach before output can be published. This remains an exploratory model with estimated bathymetry, not a calibrated HEC-RAS project or a validated inundation forecast.

In the app, refresh and choose **Load runnable public case → Prepare & run case → Play**. The case is named **Nowshera · warmed river public-data screening**. An unchanged prepared case reuses its hash-verified computed output. Changing scenario values requires a matching prepared project.

## Channel geometry

- The 14.6 × 14.6 km metric window is unchanged from the previous case; the grid is refined from 73 × 73 at 200 m to **146 × 146 at 100 m**, in EPSG:32642.
- FABDEM supplies terrain with native EGM2008 heights. ESA WorldCover supplies the water footprint. Water fractions are averaged from the source pixels; cells containing at least 25% mapped water define the resolved corridor. A four-connected corridor must span the western inlet and eastern outlet. Disconnected water is rejected; no channel is drawn across intervening land to make it connect.
- A path confined to that corridor supplies longitudinal distance. Approximately 500 m profile segments provide resolved channel widths and the 25th percentile of FABDEM's water-only surface samples. Weighted monotone regression removes upslope noise in that reference surface. These are remotely sensed surface elevations, not riverbed measurements.
- Missing bed elevations are **estimated** by subtracting rectangular Manning normal depth at the first modeled HEC-HMS flow, **2177.007 m³/s**, using channel n = 0.035 and the mapped longitudinal surface slope. This is an explicit hydraulic-geometry assumption. Neither the eight withheld observations nor their KGE are used to select dimensions.
- The current mapped path is about **18.43 km** long. Resolved segment widths range from **200.80 to 1686.68 m**; estimated normal depths range from **1.66 to 6.10 m**. The maximum correction to a mixed terrain grid cell is **14.30 m**, which also reflects removing water-surface noise and mixed bank elevations. None of these depths is surveyed bathymetry.
- Only the **725 mapped corridor cells** are lowered. Every computational terrain cell outside that corridor remains numerically unchanged. Islands and banks outside the resolved footprint retain their source elevations. A 100 m mixed water/land cell still cannot resolve its internal banks.
- Original terrain, conditioned terrain, mapped water fractions, corridor mask, lowering raster, centerline cells and all profile dimensions are retained in the prepared project. **channel-geometry.json** documents the method and assumptions.

The external LISFLOOD-FP 8.0.3 ACC engine computes every water field. Python constructs inputs and converts native outputs; it contains no hydraulic flow solver. The engine binary and equations were not modified.

## Initialization and flood forcing

The [Bristol manual](https://www.bristol.ac.uk/media-library/sites/geography/migrated/documents/lisflood-manual-v5.9.6.pdf) describes model-generated initial water conditions. This implementation runs warm-up and flood forcing continuously in the same external-engine process, retaining both water depths and flow momentum across the transition.

1. Hold the first modeled HEC-HMS discharge constant for **259,200 seconds (72 hours)**. This is a numerical initialization assumption, **not a measured three-day pre-event hydrograph**.
2. Continue immediately with the original 385 hourly flood ordinates, August 20 at 0100 UTC through September 5 at 0100 UTC. No extra upstream discharges are added to this aggregate boundary.
3. Verify the final six hours of warm-up: downstream outflow and full-section gauge flux must each remain within 2% of imposed flow; storage range must be at most 1% of final storage. At least 95% of centerline cells must have depth above 5 cm, and a wet corridor must connect inlet to outlet.
4. Exclude all warm-up frames from publication. Displayed times equal the engine's actual elapsed seconds minus the explicit warm-up duration, added to the flood start time. No nominal hourly timestamps, invented initial frame, depth-only restart or animation-generated water is used. A final engine step beyond the flood window is omitted.

The isolated 72-hour warm-up plus six-hour flood test completed successfully. Its final six-hour maximum outflow error was **0.00519%**, gauge error **0.00377%**, and relative storage range **0.00632%**. All centerline cells were wet, with a connected wet channel through the reach. These checks establish numerical initialization, not real-world water levels.

The first initialized frame already wets about **12.12 km²**, including about **4.87 km² outside the mapped corridor**. Some low ground therefore starts wet at the assumed initial discharge; the animation must not imply every floodplain cell was dry on August 20. Depth includes normal river water, not only additional flooding above a measured baseline.

## Boundaries and unresolved inputs

- The documented HEC-HMS aggregate remains modeled from sparse Warsak/Swat daily snapshots and a fitted constant lateral term. Its withheld KGE remains 0.462. These are not complete observed sub-daily tributary hydrographs.
- HydroRIVERS identifies the major-channel crossing. The mapped western inlet spans 400 m. Floodplain QVAR is m²/s, so the total m³/s is divided by that exact width, following the installed engine source and Bristol manual. The eastern boundary is free outflow with the mapped profile slope, about 0.000376197. Other outer boundaries are closed except the inlet.
- Transferring aggregate Nowshera flow to the western edge of this short reach neglects additional travel time. No independent downstream stage, surveyed cross-sections, engineered levees, bridges or operations have been supplied.
- Land-cover roughness remains an analyst assumption. Rainfall, evaporation, infiltration and soil moisture are unused in this inflow-driven case.
- The basemap is contextual satellite imagery whose date varies. River lines are mapped hydrography, not surveyed channel banks. The oblique camera is rotated; screen direction does not define geographic north. Online imagery can fall back to bundled context while real local terrain and computed water remain available.

## Numerical checks and validation

Publication checks the full initialization-plus-flood duration, native mass and section records, actual output times, grid dimensions, finite nonnegative depths, nonzero downstream outflow, converged initialization, and relative accumulated native volume error below **0.1%**. Original native files and SHA-256 hashes are preserved.

Discharge is the sum of signed eastward one-cell virtual-gauge fluxes across every grid row near Nowshera, interpolated only to the eight withheld observation times. Those observations remain **29 August–5 September from the same event**. They are not used to fit the revised geometry. No independent matched satellite flood extent has been supplied, so passing initialization or discharge checks cannot establish validated inundation.

The full revised run completed and published **384 flood-period frames**. The engine ran for 330 seconds of wall time, followed by checked raster export and publication.

| Check | Revised v3 result |
| --- | --- |
| Requested / completed engine seconds, including warm-up | 1,641,600 / 1,641,607 |
| Flood-period duration | 1,382,400 seconds (16 days) |
| Native / published frames | 457 / 384; 72 warm-up frames and the final 7-second overshoot excluded |
| First displayed native event time | 2022-08-20 01:00:04.594 UTC |
| Last displayed native event time | 2022-09-05 00:00:01.750 UTC |
| Warm-up convergence / wet connection / centerline wet fraction | Passed / connected / 100% |
| Sum of absolute native volume errors / approximate inflow volume | 20,892 m³ / 5,366,574,987 m³ |
| Relative numerical volume error | 0.0003893%, below the 0.1% limit |
| Finite nonnegative depth and expected native grid/time records | Passed |
| Maximum modeled depth / wet area above 5 cm | 12.718 m / 49.82 km²; not observed measurements |
| Eight withheld discharge pairs: NSE / KGE | **0.797 / 0.577**; NSE passes 0.65, KGE fails 0.60 |
| Withheld discharge RMSE | **1063.270 m³/s** |
| Independent flood-extent validation | Unavailable; validation_passed remains false |

Earlier v2 scores were NSE **0.747**, KGE **0.519**, RMSE **1187.296 m³/s**. The revised scores improve on this same comparison period, but KGE still fails its target. The geometry was constructed without tuning to those withheld observations. Depth changes cannot be compared as flood severity without accounting for the changed estimated bed; reduced modeled wet area is not evidence of improved satellite extent accuracy.

## Reproduce and audit

~~~powershell
.\.venv\Scripts\python.exe -m server.screening prepare
.\.venv\Scripts\python.exe -m server.screening smoke
.\.venv\Scripts\python.exe -m server.screening run
~~~

**prepare** constructs and hash-binds the exact source, geometry, scenario and engine. **smoke** computes all 72 hours of warm-up plus six flood hours in an isolated copy. **run** executes the normal worker, checks convergence and numerical output, publishes genuine rasters and returns a result ID. A failed check prevents publication.

**workspace/screening/case.json** indexes the current case; its preparation is under **workspace/screening/e2791a7a7fdd/project/**. The complete revised run is under **workspace/jobs/c5eaf4c13cd14cb7a005c416f0783313/**. Published result **nowshera-public-screen-e2791a7a-0cd25033bc97** is under **workspace/results/**. Original and conditioned rasters, native outputs, warm-up review, numerical review and exported TIFFs remain local and ignored by Git.

Earlier v2 run **772351e351004e62b5ef01ba72f39ee0** and result **nowshera-public-screen-083c2f84-8a57a7d298cf** are preserved for audit. The earlier v1 run **22985f5e75944580ab2514343949b902** also remains available: its single long virtual-gauge section was silently truncated by the installed reader. V2 fixed that diagnostic with one-cell sections across every row, without changing water fields or the external solver; v3 retains that correction. Earlier manifests are marked superseded after successful replacement publication, without changing their recorded water fields or scores.
