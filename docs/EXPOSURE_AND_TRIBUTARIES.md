# Exposure layers and tributary audit — 4 November 2026

Two additions make the published Nowshera simulations easier to interpret:

1. **Exposure**: who and what lies under the modelled water.
2. **Tributary audit**: which real streams enter each hydraulic model, and which of them the model actually feeds.

Neither changes a model, a binding or a published result. Exposure layers live in `workspace/exposure/` rather than `assets.json`, so model input hashes are unaffected.

## Exposure

### Sources

| Layer | Product | Licence | Notes |
| --- | --- | --- | --- |
| Population | [WorldPop Global2 R2024B, Pakistan 2022, constrained ~100 m](https://data.worldpop.org/GIS/Population/Global_2015_2030/R2024B/2022/PAK/v1/100m/constrained/pak_pop_2022_CN_100m_R2024B_v1.tif) | CC BY 4.0 | Modelled residential counts constrained to mapped settlements; the event year. Clipped to the pilot bounds (71.72–72.24 °E, 33.79–34.23 °N): about 3.63 million people. |
| Facilities | OpenStreetMap amenities `hospital`, `clinic`, `doctors`, `school`, `college`, `university`, `police`, `fire_station` via the Overpass API | ODbL 1.0 | 90 in the pilot bounds (32 health, 41 education, 17 emergency). Volunteered mapping, so **coverage is incomplete**, especially for schools. Areas are represented by their centre. |

`python -m server.exposure acquire` downloads both, writes `workspace/exposure/layers.json` with source and file SHA-256s, and renders a population-density overlay (people/km²; classes <250, 250–1k, 1k–5k, 5k–20k, >20k).

### Method

For each frame of a published result:

- Each populated WorldPop cell takes the depth of the model raster cell containing its centre.
- Residents are counted at ≥ 0.3 m and ≥ 1 m. These match the first two depth-legend edges, so map colours and counts agree.
- Cells already wet in the first published frame are excluded. That is the river at the start of the event, plus bank cells where the 100 m model grid and the population grid don't line up. Without this rule, 1,100–1,500 riverbank residents would be counted as "flooded" before the flood began.
- Facilities use the depth at their point. A facility counts as flooded at ≥ 0.3 m.
- **3D population columns** (map button *Population 3D*): residents are summed into 6 × 6 WorldPop cells (0.005°, about 460 × 555 m). Each column's height is linear in its residents: 100 m per 500 people. As playback runs, the base of the column fills dark red for residents in ≥ 1 m of water and red for 0.3–1 m. The rest is drawn in translucent sand. Clicking a column shows its counts at the current model time. The columns sum exactly to the panel's per-frame counts, with the same start-wet exclusion. Column bases use the viewer's own FABDEM heights, display only, set 3 m below the lowest of five sampled points. Data: `GET /api/results/{id}/exposure/columns`, gzip-compressed, about 20 KB per result.
- Every depth GeoTIFF's SHA-256 is checked against the result manifest before it is read. Output is cached by result, method version and layer hashes in `workspace/exposure/results/`.

### Current results

| Result | Residents in model raster | Peak in ≥ 0.3 m | Peak time (UTC) | Facilities flooded / in extent |
| --- | ---: | ---: | --- | ---: |
| HEC-RAS 2D | 477,091 | 81,636 (53,798 in ≥ 1 m) | 2022-08-27 20:00 | 8 / 23 |
| HEC-RAS 2D, zoned roughness | 477,091 | 104,115 | 2022-08-27 22:00 | 10 / 23 |
| LISFLOOD-FP screening | 477,091 | 61,355 | 2022-08-28 03:00 | 4 / 23 |

These numbers inherit every limitation of the uncalibrated simulations, and differ by about 70% between cases. They describe where the models put water, not observed 2022 impacts. Residence is night-time population, and no evacuation or displacement is represented. **They are not casualty, displacement or damage estimates.**

## Tributary audit

### Method

`python -m server.tributaries audit <result-id>`:

1. Takes the published depth-raster footprint as the model boundary.
2. Reads the model's actual inflow boundaries:
   - **HEC-RAS:** BC lines whose unsteady boundary is a flow hydrograph (`.g01`/`.u01`).
   - **LISFLOOD-FP:** `QVAR`/`QFIX`/`HVAR`/`HFIX` edges of the `.bci` file.
3. Lists every HydroRIVERS reach that starts outside the footprint and crosses into it.
4. Marks a stream **represented** when its edge crossing lies within 500 m of an inflow line.

Names come from OpenStreetMap waterways within 750 m of the crossing (`python -m server.tributaries names`). Reviewed transliterations are in `server/data/waterway-aliases.json`. Mean discharge is HydroRIVERS' long-term modelled average, not a 2022 flow.

### Finding: the Kalpani gets no water

All three published cases give the same result:

| Stream | Drains | Long-term mean | Enters | In the model |
| --- | ---: | ---: | --- | --- |
| Kabul River | 89,178 km² | 1,185 m³/s | west | HEC-HMS aggregate inflow |
| **Kalpani** | **2,708 km²** | **50.9 m³/s** | **north** | **no inflow** |
| 5 minor local streams | 19–53 km² each | 1.3 m³/s total | south, east | no inflow |

The Kalpani (OSM `کلپانی`, matched within 49 m) drains the Mardan side of the basin. It enters across the northern model edge near Risalpur and joins the Kabul at about 72.035 °E, 34.023 °N. That is **downstream of the Nowshera gauge line**, so:

- the withheld Nowshera gauge scores cannot reveal its absence;
- inundation below the confluence (east Nowshera, Pir Sabak) is probably underestimated in every case.

For scale, KP PDMA's daily reports give *Kalpani Nullah at Chowki Risalpur* at up to 26,571 cusecs (≈ 752 m³/s) on the 28 August report. The Kabul at Nowshera was 311,143 cusecs that day. These river tables carry **no observation time** (see [inflow improvement](INFLOW_IMPROVEMENT.md)), and the 26–27 August reports are missing, so they are shown as reference only and never used as forcing.

### What would actually fix it

A Kalpani inflow boundary needs a defensible hydrograph. Options, from most to least defensible:

1. **A timestamped Kalpani record** (Irrigation Department or PDMA source log at Risalpur or Mardan), routed to the model edge.
2. **A reviewed HEC-HMS rainfall–runoff model** of the Kalpani catchment from the registered CHIRPS rainfall and soils, checked against the untimed PDMA magnitudes. This is uncalibrated, and CHIRPS is daily, so storm timing within a day is assumed.
3. **A labelled sensitivity case** forcing the untimed PDMA daily values, held per report day. It answers "how much does including the Kalpani change flooding below the confluence?", but it cannot be presented as a hindcast.

Each would be a new, separately hash-bound HEC-RAS case with a second inflow line on the northern edge. The existing published results remain unchanged.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m server.exposure acquire
.\.venv\Scripts\python.exe -m server.tributaries names
.\.venv\Scripts\python.exe -m server.exposure compute nowshera-hecras-0b012877-f7bc61d16eb7
.\.venv\Scripts\python.exe -m server.tributaries audit nowshera-hecras-0b012877-f7bc61d16eb7
```

API: `GET /api/exposure`, `/api/exposure/population.png`, `/api/exposure/facilities`, `/api/results/{id}/exposure`, `/api/results/{id}/exposure/columns` and `/api/results/{id}/tributaries`. The result endpoints compute on demand and return `{"available": false, "reason": …}` when a layer has not been acquired.
