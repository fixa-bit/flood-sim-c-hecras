import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";

type Row = {
  date: string;
  time_utc: string;
  quantity: "inflow" | "outflow";
  discharge_m3s: string;
  discharge_cusecs: string;
  reported_as: string;
  source: string;
};
type Observed = { station_id: string; rows: Row[]; rules: string[] };

const WIDTH = 420;
const HEIGHT = 190;
const LEFT = 52;
const RIGHT = 14;
const TOP = 14;
const BOTTOM = 158;
// The 2022 monsoon window shown; WAPDA's year-round values are clipped to it.
const FIRST = Date.parse("2022-07-01T00:00:00Z");
const LAST = Date.parse("2022-09-30T23:59:59Z");
const DAY = 86_400_000;
const SERIES = [
  {
    key: "FFC inflow",
    label: "FFC inflow · 06:00",
    color: "#7cc4ff",
    dash: "",
  },
  {
    key: "FFC outflow",
    label: "FFC outflow · 06:00",
    color: "#6de4c1",
    dash: "",
  },
  {
    key: "WAPDA inflow",
    label: "WAPDA inflow · daily",
    color: "#e0b86b",
    dash: "4 3",
  },
  {
    key: "WAPDA outflow",
    label: "WAPDA outflow · daily",
    color: "#c99ae6",
    dash: "4 3",
  },
] as const;

/**
 * Observed 2022 flows for one station: measured values only. Points are
 * joined only between consecutive days, so missing days stay visible gaps.
 */
export function ObservedFlows({
  stationId,
  stationName,
  time,
}: {
  stationId?: string | null;
  stationName?: string;
  time?: string;
}) {
  const [cache, setCache] = useState<Record<string, Observed | null>>({});
  const known = stationId ? cache[stationId] : undefined;
  useEffect(() => {
    if (!stationId || known !== undefined) return;
    const controller = new AbortController();
    void api<Observed>(
      `observations/${encodeURIComponent(stationId)}`,
      undefined,
      {
        signal: controller.signal,
      },
    )
      .then((value) =>
        setCache((current) => ({ ...current, [stationId]: value })),
      )
      .catch(() => {
        if (!controller.signal.aborted)
          setCache((current) => ({ ...current, [stationId]: null }));
      });
    return () => controller.abort();
  }, [stationId, known]);

  const series = useMemo(() => {
    const groups = new Map<string, { t: number; q: number }[]>();
    for (const row of known?.rows ?? []) {
      const t = Date.parse(row.time_utc || `${row.date}T12:00:00Z`);
      if (t < FIRST || t > LAST) continue;
      const key = `${row.source.startsWith("FFC") ? "FFC" : "WAPDA"} ${row.quantity}`;
      const points = groups.get(key) ?? [];
      points.push({ t, q: Number(row.discharge_m3s) });
      groups.set(key, points);
    }
    for (const points of groups.values()) points.sort((a, b) => a.t - b.t);
    return groups;
  }, [known]);

  if (!stationId) return null;
  const all = [...series.values()].flat();
  const max = Math.max(1, ...all.map((p) => p.q)) * 1.08;
  const x = (t: number) =>
    LEFT + ((t - FIRST) / (LAST - FIRST)) * (WIDTH - LEFT - RIGHT);
  const y = (q: number) => BOTTOM - (q / max) * (BOTTOM - TOP);
  const path = (points: { t: number; q: number }[]) =>
    points
      .map((p, i) => {
        const joined = i > 0 && p.t - points[i - 1].t <= 1.5 * DAY;
        return `${joined ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.q).toFixed(1)}`;
      })
      .join(" ");
  const marker = time ? Date.parse(time) : NaN;
  const shown = SERIES.filter((item) => series.get(item.key)?.length);

  return (
    <section className="observed-section" aria-label="Observed 2022 flows">
      <div className="section-title">
        <h2>Observed 2022 flows</h2>
        <span>MEASURED VALUES ONLY · GAPS LEFT BLANK</span>
      </div>
      {known === undefined ? (
        <p className="footnote">Loading observed flows…</p>
      ) : !shown.length ? (
        <p className="footnote">
          No observed 2022 flows in the project for{" "}
          {stationName ?? "this station"}. FFC and WAPDA publish none here; see
          the observations review for sources.
        </p>
      ) : (
        <>
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            role="img"
            aria-label={`Observed 2022 discharge at ${stationName ?? stationId}`}
          >
            {[0, 0.5, 1].map((v) => (
              <g key={v}>
                <line
                  x1={LEFT}
                  y1={y(v * max)}
                  x2={WIDTH - RIGHT}
                  y2={y(v * max)}
                  stroke="#253c43"
                />
                <text x={LEFT - 6} y={y(v * max) + 3} textAnchor="end">
                  {Math.round(v * max).toLocaleString("en-US")}
                </text>
              </g>
            ))}
            {["2022-07-01", "2022-08-01", "2022-09-01"].map((day) => (
              <text
                key={day}
                x={x(Date.parse(`${day}T00:00:00Z`))}
                y={BOTTOM + 16}
              >
                {new Date(`${day}T00:00:00Z`).toLocaleString("en-US", {
                  month: "short",
                  timeZone: "UTC",
                })}
              </text>
            ))}
            <text x={LEFT} y={TOP - 4}>
              m³/s
            </text>
            {shown.map((item) => (
              <g key={item.key}>
                <path
                  d={path(series.get(item.key)!)}
                  fill="none"
                  stroke={item.color}
                  strokeWidth="1.6"
                  strokeDasharray={item.dash}
                />
                {series.get(item.key)!.map((p) => (
                  <circle
                    key={p.t}
                    cx={x(p.t)}
                    cy={y(p.q)}
                    r="1.4"
                    fill={item.color}
                  />
                ))}
              </g>
            ))}
            {marker >= FIRST && marker <= LAST && (
              <line
                x1={x(marker)}
                y1={TOP}
                x2={x(marker)}
                y2={BOTTOM}
                stroke="#ecb96c"
              />
            )}
          </svg>
          <div className="chart-legend">
            {shown.map((item) => (
              <span key={item.key} style={{ color: item.color }}>
                {item.dash ? "┄" : "━"} {item.label}
              </span>
            ))}
          </div>
          <p className="footnote">
            FFC: Annexure-I reading at 06:00 PKT. WAPDA: daily values (24-hour
            means at Tarbela, Nowshera and Mangla). Once-a-day values, so not
            model forcing.
          </p>
        </>
      )}
    </section>
  );
}
