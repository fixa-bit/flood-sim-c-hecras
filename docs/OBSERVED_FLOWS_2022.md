# Observed 2022 river flows — 4 November 2026

`workspace/observations/observed-daily-2022.csv` is one table of measured 2022 discharges at 25 stations. It combines two public sources. Its review file, `observed-daily-2022-review.json`, records every source document and hash, every line left out and why, and the cross-checks.

It is for display and for checking models. It is **not model forcing**: every value is a once-a-day reading.

## Sources

| Source | What it gives | Cadence | 2022 coverage |
| --- | --- | --- | --- |
| [FFC daily flood situation reports](https://ffc.gov.pk/), Annexure-I "River Flow Situation" | Today's inflow (column 7) and outflow (column 8) at 25 structures and gauges | One reading at 06:00 PKT | 68 reports, 1 July – 11 September. Not published: 5 and 23 July, 6 August, 9–10 September, and all of June and 12 September – 15 October |
| [WAPDA river-flow workbook](https://wapda.gov.pk/river-flow/), `GHRAPH` sheet | Tarbela inflow and outflow, Nowshera (Kabul) inflow, Mangla inflow and outflow, Marala (Chenab) inflow | Daily. WAPDA's press releases describe Tarbela, Nowshera and Mangla as 24-hour means and Marala as the 06:00 reading | All 365 days of 2022; no zero or missing values |

## Rules

- **Measured or reported values only.** Nothing is interpolated, filled in or adjusted.
- **FFC rows are read against the report's own numbered column header (1–10).** A row is kept only when its numbers map to distinct printed columns in order. "NIL" is kept as 0, with `reported_as = NIL`.
- **Lines that can't be read unambiguously are left out and listed in the review.** In 2022 that is 41 lines:
  - **29 Mangla rows** (July – early August). The text layer has a stray "0" between the columns, so the values can't be placed with certainty. WAPDA's daily Mangla values cover these days.
  - **12 Nowshera outflows** (10–21 August). The report prints them with a period instead of a comma ("42.000"). They are probably 42,000 and so on, but correcting the source is left to a reviewer.
- **Stray spaces around a thousands comma are read as one number**, for example "292 ,000" = 292,000. The digits and comma are all printed; the project's earlier FFC extractor reads them the same way.
- **The two sources measure different things**: a 06:00 reading and a daily value. Both are kept, side by side, never merged or reconciled.

## Checks

- **Against the project's earlier reviewed FFC transcriptions** (Warsak, Charsadda Road and Nowshera, 20 Aug – 5 Sep): 49 values compared, **0 differences**.
- **Against the printed PDF tables:** all 41 values of 28 July, read from a rendered page image, and 31 values of 27 August. All match after the comma-spacing fix.
- **FFC 06:00 vs WAPDA daily**, median ratio on common days:

  | Series | Median ratio | Range |
  | --- | ---: | --- |
  | Marala inflow | 1.00 | 0.99–1.26 |
  | Tarbela inflow | 1.00 | 0.89–1.17 |
  | Tarbela outflow | 0.99 | 0.59–1.38 |
  | Mangla inflow | 0.99 | 0.79–1.88 |
  | Mangla outflow | 0.93 | 0.44–1.40 |

  The wide ranges are on days when flows change quickly within the day.

## Coverage and 06:00 peaks (cusecs)

| Station | River | FFC inflow | FFC outflow | WAPDA inflow | WAPDA outflow |
| --- | --- | --- | --- | --- | --- |
| Tarbela | Indus | 68 d, 395,000 (27 Aug) | 68 d, 332,000 (27 Aug) | 365 d, 353,800 (27 Aug) | 365 d, 374,900 (27 Aug) |
| Kalabagh | Indus | 68 d, 427,000 (28 Aug) | 68 d, 423,000 (28 Aug) | — | — |
| Chashma | Indus | 68 d, 525,000 (29 Aug) | 68 d, 519,000 (29 Aug) | — | — |
| Taunsa | Indus | 68 d, 622,000 (30 Aug) | 68 d, 622,000 (30 Aug) | — | — |
| Guddu | Indus | 68 d, 558,000 (2 Sep) | 68 d, 558,000 (2 Sep) | — | — |
| Sukkur | Indus | 68 d, 580,000 (25 Aug) | 68 d, 580,000 (25 Aug) | — | — |
| Kotri | Indus | 68 d, 626,000 (11 Sep) | 67 d, 600,000 (11 Sep) | — | — |
| Warsak | Kabul | — | 67 d, 130,000 (27 Aug) | — | — |
| Nowshera | Kabul | — | 56 d, 307,000 (28 Aug) | 365 d, 318,500 (29 Aug) | — |
| Chakdara Bridge | Swat | — | 68 d, 83,000 (27 Aug) | — | — |
| Munda Headworks | Swat | — | 68 d, 120,000 (28 Aug) | — | — |
| Charsadda Road | Swat | — | 68 d, 140,000 (27 Aug) | — | — |
| Mangla | Jhelum | 39 d, 75,000 (27 Aug) | 39 d, 37,000 (1 Jul) | 365 d, 73,200 (29 Jul) | 365 d, 60,000 (23 Feb) |
| Rasul | Jhelum | 68 d, 34,000 (1 Jul) | 68 d, 12,000 (1 Jul) | — | — |
| Marala | Chenab | 68 d, 156,000 (16 Aug) | 68 d, 144,000 (16 Aug) | 365 d, 155,900 (16 Aug) | — |
| Khanki | Chenab | 67 d, 217,000 (12 Aug) | 68 d, 211,000 (12 Aug) | — | — |
| Qadirabad | Chenab | 68 d, 210,000 (29 Jul) | 68 d, 191,000 (29 Jul) | — | — |
| Trimmu | Chenab | 68 d, 130,000 (19 Aug) | 68 d, 122,000 (19 Aug) | — | — |
| Panjnad | Chenab | 68 d, 122,000 (3 Aug) | 68 d, 113,000 (3 Aug) | — | — |
| Jassar | Ravi | — | 68 d, 48,000 (17 Aug) | — | — |
| Shahdara | Ravi | — | 68 d, 31,000 (2 Aug) | — | — |
| Balloki | Ravi | 68 d, 52,000 (3 Aug) | 68 d, 35,000 (3 Aug) | — | — |
| Sidhnai | Ravi | 68 d, 27,000 (13 Aug) | 68 d, 23,000 (29 Jul) | — | — |
| Suleimanki | Sutlej | 68 d, 25,000 (20 Jul) | 68 d, 18,000 (17 Jul) | — | — |
| Islam | Sutlej | 67 d, 13,000 (24 Jul) | 65 d, 13,000 (24 Jul) | — | — |

These are the highest **06:00 readings**, not event peaks. Once-a-day readings miss short peaks. For example, NDMA reports Marala's 2022 maximum as 225,836 cusecs at 18:00 on 28 July, while the highest 06:00 reading of the season is 156,000 cusecs, on 16 August.

## Not covered

- **Kohala** (Jhelum), **Akhnur** and **Jammu Tawi** (Chenab, India-administered), **Attock**, **Chiniot Bridge** and **G.S. Wala** are not in either source. Kohala would need a request to WAPDA's Surface Water Hydrology office. Akhnur would need a request to India's Central Water Commission.
- **No sub-daily 2022 record is public** for any of these stations.

## In the app

Select a station, then open the **Simulation** tab. **Observed 2022 flows** plots each available series for 1 July – 30 September:
- FFC inflow and outflow as solid lines;
- WAPDA daily values as dashed lines.

Points are joined only between consecutive days, so missing days stay visible gaps. During playback, a marker shows the model time. API: `GET /api/observations` (summary) and `GET /api/observations/{station_id}` (rows).

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m pip install -r server\requirements-data.txt   # adds xlrd for the .xls workbook
.\.venv\Scripts\python.exe -m server.observations acquire   # WAPDA workbook + FFC reports, hashed into an index
.\.venv\Scripts\python.exe -m server.observations build     # table + review
```

Downloads are kept under `workspace/downloads/observations-2022/`. FFC reports already in the project are reused rather than downloaded again.
