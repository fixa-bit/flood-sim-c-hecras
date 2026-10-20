import { useEffect, useState } from "react";
import { api, download } from "../lib/api";
import type { Hydrograph as Graph } from "../lib/api";
import { Hydrograph } from "./Hydrograph";

type Study = {
  boundaries: { reviewed_rows: number; hourly_rows: number } | null;
  moisture: { product: string; accepted_for_infiltration: boolean } | null;
  rainfall: {
    multiplier?: number;
    heldout_rmse_improved?: boolean;
    reason?: string;
  } | null;
  routing: {
    candidates: number;
    validation_targets_met: boolean;
    scores: Record<
      string,
      {
        samples: number;
        nse: number | null;
        kge: number | null;
        rmse_m3s: number | null;
      }
    >;
  } | null;
  hydrograph: Graph | null;
};

export function StudyPanel() {
  const [study, setStudy] = useState<Study>();
  useEffect(() => {
    void api<Study>("study")
      .then(setStudy)
      .catch(() => {});
  }, []);
  if (!study?.routing) return null;
  const score = study.routing.scores.validation;
  const fmt = (value: number | null | undefined) =>
    value == null ? "—" : value.toFixed(3);
  return (
    <section className="study-panel">
      <div className="section-title">
        <h2>Upstream routing study · 2022</h2>
        <button
          className="small-button"
          onClick={() => download("nowshera-public-study.json", study)}
        >
          Export study
        </button>
      </div>
      <p>
        Warsak + Swat at Charsadda Road → HEC-HMS → Nowshera. Thirty routing
        candidates were tested against early observations; later observations
        were withheld from fitting.
      </p>
      <div className="study-metrics">
        <div>
          <strong>{fmt(score.nse)}</strong>
          <span>Validation NSE · target ≥ 0.65</span>
        </div>
        <div>
          <strong>{fmt(score.kge)}</strong>
          <span>Validation KGE · target ≥ 0.60</span>
        </div>
        <div>
          <strong>{score.samples}</strong>
          <span>Withheld daily observations</span>
        </div>
      </div>
      <p className="inline-note">
        {study.routing.validation_targets_met
          ? "Routing targets met on the within-event test."
          : "Routing validation targets are not all met."}{" "}
        Hydraulic calibration and independent flood-extent validation remain
        open.
      </p>
      <Hydrograph graph={study.hydrograph ?? undefined} />
      <p className="muted">
        Hourly boundary values interpolate daily reports. Other tributary
        contributions are estimated as a constant fitted to training data. This
        is a hydrologic routing experiment.
      </p>
      <div className="study-input-notes">
        <p>
          <strong>Initial moisture:</strong>{" "}
          {study.moisture?.product ?? "Not acquired"}. Provider quality flags
          and root-zone interpretation still need review.
        </p>
        <p>
          <strong>Rainfall correction:</strong>{" "}
          {study.rainfall?.multiplier
            ? `${study.rainfall.multiplier.toFixed(3)}× candidate from NOAA station records; ${study.rainfall.heldout_rmse_improved ? "held-out RMSE improved" : "held-out RMSE did not improve"}.`
            : (study.rainfall?.reason ?? "Pending")}
        </p>
        <p>
          Gauged routing consumes measured discharge, so rainfall and soil
          moisture are unused in this experiment.
        </p>
      </div>
    </section>
  );
}
