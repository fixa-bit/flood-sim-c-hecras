import type { Result, ResultSummary } from "../lib/api";
import type { Field } from "../lib/legend";
import { FIELD_TITLES, LEGEND_COLORS, legendLabels } from "../lib/legend";
import { PLAYBACK_SPEEDS } from "../hooks/usePlayback";
import type { PlaybackSpeed } from "../hooks/usePlayback";

type Frame = Result["frames"][number];
export type ComparisonTiming = "exact" | "nearby";

const utc = (time?: string) =>
  time
    ? `${new Date(time).toISOString().slice(0, 16).replace("T", " ")} UTC`
    : "No model output";

export function ResultPicker(props: {
  results: ResultSummary[];
  result?: ResultSummary;
  compareId: string;
  timing: ComparisonTiming;
  field: Field;
  onResult: (id: string) => void;
  onCompare: (id: string) => void;
  onTiming: (timing: ComparisonTiming) => void;
  onField: (field: Field) => void;
}) {
  const { results, result } = props;
  return (
    <div className="result-picker">
      <label>
        Result A
        <select
          aria-label="Result A"
          value={result?.id ?? ""}
          onChange={(e) => props.onResult(e.target.value)}
        >
          <option value="">Select published output</option>
          {results.map((r) => (
            <option key={r.id} value={r.id}>
              {r.scenario.name} · {r.engine}
            </option>
          ))}
        </select>
      </label>
      <label>
        Compare B
        <select
          aria-label="Result B"
          value={props.compareId}
          onChange={(e) => props.onCompare(e.target.value)}
        >
          <option value="">No comparison</option>
          {results
            .filter(
              (r) =>
                r.id !== result?.id &&
                (!result ||
                  r.scenario.outlet.station_id ===
                    result.scenario.outlet.station_id),
            )
            .map((r) => (
              <option key={r.id} value={r.id}>
                {r.scenario.name} · {r.engine}
              </option>
            ))}
        </select>
      </label>
      <label>
        Compare times
        <select
          aria-label="Comparison timing"
          value={props.timing}
          onChange={(e) => props.onTiming(e.target.value as ComparisonTiming)}
        >
          <option value="exact">Exact timestamps</option>
          <option value="nearby">Nearest frame within 60 seconds</option>
        </select>
      </label>
      <label>
        Field
        <select
          aria-label="Model field"
          value={props.field}
          onChange={(e) => props.onField(e.target.value as Field)}
        >
          <option value="depth">Depth (m)</option>
          <option value="wse">Water surface (m)</option>
          <option value="velocity">Speed (m/s)</option>
        </select>
      </label>
    </div>
  );
}

export function ResultDetails(props: {
  result: Result;
  frame?: Frame;
  field: Field;
  comparing?: Result;
  comparisonFrame?: Frame;
  timing: ComparisonTiming;
  showObserved: boolean;
  onShowObserved: (show: boolean) => void;
}) {
  const { result, frame, comparing, comparisonFrame } = props;
  const offset =
    comparisonFrame && frame
      ? (Date.parse(comparisonFrame.time) - Date.parse(frame.time)) / 1000
      : undefined;
  return (
    <div className="result-details">
      <span>{result.validation_status}</span>
      {frame && !frame.fields[props.field] && (
        <strong>This field was not exported for this frame.</strong>
      )}
      {comparing && !comparisonFrame && (
        <strong>
          {props.timing === "exact"
            ? "B has no frame at this model time."
            : "B has no frame within 60 seconds of this model time."}
        </strong>
      )}
      {comparing && comparisonFrame && frame && offset !== undefined && (
        <div className="comparison-times" role="status">
          <span>
            A · {result.engine}: {new Date(frame.time).toISOString()}
          </span>
          <span>
            B · {comparing.engine}:{" "}
            {new Date(comparisonFrame.time).toISOString()}
          </span>
          <span>
            B time offset: {offset >= 0 ? "+" : ""}
            {offset.toFixed(3)} s. Original frames; no temporal interpolation.
          </span>
        </div>
      )}
      {comparing && comparing.terrain_sha256 !== result.terrain_sha256 && (
        <strong>
          A/B use different terrain hashes; interpret differences accordingly.
        </strong>
      )}
      <label>
        <input
          type="checkbox"
          checked={props.showObserved}
          disabled={!result.extent_validation?.overlay}
          onChange={(e) => props.onShowObserved(e.target.checked)}
        />{" "}
        Observed extent at matched acquisition time
      </label>
    </div>
  );
}

export function PlaybackBar(props: {
  enabled: boolean;
  frameCount: number;
  frameIndex: number;
  time?: string;
  playing: boolean;
  speed: PlaybackSpeed;
  onToggle: () => void;
  onSeek: (index: number) => void;
  onSpeed: (speed: PlaybackSpeed) => void;
}) {
  const { enabled, frameCount, frameIndex } = props;
  return (
    <div className="timebar">
      <button
        className="play-button"
        aria-label={props.playing ? "Pause playback" : "Play model output"}
        disabled={!enabled || !frameCount}
        onClick={props.onToggle}
      >
        {props.playing ? "Ⅱ" : "▶"}
      </button>
      <div className="time-label">
        <span>MODEL TIME</span>
        <strong>{enabled ? utc(props.time) : "Awaiting hydraulic output"}</strong>
      </div>
      <input
        aria-label="Model timestep"
        type="range"
        min="0"
        max={Math.max(0, frameCount - 1)}
        value={frameIndex}
        disabled={!enabled}
        onChange={(e) => props.onSeek(+e.target.value)}
      />
      <span className="frame-count">
        {enabled ? `${frameIndex + 1} / ${frameCount}` : "— / —"}
      </span>
      <select
        className="speed-select"
        aria-label="Playback speed"
        title="Space plays or pauses; ← → step one frame, Shift+← → step ten"
        value={props.speed}
        disabled={!enabled}
        onChange={(e) => props.onSpeed(+e.target.value as PlaybackSpeed)}
      >
        {PLAYBACK_SPEEDS.map((value) => (
          <option key={value} value={value}>
            {value}×
          </option>
        ))}
      </select>
    </div>
  );
}

export function MapLegend({ field, result }: { field: Field; result?: Result }) {
  return (
    <div className="map-legend">
      <span>{FIELD_TITLES[field]}</span>
      {legendLabels(field, result?.legend).map((label, i) => (
        <span key={label}>
          <i style={{ background: LEGEND_COLORS[i] }} />
          {label}
        </span>
      ))}
      <small>
        {result
          ? "Dry / nodata transparent"
          : "Legend activates with model rasters"}
      </small>
    </div>
  );
}
