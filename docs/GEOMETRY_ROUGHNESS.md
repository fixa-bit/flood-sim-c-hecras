# Geometry and roughness status — 23 October 2026

The [detailed bathymetry investigation](BATHYMETRY_INVESTIGATION.md) identifies
specific survey-project leads, archives new public water-level/photon previews,
and evaluates alternatives. No bed measurements were accepted from that work;
the surveyed-geometry requirement remains open.

**Partially completed.** Spatial roughness is implemented in a new, computed
HEC-RAS case. **Surveyed channel geometry has not replaced the estimated
bathymetry.** No usable full-reach survey was obtained. A validated survey
import path is available, but an import capability is not survey evidence.

## Open the computed case

Refresh the app. Select **Scenario lab → Base scenario case → HEC-RAS · zoned
roughness · estimated bed**, then **Prepare & run case**. This opens the
published native result. The original HEC-RAS and LISFLOOD cases remain
available. Choosing HEC-RAS explicitly preserves the selected zoned variant.
Changing a variant to another engine requires its own matching model binding.

**Data & provenance → Geometry and roughness** shows the classes, source,
roughness ranges and missing-survey status. In **Model results**, compare the
zoned result with the original HEC-RAS result using the A/B control; their
timestamps match exactly.

## Roughness change actually computed

The registered ESA WorldCover 2021 v200 clip is reprojected with categorical
nearest-neighbor sampling to a 30 m UTM 42N grid. The registered clip was
already sampled to approximately 30 m; this does not restore native 10 m
detail. Missing and unsupported classes are rejected without a default n.

The analyst crosswalk uses comparable classes in the
[USACE published roughness guidance](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.6/land-classification-layers).
Values are provisional priors for appreciable inundation depths, not field
measurements or a locally calibrated WorldCover lookup.

| WorldCover zone | Nominal n | Comparable published range |
| --- | ---: | ---: |
| Tree cover | 0.120 | 0.080–0.200 |
| Shrubland | 0.090 | 0.070–0.160 |
| Grassland | 0.035 | 0.025–0.050 |
| Cropland | 0.040 | 0.020–0.050 |
| Built-up | 0.100 | 0.060–0.200 |
| Bare/sparse vegetation | 0.027 | 0.023–0.030 |
| Permanent water/channel prior | 0.035 | 0.025–0.050 |

Forest and developed ranges span comparable subclasses because their types
and densities are unknown. WorldCover does not measure channel bed material,
crop height, forest type or urban obstruction geometry. Built-up resistance
does not insert buildings, roads, bridges or levees. The 2021 classification
may differ from conditions during August 2022. Field review and independent
calibration remain necessary. The ranges are not confidence limits.

Rules, rationales and limitations are versioned in
`server/data/roughness-worldcover-v1.json`. Nominal and lower/upper prior
rasters are preserved; the bounds have not been computed as a hydraulic
ensemble. No coefficient was selected by fitting withheld Nowshera data.

HEC-RAS/RAS Mapper authored the classification TIFF/HDF and terrain HDF, and
native preprocessing generated the actual cell and face values using the
[land-cover association workflow](https://www.hec.usace.army.mil/confluence/rasdocs/rmum/6.6/geometry-data/mannings-n-values).
Python did not fabricate solver roughness arrays or hydraulic outputs.
The copied mapper file's missing template projection link was corrected to
the actual UTM 42N projection. The original source was preserved.

## Native result, computed 22 October 2026

Case: `nowshera-hecras-zoned-87781e7f`.
Result: `nowshera-hecras-zoned-87781e7f-78d799cd2d0c`.

- Seven cover classes yield **six distinct native Manning values**, with
  water and grass sharing 0.035. Cell and face property tables contain
  0.027, 0.035, 0.040, 0.090, 0.100 and 0.120.
- Complete native geometry and land-cover association; 4,624 physical cells,
  200 m mesh and original 100 m estimated terrain.
- 457 native hourly frames; **385 published flood frames**, excluding 72
  initialization hours.
- Native volume accounting error **0.000431%**, below the 0.1% threshold.
  Initialization passed flow/storage convergence and wet connectivity.
- Maximum native face-normal velocity 2.537 m/s; maximum mapped depth
  13.965 m. These are modeled quantities without independent depth validation.

| Eight withheld daily observations | Original uniform case | Zoned case |
| --- | ---: | ---: |
| NSE | 0.777953 | 0.787315 |
| KGE | 0.548113 | 0.557552 |
| RMSE (m³/s) | 1,112.206 | 1,088.507 |

KGE still misses the 0.60 target. Terrain bytes, original HEC-HMS inflow,
mesh, solver settings and initialization are retained for this comparison.
The earlier timed-Warsak inflow candidate is not mixed into this run.
This is further development on an inspected event, not new independent
validation. No independent flood extent or water-level validation was added.

Native plan HDF SHA-256:
`950b7172d8a17ec50572f1857790dda99f1f32cd17716905b1f94a8b5669912d`.
Publication rejects uniform or invalid native roughness, missing land-cover
associations, incomplete/unstable output, excessive volume error, unconverged
initialization and missing wet connectivity. A process-success flag alone
does not establish acceptance.

## Why the surveyed-geometry requirement remains open

No bathymetric survey or channel-section files were found in this workspace
or the relevant local flood-data projects. The public
[AIIB Nowshera–Peshawar engineering report](https://www.aiib.org/en/projects/details/2025/_download/Pakistan/ESIA-Vol.-3-Climate-Reports-Detailed-Design-Report-Section-8-Nowshera-Peshawar-Combined-26-12-2024.pdf)
describes bridge surveys, but does not provide a usable full-reach,
georeferenced channel-bed dataset with elevations, datum and coverage for this
model. Its example figures were not converted into invented survey data.
This does not establish that the responsible agencies have no surveys; the
required dataset has not been obtained.

A further public-source check on 23 October 2026 found that PCRWR's published
measured sections cover other rivers, while FFC describes its Kabul/Swat
riverbed sections as DEM-derived. The [survey data request](SURVEY_DATA_REQUEST.md)
records these findings and provides a local package with the exact model
footprint, minimum channel-coverage reference and delivery/review templates.
The package contains no measured bed elevations and has not been sent.

Finishing the requirement needs actual surveyed channel/bed elevations,
horizontal and vertical references, survey date, measurement method,
reviewed reach coverage and a terrain representation suitable for the model.
Structures, bank/levee levels and channel changes also need separate review.

## Survey import contract

The importer accepts a **GIS-reviewed hydraulic terrain raster derived from
real measurements**, an explicit 0/1 survey-coverage raster and review JSON.
Raw XYZ points or sparse sections require a reviewed terrain-building step
first. Python does not choose an interpolation surface, extend survey
coverage or guess datum corrections.

Both rasters must match the original projected hydraulic terrain grid:
EPSG:32642, 100 m, 146×146 cells, and the exact origin/affine transform of
the screening project's `unconditioned-terrain.tif`. Grid aggregation must be
reviewed; this remains too coarse to resolve narrow channels or structures.
The coverage raster must have **no nodata**: 0=outside declared survey and
1=covered. Every resolved model-channel cell must be covered with finite
elevations. Partial channel coverage is refused without estimated gap filling.
Outside declared survey coverage, original unconditioned FABDEM is retained.

Required JSON fields follow. Empty fields and zero slope deliberately fail
acceptance; fill them with the actual reviewed source and hashes.

```json
{
  "terrain": "survey-terrain-100m.tif",
  "terrain_sha256": "",
  "coverage": "survey-coverage-100m.tif",
  "coverage_sha256": "",
  "source": "",
  "survey_date": "",
  "survey_method": "",
  "review": "",
  "grid_aggregation_review": "",
  "historical_representativeness_review": "",
  "channel_bed_measured": true,
  "is_dem_derived_bathymetry": false,
  "elevation_units": "m",
  "source_vertical_datum": "",
  "vertical_datum": "EGM2008",
  "vertical_transformation_review": "",
  "reviewed_boundary_slope": 0
}
```

Elevations must already be reviewed in EGM2008 meters. A different source
datum needs a documented transformation. The review must address whether
the survey represents the 2022 channel and how it was gridded. Accepted
survey terrain replaces the estimated-channel report and boundary slope in
a new source model. Source/coverage acceptance does not establish hydraulic
calibration or validation of all floodplain geometry and structures.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m server.geometry_inputs prepare
.\.venv\Scripts\python.exe -m server.geometry_inputs build
.\.venv\Scripts\python.exe -m server.geometry_inputs run
# Only when a real reviewed survey is available:
.\.venv\Scripts\python.exe -m server.geometry_inputs run --survey D:\survey\review.json
```

Inputs are in `workspace/geometry/<fingerprint>/`. The variant index is
`workspace/hecras/variants/87781e7f87c5.json`; its `project` path identifies
the source. The `latest-run.json` beside that source directory identifies
the native run. Preserve the index, source, run HDF, binding, domain,
numerical review and published results together. Failed preparations are
retained, and retries use fresh directories.
