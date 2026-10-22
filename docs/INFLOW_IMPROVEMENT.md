# Shared inflow improvement — 22 October 2026

The first data improvement is prepared and computed in HEC-HMS as a separate
candidate. It is **not yet a complete inflow fix**, and has not replaced either
published HEC-RAS or LISFLOOD result. Both existing hydraulic cases still use the
original shared HEC-HMS hydrograph.

## Additional verified observations

Page 1 of the original Federal Flood Commission reports contains three timed
Warsak observations omitted from the baseline's 06:00 PKT daily tables:

| Local observation time (PKT) | Warsak discharge (cusecs) | Original document |
| --- | ---: | --- |
| 26 August 2022, 12:00 | 106,000 | [FFC 26 August](https://www.ffc.gov.pk/wp-content/uploads/2022/08/DFSR-26-08-2022.pdf) |
| 27 August 2022, 12:30 | 139,000 | [FFC 27 August](https://www.ffc.gov.pk/wp-content/uploads/2022/08/DFSR-27-08-2022.pdf) |
| 28 August 2022, 13:00 | 120,000 | [FFC 28 August](https://www.ffc.gov.pk/wp-content/uploads/2022/08/DFSR-28-08-2022.pdf) |

The reviewed transcription, units, times, source URLs, pages and PDF hashes are
in `server/data/ffc-subdaily-2022.json`. The preparation command verifies those
PDF hashes before using the observations. Rendered review images are under
`workspace/downloads/nowshera-2022/references/review/upstream-narrative-*.png`.
The 12:30 PKT observation remains at 07:30 UTC in `observations.csv`. Neighboring
hourly model inputs are explicitly interpolated, not relabeled observations;
hourly resampling does not retain that exact half-hour peak ordinate.

The candidate has 20 Warsak and 17 Swat/Khiali at Charsadda Road observations.
Both stations still have maximum observation gaps of 24 hours. This is sparse
additional evidence, not a continuous subdaily gauge record.

## Controlled HEC-HMS result

HEC-HMS 4.14 recomputed the full 385-hourly-ordinate event using the original
Warsak/Swat Muskingum K values (12/6 hours, x=0). No routing coefficient or
lateral constant was refitted. The baseline lateral estimate, 732.848 m³/s,
remains only for this controlled comparison.

| Metric | Original shared inflow | Timed Warsak candidate |
| --- | ---: | ---: |
| Withheld samples | 8 | 8 |
| Withheld NSE | 0.678277 | 0.686689 |
| Withheld KGE | 0.461787 | 0.469270 |
| Withheld RMSE (m³/s) | 1,338.764 | 1,321.145 |
| Modeled event peak (m³/s) | 7,772.958 | 7,926.316 |

The small change does not solve the flattening or meet the 0.60 KGE target.
These scores assess the shared **HEC-HMS inflow**, not new hydraulic runs.
Nowshera observations are used only for scoring this candidate. Because this
is further development on an already inspected event, the comparison is not
new independent validation.

## Lateral sources and remaining evidence

The public [KP PDMA daily weather reports](https://rms.pdma.gov.pk/DWRs.aspx)
include actual Bara, Budni, Jindi and other river readings. Seventeen dated
reports, 20 August–5 September 2022 (DWR IDs 1102–1118), were downloaded and
preserved with hashes, yielding 288 reference rows. Their river tables give
**no observation time**. Assigning midnight, 06:00, or the report publication
time would invent a hydrograph. They remain excluded from forcing. For example,
[28 August's report](https://rms.pdma.gov.pk/ViewDWR.aspx?DWRID=1110) contains
daily lateral and Swat readings but no observation timestamp.

Raw reports, `source-audit.json` and `untimed-reference-observations.csv` are in
`workspace/downloads/nowshera-2022/references/pdma-dwr-2022/`.

Munda/Chakdara/Khwazakhela are nested upstream of the selected Swat boundary.
Adezai/Naguman/Shah Alam include Kabul distributary flows. Summing these with
the existing boundaries would count the same water twice. An actual lateral
replacement requires reviewed intervening catchments, observed timestamps,
travel times, and routing to the model junction. The code does not infer
laterals by subtracting modeled flow from withheld Nowshera observations.

Needed to finish: timestamped Warsak and Swat at Khiali/Charsadda Road flows,
ideally hourly and at most six-hourly, covering **20 August 2022 06:00 PKT to
5 September 2022 06:00 PKT**, plus reviewed time-varying local contributions.
Those can come from timed independent tributary observations with reach
routing, or a separately reviewed local HEC-HMS rainfall-runoff model. Rainfall
over catchments already represented by the upstream gauges must not be added
again. A source export or Irrigation Department observation log is still needed
to establish the missing times; none is fabricated.

## Run and inspect

```powershell
.\.venv\Scripts\python.exe -m server.inflows all
```

This downloads/caches the public PDMA reference reports, verifies the reviewed
FFC documents, writes the candidate and computes it using the installed
HEC-HMS. It does not edit the baseline study, global assets, hydraulic bindings,
or published results. The existing `server.study_hms` defaults remain unchanged.

Artifacts are under
`workspace/downloads/nowshera-2022/study/inflow-candidates/timed-ffc-v1/`:

- `observations.csv`: exact observation times and provenance.
- `upstream-hourly-interpolated.csv`: explicitly labeled boundary ordinates.
- `boundary-review.json`: coverage, missing evidence, baseline/input hashes.
- `hec-hms/`: native project, DSS inputs/outputs and compute logs.
- `hms-nowshera-hourly-modeled.csv` and `evaluation.json`: computed candidate and scores.

The app's **Data & provenance → Inflow improvement candidate** shows the
comparison and remaining gaps. **Export study** includes the audit. Model
results continue to identify the actual published hydraulic simulations.

Additional reviewed upstream CSVs can be supplied with `--observations PATH` to
`prepare` or `all`. Required columns:

```csv
time,station_id,discharge,units,value_type,source,source_sha256,page_or_record,review
```

Use timezone-aware ISO timestamps, station IDs `warsak` or `charsadda-road`,
units `cusecs` or `m3/s`, and `value_type=observed`. Each row needs its original
source document/export SHA-256 and a transcription review. Conflicting
same-time values, nested gauges, Nowshera inputs, negative/nonfinite flows,
and extrapolation are refused. No timestamped data is accepted merely by
changing an untimed report's date field.

To replace the fitted lateral constant, supply `--laterals PATH
--lateral-review PATH` alongside preparation. This expects a **routed local
hydrograph delivered at the HEC-HMS Nowshera junction**, not a raw tributary
gauge series. CSV columns:

```csv
time,station_id,discharge,units,value_type,source,source_sha256
```

Use `station_id=nowshera-local-laterals`, `units=m3/s`, `value_type=modeled`,
complete bracketing timestamps with no gaps over six hours, and source hashes.
The review JSON must contain the following fields; fill in the actual source,
catchments and routing evidence before importing:

```json
{
  "delivery_location": "HEC-HMS Nowshera junction",
  "includes_upstream_gauged_catchments": false,
  "uses_nowshera_observations": false,
  "contributing_catchments": [],
  "routing_method": "",
  "review": "",
  "all_intervening_catchments_accounted_for": false
}
```

Empty catchment/routing/review fields are rejected. Accepted lateral series
**replace** the baseline constant in the actual HMS DSS input; they are never
added on top of it. Imported local outputs stay labeled modeled. An import
does not automatically establish scientific validity or rebuild either
hydraulic project. This command prepares/evaluates candidate shared inflows;
complete evidence and new hash-bound hydraulic cases are still required before
replacing either published simulation.
