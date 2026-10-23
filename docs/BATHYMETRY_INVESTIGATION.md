# Nowshera bathymetry investigation — 23 October 2026

**Finding:** a usable, measured, full-reach riverbed survey has still not been
obtained. There are specific agency/project leads and an additional satellite
data route worth pursuing. It is premature to conclude that the data cannot
be obtained. The current model bed remains **estimated**.

The investigation acquired **22 public ICESat-2 water-surface preview points
dated 27 March 2022**, of which **15 intersect the current model channel mask**,
and photon previews for March and August. **Zero points have been accepted as
bed measurements.** Water levels and signal photons do not by themselves
establish a bed elevation, vertical control or continuous survey coverage.

## Priority 1: obtain original measurements

The request area is the local Nowshera pilot: 14.6 × 14.6 km, EPSG:32642,
easting 767800–782400 m, northing 3760000–3774600 m. Its mapped channel has
725 cells at 100 m. The [request package](SURVEY_DATA_REQUEST.md) contains the
exact footprint and coverage reference. It is not the entire Warsak–Attock
reach, and the mapped-water mask is not a surveyed bank boundary.

| Acquisition route | Evidence found | What is still needed |
| --- | --- | --- |
| **KP Irrigation: start here** | Its [2020–21 ADP, PDF p.4](https://www.irrigation.gkp.pk/files/ADP2020-21.pdf) identifies right-bank embankment schemes **140523, 140524, 140525**, right-bank protection near the Nowshera–Mardan bridge **150383**, and left-bank protection **150715**. These are specific pre-2022 project leads. | Original survey fieldbooks/XYZ/cross sections, benchmark/leveling records, design and as-built drawings, and native model files. The ADP proves that projects existed; it does not prove that a usable bed survey is held or establish its coverage. |
| **NESPAK/NHA/KP project custodians** | The [AIIB Nowshera–Peshawar engineering report](https://www.aiib.org/en/projects/details/2025/_download/Pakistan/ESIA-Vol.-3-Climate-Reports-Detailed-Design-Report-Section-8-Nowshera-Peshawar-Combined-26-12-2024.pdf), printed pp.39–41, describes surveyed cross sections around road bridges. Printed p.36 discusses Kabul flood protection works under EFAP. | Original survey and structure files, exact locations, dates and vertical control. The typical bridge figures do not provide measured geometry for the full pilot. Later construction/surveys need a separate assessment of 2022 conditions. |
| **ECIL/NHA motorway bridge archive** | The designer's [Kabul River motorway bridge project record](https://www.ecil.com/projects/details/River-Bridge-Over-Kabul-River-in-Islamabad-Peshawar-Motorway) explicitly lists riverbed surveying among its services for a project dated 1992–2007. | Original deliverables, benchmarks and location/coverage checks. The page was inspected through indexed primary text; direct download failed certificate verification. This older, local bridge survey is not assumed to cover this pilot or represent its 2022 bed. |
| **CEWRE/UET Lahore research archive** | The [official catalogue](https://cewre.edu.pk/web/dissertation-thesis/) lists Qudsia Latif's 2007 Kabul channel-improvement thesis and Muhammad Zia ul Islam's 2012 Nowshera flood-mapping thesis. | Full theses, original geometry and their measurement/control evidence. A relevant title or HEC-RAS model is not proof of surveyed bathymetry. |
| **Authors of a regional MIKE11 study** | The [2023 CPEC hydrodynamic study](https://doi.org/10.3390/w15244295), PDF pp.4–5 and 21, combines government-provided and DEM-derived sections; its data are available by author request. | Confirmation of Kabul/Nowshera coverage, original measured sections and control metadata. The paper does not establish that its files contain an acceptable survey for this reach. |

No agency, author or consultant has been contacted. Updated request text and
project identifiers are prepared locally; no external messages were sent.
WAPDA hydrology services remain a further enquiry route for gauge sections,
rating-curve surveys and gauge-zero/benchmark history, with holdings unconfirmed.

## Priority 2: inspect specific satellite files

[NASA's ATL13 Version 7](https://nsidc.org/data/atl13/versions/7) includes
shallow-water bathymetry where detection permits, in addition to water-surface
observations. This is a more relevant lead than a general surface DEM.
**Its availability over a river does not guarantee bottom detections.**

Queries of NASA's public CMR catalogue for the pilot bounds found **10 ATL13
and 10 ATL03 granules in 2022**, and **none in the broader event query window
20 August–6 September 2022**. Metadata responses are archived locally. These
results concern the queried Version 7 collections; they are not proof that
all missions, versions or agency archives lack observations.

Prioritize these ATL13 files for inspection:

| Granule start date | File |
| --- | --- |
| 18 August 2022: close to the flood, before the displayed event | `ATL13_20220818013817_08731601_007_01.h5` |
| 27 March 2022: public water-surface preview exists | `ATL13_20220327204633_00731501_007_01.h5` |
| 17 February 2022: another pre-flood candidate | `ATL13_20220217101825_08731401_007_01.h5` |

The full files require a **free NASA Earthdata account**. No Earthdata
credentials are configured in this environment. The local
`atl13-2022-discovery-summary.json` records all ten file names and official
download URLs. Catalogue footprints are broad; they cannot be counted as
measured channel coverage. A four-orbit ATL13 file's starting track number is
also not necessarily the track crossing Nowshera.

What was actually downloaded anonymously:

- The [OpenAltimetry](https://nsidc.org/openaltimetry/about) preview for
  **27 March 2022, actual reference track 74** contains 22 water-surface
  observations, 15 inside the current channel mask. Per-point bottom depths,
  quality flags, geoid terms and processing-version metadata are absent from
  this preview. Its returned elevation reference must be verified before use.
- Raw photon previews were obtained for that pass and **18 August 2022,
  track 874**. The August response yielded no photons in the current mapped
  channel mask; its ATL13 water-surface response was empty. This is not proof
  that every other date lacks useful data.
- Signal-confidence labels in an ATL03 preview do not identify bed returns.
  [ATL03 heights are ellipsoidal](https://nsidc.org/openaltimetry/about);
  they must not be subtracted directly from the model's orthometric terrain
  or from preview heights with an unverified reference.

The [ATL13 data dictionary](https://nsidc.org/sites/default/files/documents/technical-reference/icesat2_atl13_data_dict_v007.pdf)
provides refraction-corrected bottom locations, depth and a subsurface anomaly
flag. A flag of 1 means a likely bottom; other flags are ambiguous. Inspection
must also check fill values, surface quality, cloud/shore effects, photon
profiles, actual river intersection and uncertainty. A likely-bottom flag
alone is not sufficient acceptance evidence.

The [user guide](https://nsidc.org/sites/default/files/documents/user-guide/atl13-v007-userguide.pdf)
distinguishes EGM2008 orthometric surface heights from ellipsoidal heights and
documents geoid information. For accepted bottom detections, derive bed
elevations using the documented depth/reference convention, retain the actual
bottom coordinates and observation time, and review the geoid and tide system
against the terrain. Do not guess an offset or apply refraction corrections
twice. Sparse valid returns would constrain a **hybrid** bed, not establish
full-reach survey coverage.

## Sources that do not close the gap

| Source | Why it cannot be used as the missing measured bed |
| --- | --- |
| [PCRWR hydro-morphology survey report](https://pcrwr.gov.pk/wp-content/uploads/2020/Water-Management-Reports/Hydro-Morphology%20%2821%20September-2021%29.pdf), printed p.17 | Its 50 surveyed sections are on Jhelum, Chenab, Ravi and Sutlej, not Kabul/Nowshera. |
| [FFC NFPP-IV Task C](https://ffc.gov.pk/wp-content/uploads/2022/08/Task-C-Floodplain-Mapping.pdf), p.2-31 | Kabul/Swat riverbed sections are described as DEM-derived; bridge measurements are separate. |
| [CKRB geoportal documentation](https://www.ckrb.org/var/cache/87396-9cb45705a4620a78129d12dfbd18ca18/High-resolution_data_and_groundwater_modeling.pdf) | Its described basin products are 1 km grids based on surface elevation and other regional data, not a Nowshera bed survey. |
| [Peshawar running-water-volume study](https://doi.org/10.3390/su14073754), PDF pp.7, 21 | Rainfall, land-cover and runoff-volume analysis; no usable bed measurements/control were supplied. Data are by author request. |
| [DAHITI target 22319](https://dahiti.dgfi.tum.de/en/22319/) | The station is at 71.3174° E, 34.2661° N, about **67.2 km straight-line** from the model outlet. It reports water levels outside this pilot; its levels cannot be transferred directly to Nowshera bed elevations. |
| [SWOT](https://swot.jpl.nasa.gov/news/99/joint-nasa-cnes-water-tracking-satellite-reveals-first-stunning-views/) | Launched 16 December 2022, after the August flood. Later water levels/widths/slopes may constrain a later geometry, with a separate channel-change review; they do not supply August 2022 survey measurements. |

Two newer global products can help define **priors**, with further local
coverage checks. [GQBF](https://doi.org/10.1038/s41467-026-76433-3) estimates
bankfull discharge; even its observed discharge training sites are not a
replacement for georeferenced bed sections and vertical-control records.
It also cautions against assuming that bankfull flow everywhere equals a
2-year flood. The 2026 [global bankfull-depth dataset](https://zenodo.org/records/19176596)
contains model-estimated average depths and has restricted files. It has not
been downloaded or checked for this reach. Neither product closes the
measured-bed requirement; both could inform a reviewed sensitivity study.
The [GLOW repository](https://zenodo.org/records/6425657) provides historical
river widths and transect locations, not surveyed bottom elevations.

## Alternatives if a full survey is unavailable

| Approach | What it needs and can achieve | Appropriate label |
| --- | --- | --- |
| **Targeted field survey plus reviewed interpolation** | Measure bed/banks and controls at boundaries, bridges, confluences, bends and channel changes, tied to surveyed benchmarks. Retain dry-bank/levee observations and underwater measurements. A hydraulic reviewer chooses section spacing and interpolation extent. This is the strongest route to measured geometry. | Survey-based terrain, with measured versus interpolated coverage documented |
| **Sparse measured anchors plus reconstruction** | Use verified archive sections or valid satellite bottom returns as anchors; infer gaps using bank geometry, hydraulic constraints and a reviewed surface-building method. Track the two evidence types separately. | Hybrid: measured constraints plus estimated gaps |
| **Observation-constrained hydraulic inversion** | Use contemporaneous discharge and datum-checked water levels, widths and/or surface velocities across several flows to estimate a small number of smooth bed parameters. Check against independent water levels and flood extents. Feasible in principle; the necessary observations are not yet complete here. | Estimated, constrained by observations |
| **Hydraulic-geometry sensitivity ensemble** | Construct physically plausible beds using reviewed widths, slopes, cross-section shapes and conveyance assumptions; run them through both native engines. It quantifies sensitivity when observations are insufficient, rather than proving which bed is correct. | Estimated; scenario range |
| **Floodplain screening without full channel detail** | Some methods simulate excess flow above assumed channel capacity. Capacity, routing and channel/floodplain exchange remain uncertain, especially in complex reaches; this is a separate approximation requiring review. | Screening approximation |

A [USGS bathymetric survey example](https://data.usgs.gov/datacatalog/data/USGS%3A6272b722d34e76103cd644ee)
illustrates how corrected acoustic depths are tied to RTK-GNSS transducer
elevations and documented datums. Its US datums and accuracy do not transfer
to Pakistan. A new local survey also needs a review of how post-2022 scour,
deposition and construction affect reconstruction of the historical event.

[Neal et al. (2021)](https://doi.org/10.1029/2020WR028301) provides a basis for
estimating channel conveyance/bathymetry with hydraulic constraints, including
gradually varied flow. Its published improvements elsewhere are not promised
performance gains for Nowshera. The present bed already uses a rectangular
Manning normal-depth estimate; simply renaming that method is not an advance.

[Nguyen et al. (2026)](https://hess.copernicus.org/articles/30/183/2026/)
demonstrates why width, slope and flow assumptions should be varied when
assessing bathymetry-driven flood uncertainty. Its New Zealand error model and
parameter ranges must not be adopted as validated local uncertainties here.

## Recommended fallback for this project

1. Finish the two promising acquisition routes above: original project
   measurements and full ATL13 quality/bottom fields. Keep the March preview
   points as candidate water-level evidence until their datum and quality are
   checked. Do not combine March levels with August discharge as though they
   were simultaneous observations.
2. Obtain date-matched low-flow widths and water levels/discharge where
   possible. Use dated flood-extent scenes for spatial checks, with acquisition
   time, permanent water, cloud/shadow and uncertainty handled explicitly.
   A cumulative maximum-extent map cannot validate a single model timestamp.
3. Build a **separate observation-constrained estimated-bed case** if the
   evidence supports it. Use a few smooth bed/conveyance parameters and
   physically reviewed limits. Account separately for inflow and roughness
   uncertainty so that bed changes do not merely compensate for bad forcing.
   If evidence remains insufficient, publish a sensitivity ensemble instead
   of choosing a supposedly accurate bed.
4. Retain the best available floodplain terrain and review bank/levee/bridge
   controls. The current 100 m terrain and 200 m HEC-RAS mesh can erase narrow
   features. Finer measurements need a reviewed terrain/mesh refinement and
   convergence check; resampling a coarse DEM does not create measured detail.
5. Produce one documented terrain/evidence package, then rebuild **both
   HEC-RAS and LISFLOOD** from it with matching inflows and scenario times.
   HEC-RAS needs new native terrain, geometry preprocessing and associations;
   LISFLOOD needs a new DEM/project/binding. Switching the engine selector
   alone does not transfer changed terrain between prepared cases.
6. Check native mass balance, stable initialization, wet connectivity and
   complete timestamped rasters. Then assess water-level bias/RMSE, date-matched
   flood extent and discharge. Reserve independent observations/events before
   tuning. The already-inspected withheld discharge set is development
   evidence; it is no longer an untouched test for further tuning.
7. Show the evidence class and unresolved coverage in the app: **estimated**,
   **hybrid**, or **survey-based**. An ensemble's minimum/maximum or percentiles
   are conditional scenario ranges unless a defensible probability model has
   been established. Preserve original cases and compare matching timestamps.

[USACE documents](https://www.hec.usace.army.mil/confluence/rasdocs/hgt/latest/tutorials/terrain/terrain-modification)
merging cross-section channel terrain with overbank terrain. Those tools help
apply geometry once it is justified; they do not obtain or verify missing
measurements. The current survey-only importer correctly refuses incomplete
coverage. A hybrid/inferred case needs its own provenance path rather than
passing estimated gaps through the full-survey gate.

## Deliverables and verification

The combined request, discovery records and public-preview data are packaged
in `workspace/survey-request/nowshera-bathymetry-investigation-2026-10-23.zip`.
Official research PDFs are archived locally and referenced by URL/hash rather
than copied into that package.

Research files are in
`workspace/research/bathymetry-investigation-2026-10-23/`:

- Official PDF downloads and hashes; NASA discovery responses; the public
  March/August preview responses. Raw downloads are preserved separately
  from interpreted data.
- `water-surface-preview-20220327.csv` and `.geojson`: the 22 returned water
  levels, with unverified preview datum/version clearly marked. GeoJSON uses
  2D locations; reported height is an attribute, not an accepted bed Z value.
- `preview-audit.json`: point/beam counts and channel-mask intersections;
  **accepted bed points = 0**, **bed_is_surveyed = false**.
- `acquisition-manifest.json` and `checksums.sha256`: source URLs, file
  integrity, query parameters and access limitations.
- `export-evidence.py`: rerun from the project root with the project's Python
  environment to reproduce preview exports and channel-mask counts from the
  preserved downloads. It does not change model inputs or accept bed points.

Verified that exported locations match the actual responses and that channel
membership is sampled from the original mask on its projected grid. The
incomplete survey template is still rejected by the importer. This research
does not replace the terrain, create a new hydraulic result or claim an
improvement in KGE. No code/engine installation can supply missing physical
observations by itself.
