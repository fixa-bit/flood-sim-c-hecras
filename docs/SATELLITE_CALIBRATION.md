# Warsak: steady snapshots checked against Sentinel-1 — 5 November 2026

The first simulation in the project scored against an **observed flood extent**. It combines:
- **an observed discharge**, which drives the model;
- **a satellite flood map from almost the same moment**, which calibrates and checks it;
- **terrain, roughness and the mapped channel**, as for the other cases.

## Why a snapshot, not a 2022 replay

The public 2022 Warsak record is one FFC reading a day, and the project owner declined interpolating it into an hourly inflow. Instead, each run holds **one observed FFC 06:00 release constant until the river is steady**. It then compares the steady flood with a Sentinel-1 water map:

| Pair | FFC Warsak release | Sentinel-1 acquisition | Flow at the time |
| --- | ---: | --- | --- |
| Calibration | 59,000 cusecs (1,671 m³/s), 25 Aug 06:00 PKT | 25 Aug 01:16 UTC = **06:16 PKT**, 16 minutes later | Rising: 46,000 the day before, 87,000 the day after |
| Validation | 26,000 cusecs (736 m³/s), 5 Sep 06:00 PKT | 5 Sep 13:13 UTC = 18:13 PKT | Steady: 26,000 on 4 and 5 Sep, 24,000 on 6 Sep |

The frames show the steady state at that release, labelled so the last one is the satellite time. They are not event timing.

## Satellite water masks (`server/satellite.py`)

**Data:** Sentinel-1 RTC gamma0, VV and VH (Microsoft Planetary Computer `sentinel-1-rtc`, anonymous token). Only the model window is read, at 10 m, in the model's own UTM 42N grid. It contains modified Copernicus Sentinel data 2022, under the [Sentinel data legal notice](https://sentinel.esa.int/documents/247904/690755/Sentinel_Data_Legal_Notice).

**Thresholds.** Values are converted to dB and median-filtered (3×3). Water is where **both** bands fall below their minimum-error (Bayes) thresholds. The thresholds come from two classes the radar doesn't define:
- **water:** pixels WorldCover maps as water;
- **land:** usable pixels more than 300 m from any mapped water.

Otsu was tried first and rejected. Water is under 1% of the window, and the sediment-laden, turbulent Kabul has a wide backscatter spread, so no histogram has a clean valley.

| Scene | VV threshold | VH threshold | Mapped river detected as water | Distant land wrongly called water |
| --- | ---: | ---: | ---: | ---: |
| 25 Aug | −11.32 dB | −17.43 dB | 79% | 2.6% |
| 5 Sep | −11.35 dB | −17.16 dB | 58% (lower flow: narrower river) | 4.0% |

**Excluded, never called dry:**
- slope > 10° (radar shadow and layover);
- WorldCover built-up (SAR misses flooding between buildings);
- more than 15 m above the nearest mapped water.

**Aggregation:** to the 100 m model grid. A cell is observable when at least 50% of its pixels are usable, and wet when at least 50% of those are water. Review PNGs: `workspace/sites/warsak/satellite/<date>/review.png`.

**Scoring zone.** Both scenes show water far out on the Peshawar plain, probably ponded rain or irrigated fields, which a river-forced model cannot produce. Scores therefore use the **Kabul floodplain zone**: cells at most 10 m above the river's mapped water surface and within 3 km of its channel. **Floodplain CSI** also excludes the always-wet mapped channel, so the channel cannot inflate the score. Whole-window scores are kept in the run records.

## Model and calibration (`server/warsak_snapshot.py`)

- **Model:** LISFLOOD-FP ACC on the prepared Warsak geometry (156 × 386 cells at 100 m, from 71.40 E about 4 km below the dam).
- **Bed:** conditioned once at a fixed reference flow, the median 2022 FFC Warsak release (34,000 cusecs, 963 m³/s, 67 readings), so every run shares the same terrain.
- **Steady state:** 72 h warm-up at the release plus 24 steady hours.
- **Speed:** cell speed from the engine's face velocities (`voutput`).
- **Rain and infiltration are off:** rain on the 602 km² window is under 1% of river volume. Soils matter for catchment runoff instead (approved for the Kalpani in the later Nowshera run).
- **Numerical checks:** every run converged, with outflow matching inflow to 0.02% and a volume error of about 4 × 10⁻⁶. Each run takes about 14 s.

**Calibration sweep** against the 25 Aug mask: floodplain roughness multiplier × channel Manning n, 20 runs. Chosen by floodplain CSI: **multiplier 0.85, channel n 0.035**, essentially the starting priors.

| Floodplain × | n = 0.030 | 0.035 | 0.040 | 0.045 |
| --- | ---: | ---: | ---: | ---: |
| 0.70 | 0.171 | 0.201 | 0.185 | 0.193 |
| 0.85 | 0.171 | **0.205** | 0.182 | 0.192 |
| 1.00 | 0.173 | 0.201 | 0.188 | 0.188 |
| 1.15 | 0.173 | 0.201 | 0.185 | 0.185 |
| 1.30 | 0.171 | 0.201 | 0.185 | 0.183 |

(Floodplain CSI; zone CSI ranges from 0.52 to 0.62.)

## Results

| Run | Zone CSI | POD | FAR | Floodplain CSI | Wet area |
| --- | ---: | ---: | ---: | ---: | ---: |
| **25 Aug, 59,000 cusecs (calibration)** | **0.61** | 0.87 | 0.33 | 0.21 | 10.6 km² |
| 24 Aug release, 46,000 (bracket) | 0.62 | 0.84 | 0.30 | 0.17 | 9.6 km² |
| 26 Aug release, 87,000 (bracket) | 0.50 | 0.93 | 0.48 | 0.17 | 14.4 km² |
| **5 Sep, 26,000 cusecs (independent validation)** | **0.46** | 0.78 | 0.47 | 0.03 | 8.5 km² |

Exposure at the steady state (WorldPop 2022, outside the mapped river channel):

| Run | ≥ 0.3 m water | ≥ 1 m water | Dangerous water (HR ≥ 0.75) |
| --- | ---: | ---: | ---: |
| 25 Aug | 124 residents | 60 | 95 |
| 5 Sep | 36 residents | 0 | 36 |

HR is the Defra/EA FD2321 hazard rating, d(v + 0.5) + DF.

## What this shows

- **The model catches most observed water in the river corridor** at the calibration flow (POD 0.87). It meets the project's CSI target of 0.5 there, and its result barely changes with the release: 0.62 → 0.61 → 0.50 across 46,000–87,000 cusecs.
- **Roughness is not what limits accuracy.** Across the whole sweep, floodplain CSI moves only between 0.17 and 0.21.
- **The limit is the estimated channel bed.** It is a flat, rectangular channel lowered across the full width of the braided river as WorldCover mapped it in 2021. At the low 5 Sep flow the model therefore wets almost the whole mapped corridor: about 349 false alarms inside it. The satellite saw a narrower channel, only 58% of the mapped river.
- **What would improve it:** surveyed cross-sections, or a channel shaped from the satellite's own low-flow water. Changing roughness further would not.

These are exploratory, uncalibrated-beyond-roughness results. The 5 Sep scores are independent of the calibration; the 25 Aug scores are not.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m server.satellite 2022-08-25 2022-09-05     # water masks on the model grid
.\.venv\Scripts\python.exe -m server.warsak_snapshot sweep               # 20 calibration runs, brackets, validation
.\.venv\Scripts\python.exe -m server.warsak_snapshot publish             # publish the two runs with their observed extents
```

**Outputs:**
- masks and records: `workspace/sites/warsak/satellite/`;
- runs and `calibration.json`: `workspace/sites/warsak/snapshots/`;
- results: `warsak-snapshot-20220825-59000-…` and `warsak-snapshot-20220905-26000-…`.

**In the app:** select **Warsak**, then **Model results**. The run details show the satellite score. At the last frame, **Observed extent at matched acquisition time** overlays the satellite map, and **Field → Speed** shows velocity.
