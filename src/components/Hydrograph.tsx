import type { Hydrograph as Graph } from "../lib/api";

export function Hydrograph({ graph, time }: { graph?: Graph; time?: string }) {
  if (!graph?.samples.length)
    return (
      <div className="chart-empty">
        <span className="empty-wave">∿</span>
        <strong>Hydrograph awaits model output</strong>
        <p>
          Observed and modeled discharge will share the model clock.
          <br />
          Import time-aligned gauge records to measure skill.
        </p>
      </div>
    );
  const samples = graph.samples;
  const start = Date.parse(samples[0].time),
    end = Date.parse(samples.at(-1)!.time);
  const max =
    Math.max(
      1,
      ...samples.flatMap((s) => [
        s.observed_m3s ?? 0,
        s.simulated_m3s ?? 0,
        s.upper_m3s ?? 0,
      ]),
    ) * 1.1;
  const x = (t: string) =>
    55 + ((Date.parse(t) - start) / (end - start || 1)) * 680;
  const y = (v: number) => 155 - (v / max) * 130;
  const path = (key: "observed_m3s" | "simulated_m3s") => {
    let move = true;
    return samples
      .map((s) => {
        if (s[key] == null) {
          move = true;
          return "";
        }
        const command = `${move ? "M" : "L"}${x(s.time)},${y(s[key]!)}`;
        move = false;
        return command;
      })
      .join(" ");
  };
  const band = samples.filter(
    (s) => s.lower_m3s !== undefined && s.upper_m3s !== undefined,
  );
  return (
    <div className="chart">
      <svg
        viewBox="0 0 760 195"
        role="img"
        aria-label={`Observed and modeled discharge at ${graph.station_id}`}
      >
        {[0, 0.5, 1].map((v) => (
          <g key={v}>
            <line
              x1="55"
              y1={y(v * max)}
              x2="735"
              y2={y(v * max)}
              stroke="#253c43"
            />
            <text x="46" y={y(v * max) + 4} textAnchor="end">
              {Math.round(v * max).toLocaleString()}
            </text>
          </g>
        ))}
        {band.length > 1 && (
          <polygon
            fill="#69d7bd22"
            points={[
              ...band.map((s) => `${x(s.time)},${y(s.upper_m3s!)}`),
              ...band
                .toReversed()
                .map((s) => `${x(s.time)},${y(s.lower_m3s!)}`),
            ].join(" ")}
          />
        )}
        <path
          d={path("observed_m3s")}
          fill="none"
          stroke="#8fabb6"
          strokeWidth="2"
          strokeDasharray="5 4"
        />
        <path
          d={path("simulated_m3s")}
          fill="none"
          stroke="#6de4c1"
          strokeWidth="2.5"
        />
        {samples
          .filter((sample) => sample.observed_m3s != null)
          .map((sample) => (
            <circle
              key={sample.time}
              cx={x(sample.time)}
              cy={y(sample.observed_m3s!)}
              r="3.2"
              fill="#c0d4db"
            />
          ))}
        {time && (
          <line x1={x(time)} y1="12" x2={x(time)} y2="155" stroke="#ecb96c" />
        )}
        <text x="55" y="179">
          {samples[0].time.slice(0, 10)}
        </text>
        <text x="735" y="179" textAnchor="end">
          {samples.at(-1)!.time.slice(0, 10)}
        </text>
        <text x="55" y="10">
          m³/s
        </text>
      </svg>
      <div className="chart-legend">
        <span>━ Modeled</span>
        <span>┄ Observed</span>
        {band.length > 1 && <span>▧ Supplied uncertainty interval</span>}
      </div>
    </div>
  );
}
