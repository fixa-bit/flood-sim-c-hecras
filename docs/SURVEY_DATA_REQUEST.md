# Nowshera channel survey data request — 23 October 2026

**Still missing: measured channel geometry.** The public-source review below
did not obtain a usable bed survey for this model. The current bed remains
estimated. The prepared package defines the area and delivery requirements;
it contains no surveyed elevations and has not been sent to any agency.

The subsequent [detailed investigation](BATHYMETRY_INVESTIGATION.md) adds
specific acquisition leads and an observation-constrained fallback. For KP
Irrigation, reference schemes **140523, 140524, 140525, 150383 and 150715**
from its [2020–21 ADP, PDF p.4](https://www.irrigation.gkp.pk/files/ADP2020-21.pdf).
Ask for original measured bed/bank sections, leveling/benchmark sheets,
survey dates, design/as-built drawings and native model files. Project
identifiers do not establish that acceptable bed data exist or are available.

## Request package

Local package: `workspace/survey-request/nowshera-2026-10-23.zip`.
The matching directory contains the following attachments:

| File | Purpose |
| --- | --- |
| `model-footprint.geojson` | Exact terrain-grid footprint and Nowshera outlet in longitude/latitude |
| `required-channel-coverage.geojson` | Polygonized model channel cells; a minimum coverage reference derived from mapped water, not surveyed bank lines |
| `model-grid.json` | Target grid, source hashes, bounds and explicit missing-survey status |
| `bed-measurements.template.csv` | Empty example delivery columns for actual measured points; no invented sample records |
| `survey-review.template.json` | Incomplete review template for the existing terrain importer |
| `source-audit.json` | Sources checked and reasons they have not supplied an accepted survey |
| `REQUEST.md` | This request and acceptance requirements |
| `BATHYMETRY_INVESTIGATION.md` | Subsequent source investigation, newly acquired preview data and alternatives |
| `GEOMETRY_ROUGHNESS.md` | Current model status and survey import contract |
| `checksums.sha256` | Attachment integrity hashes |

These are model-specific planning attachments. They do not establish that
the mapped channel captures every active branch or that survey coverage is
adequate for floodplain structures. A surveyor/hydraulic reviewer must decide
where extra sections, bank levels and structure surveys are needed.

## Text to provide to a data custodian

Please provide existing measured riverbed and bank geometry for the Kabul
River through the attached Nowshera pilot area. We are reconstructing the
20 August–5 September 2022 flood. We need original survey files and their
control/quality records, rather than cross sections extracted from a surface
DEM or river depths inferred from discharge.

The current model terrain covers **14.6 × 14.6 km**, in WGS 84 / UTM zone 42N
(EPSG:32642): easting **767800–782400 m**, northing **3760000–3774600 m**.
The enclosing geographic bounds are approximately **71.897619–72.060118° E,
33.942615–34.077940° N**; use the GeoJSON for the projected rectangle's exact
footprint. This is the local pilot, not the entire Warsak–Attock reach.

Please include:

1. Original georeferenced bed soundings/points or cross sections, with section
   IDs, ordered point locations and bank/thalweg identifiers where available.
   CSV/XYZ, GeoPackage, surveyed CAD, ADCP/sonar exports or a documented native
   hydraulic model with its source measurements are useful. Station–elevation
   pairs also need georeferenced cutlines and their stationing convention.
2. Horizontal CRS and units; vertical datum, elevation units, benchmark IDs,
   control-point coordinates/elevations and leveling/GNSS/geoid records. A
   label such as “MSL” without a traceable reference is insufficient. If the
   delivered measurements are water depths, include the contemporaneous
   water-surface elevations and instrument corrections needed to recover
   bed elevations in that reference.
3. Acquisition dates, measurement method, instrument/draft corrections,
   accuracy/uncertainty and quality-control records, including gaps and
   rejected observations. Please distinguish measured and interpolated data.
4. Coverage of the active channels from the model's upstream boundary to its
   downstream boundary, including branches and hydraulic controls. The
   attached mapped-water mask contains **725 cells at 100 m**; it is only a
   minimum reference for compatibility with the current importer, not a
   proposed survey spacing or an assertion of continuous measured coverage.
5. Available bank/levee crest lines and levels, bridge/culvert openings and
   piers, and changes due to scour, deposition or construction. Identify
   whether these describe conditions before, during or after the 2022 flood.
   A later survey needs a review of its relevance to that event.
6. Data-use terms, source ownership and the contact responsible for the
   survey's technical metadata.

KP Irrigation, the relevant NESPAK project custodians and WAPDA's hydrology
services are **possible enquiry routes**, not confirmed holders of a usable
dataset for this exact reach. The engineering sources below provide project
leads. The original project survey/model files and benchmark sheets are the
requested deliverables; a report citation does not prove their availability.

## Public-source audit

| Primary source checked | Finding and consequence |
| --- | --- |
| [PCRWR, Hydro-Morphology of the Tributaries and Active Flood Plains of the River Indus (2021)](https://pcrwr.gov.pk/wp-content/uploads/2020/Water-Management-Reports/Hydro-Morphology%20%2821%20September-2021%29.pdf), printed p.17, Table 2 | The 50 measured sections are on the Jhelum, Chenab, Ravi and Sutlej. They do not supply Kabul/Nowshera bed measurements. The downloaded PDF is archived locally with SHA-256 in `source-audit.json`. |
| [FFC, NFPP-IV Task C: Floodplain Mapping](https://ffc.gov.pk/wp-content/uploads/2022/08/Task-C-Floodplain-Mapping.pdf), p.2-31 | The Kabul/Swat riverbed geometry is described as extracted from the project's DEM; bridges were measured separately. This does not supply the measured full-reach bed dataset required here. The passage was checked through the indexed official report; a local PDF download failed certificate verification. |
| [AIIB, Nowshera–Peshawar detailed engineering report (2024)](https://www.aiib.org/en/projects/details/2025/_download/Pakistan/ESIA-Vol.-3-Climate-Reports-Detailed-Design-Report-Section-8-Nowshera-Peshawar-Combined-26-12-2024.pdf), §3.4.1.1, printed pp.39–40 | Describes cross-sectional surveys for bridge analyses. A usable full-reach, georeferenced bed dataset with vertical-control records was not obtained from this public report. Original survey files would need separate acquisition and review. |
| [CEWRE thesis catalogue](https://cewre.edu.pk/web/dissertation-thesis/), Qudsia Latif (2007), *Effect of channel improvement on water levels for Kabul River under flood conditions* | Confirms a relevant thesis exists. Its original geometry, survey evidence, datum and relevance to 2022 have not been obtained or verified. It is a lead, not an accepted survey. |

These findings describe the sources checked. They do not establish that no
relevant survey exists in agency or consultant archives.

## What happens after delivery

Preserve the raw measurements and their hashes. A GIS/hydraulic review must
check the datum, reach coverage, historical relevance and terrain-building
method before importing elevations. Retain the original resolution and
control data; **100 m is the current model grid, not a recommended acquisition
resolution**. The model may need refinement to retain narrow channels and
hydraulic controls.

The current importer accepts a reviewed single-band terrain raster and an
explicit 0/1 coverage raster, both on this exact grid: EPSG:32642, 146 × 146,
100 m pixels, affine coefficients `[100, 0, 767800, 0, -100, 3774600]`.
Coverage must have no nodata, and every current channel cell must be covered
by finite reviewed bed elevations. Coverage cannot be asserted solely because
a polygon or an interpolation spans the reach. Outside declared survey
coverage, the importer retains the original unconditioned terrain.

Target elevations are **EGM2008 metres**. A different source datum requires a
documented, reviewed transformation, with the source control preserved. Do
not use a guessed constant offset. The template intentionally has blank
fields, false measurement flags and an invalid zero slope, so it is not an
acceptable survey review until completed from actual evidence.

After review, run:

```powershell
.\.venv\Scripts\python.exe -m server.geometry_inputs run --survey D:\survey\review.json
```

This creates a separate native HEC-RAS case; acceptance of survey inputs alone
does not establish hydraulic calibration. LISFLOOD needs a separate rebuilt
and bound model using the same accepted terrain before a new comparison is
valid. See [the import contract and current results](GEOMETRY_ROUGHNESS.md).
