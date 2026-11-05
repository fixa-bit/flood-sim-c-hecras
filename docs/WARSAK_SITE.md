# Warsak below-dam site — prepared 4 November 2026

The Warsak site is a second hydraulic site beside the Nowshera pilot. Every input that does not depend on the dam release is prepared and checked. The model will run once a **continuous Warsak Dam release record** is registered.

## Why it waits for the release record

The only public 2022 Warsak flows are 20 timed Federal Flood Commission readings, with gaps of up to 24 hours. These are the same readings already used inside the Nowshera inflow study. NDMA's 2025 flood-impact report gives only the peak: 139,086 cusecs on 27 August at 12:30. The project owner chose not to interpolate the sparse readings into a model boundary. The build step therefore refuses any record whose ordinates inside the event window are more than **3 hours** apart.

## Model area

- **Window:** the app's Warsak window, 20 km around the station (34.1608 N, 71.3619 E).
- **The reservoir above the dam is not modelled.** That would need the Kabul inflow from Afghanistan and the dam's gate operations, and neither is available.
- **Where the model starts:** a FABDEM/WorldCover profile along HydroRIVERS shows the reservoir surface at ~388–390 m up to 71.353 E. The dam drop comes by 71.360 E, followed by a narrow hill-confined reach. Mapped water becomes continuous from ~71.39 E at 342–344 m. The model's western edge is **71.40 E, about 4 km below the dam**. The dam release enters there.
- **Grid:** 156 × 386 cells at 100 m in UTM 42N (602 km²). It runs from that western edge to the window's eastern edge and covers the window's full north–south extent.
- **Upstream of the Swat:** the Swat junction (~71.71 E) lies outside the window, so the release is the only major inflow.

## Prepared inputs

The inputs are kept in their own catalog, `workspace/sites/warsak/assets.json`. Nowshera's `workspace/assets.json`, its hashes and its accepted bindings are unchanged.

| Input | Source | Note |
| --- | --- | --- |
| Terrain | FABDEM v1.2 tiles N33E071 + N34E071, clipped to 71.10–71.62 E, 33.94–34.38 N | Same tiles as the viewer terrain |
| Land cover | ESA WorldCover 2021 tile N33E069 | Nearest-neighbour ~30 m clip |
| Rivers | HydroRIVERS upper-Kabul extract | Same file as Nowshera, which already spans Warsak |
| Catchment | HydroBASINS level-8 candidate union upstream of the Warsak gauge position | 69,187 km²; review required |
| Soil | SoilGrids 2.0, 0–5 cm | Unused by the gauge-driven model; required by preflight |

## Channel and boundaries (no inflow used)

- **Mapped-water corridor:** one connected west-to-east stretch of WorldCover water (≥ 25% water fraction): **797 cells**, **17.1 km** along its centerline. Widths range from 164 to 1,066 m.
- **Water-surface profile:** monotone FABDEM water surface falling from 340.9 m to 313.4 m, a slope of **0.00166**.
- **Upstream boundary:** the 400 m of corridor cells on the west edge at the HydroRIVERS entry (`QVAR`, divided by that width).
- **Downstream boundary:** free outflow at the mapped-water slope. The other edges are closed.
- **Bed lowering:** Manning normal depth at the first release value, as for Nowshera. This step is applied only when the release record exists.

## Numerical smoke test

`python -m server.warsak smoke 1132.7` ran the real geometry with a constant **test** flow of 1,132.7 m³/s. That flow is Warsak's FFD "low flood" limit of 0.4 lakh cusecs, not a 2022 value. The run covered the 72-hour warm-up plus six hours in a scratch folder under `workspace/sites/warsak/smoke/`. It was never bound or published.

| Check | Result | Limit |
| --- | ---: | ---: |
| Outflow vs inflow, last 6 warm-up hours | 0.0003% | 2% |
| East-edge cross-section vs inflow | 0.0016% | 2% |
| Storage range | 0.00009% | 1% |
| Centerline wet / inlet-to-outlet connection | 100% / yes | ≥ 95% / yes |
| Volume error | 0.0002% | 0.1% |

At that test flow the maximum depth was 4.9 m and 9.2 km² was wet. These checks show the model initialises correctly. They do not validate real-world flooding.

## When the release record arrives

```powershell
.\.venv\Scripts\python.exe -m server.cli register inflow warsak-release.csv --site warsak --source "<agency and document>" --license "<terms>" --product "Warsak Dam release 2022"
.\.venv\Scripts\python.exe -m server.warsak build
```

The CSV needs columns `time` (ISO 8601 with timezone), `station_id` (`warsak`), `discharge_m3s`, `source` and `value_type` (`observed` or `modeled`). It must cover 2022-08-20T01:00Z to 2022-09-05T01:00Z, with ordinates at most 3 hours apart.

`build` then does four things:
1. conditions the channel at the first release value;
2. writes and binds the LISFLOOD-FP project;
3. checks preflight;
4. adds **Runnable · Warsak below-dam screening** to the app's case runner.

Running the case publishes it through the shared LISFLOOD checks, with the modelled outflow at the east edge as its hydrograph. There is no downstream gauge inside the window, so there are no discharge skill scores. The HEC-RAS case is built after the LISFLOOD case runs.

`python -m server.warsak status` (or `GET /api/sites/warsak`) lists what is ready and what is still missing.

## Exposure layers

Population (WorldPop 2022) and OpenStreetMap facilities now cover both sites: 71.10–72.24 E, 33.79–34.38 N. That is 11.4 million residents and 420 facilities. Stream names are looked up around both reaches. Recomputed Nowshera exposure numbers are unchanged.
