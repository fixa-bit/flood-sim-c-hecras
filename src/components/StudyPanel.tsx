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
  geometry_roughness?: {
    bed_is_surveyed: boolean;
    classes: { name: string; n: number; low: number; high: number }[];
    source_reference: string;
    available_cases: { label: string; id: string; result_id: string }[];
  } | null;
  inflow_improvement?: {
    additional_reviewed_observations: number;
    promoted_to_hydraulic_models: boolean;
    coverage: Record<string, { maximum_gap_hours: number }>;
    lateral_inflows: { state: string };
    scores?: Record<
      string,
      {
        baseline: { kge: number | null };
        candidate: { kge: number | null };
      }
    >;
  } | null;
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
        {study.geometry_roughness && (
          <section
            aria-label="Geometry and roughness"
            className="geometry-roughness"
          >
            <h3>Geometry and roughness</h3>
            <p>
              {study.geometry_roughness.bed_is_surveyed
                ? "Channel bed: reviewed survey raster on the hydraulic terrain grid."
                : "Surveyed channel geometry is still missing. The zoned roughness case retains the estimated bed."}
            </p>
            <p>
              Spatial roughness uses ESA WorldCover 2021 and comparable classes
              in the{" "}
              <a
                href={study.geometry_roughness.source_reference}
                target="_blank"
                rel="noreferrer"
              >
                USACE roughness guidance
              </a>
              . Values are provisional and have not been calibrated to this
              reach.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Roughness zone</th>
                  <th>Manning n</th>
                  <th>Published range</th>
                </tr>
              </thead>
              <tbody>
                {study.geometry_roughness.classes.map((zone) => (
                  <tr key={zone.name}>
                    <td>{zone.name}</td>
                    <td>{zone.n.toFixed(3)}</td>
                    <td>
                      {zone.low.toFixed(3)}–{zone.high.toFixed(3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p>
              Ranges describe comparable land classes; they are not confidence
              limits.
            </p>
            {study.geometry_roughness.available_cases.map((item) => (
              <p key={item.id}>
                View in Scenario lab → Base scenario case → {item.label}.
              </p>
            ))}
          </section>
        )}
        {study.inflow_improvement && (
          <div className="inflow-improvement">
            <h3>Inflow improvement candidate</h3>
            <p>
              {study.inflow_improvement.additional_reviewed_observations}{" "}
              additional timed upstream observations reviewed.
              {study.inflow_improvement.scores && (
                <>
                  {" "}
                  Withheld routing KGE:{" "}
                  {fmt(study.inflow_improvement.scores.validation.baseline.kge)}
                  {" → "}
                  {fmt(
                    study.inflow_improvement.scores.validation.candidate.kge,
                  )}
                  .
                </>
              )}
            </p>
            <p>
              Maximum observation gaps: Warsak{" "}
              {study.inflow_improvement.coverage.warsak.maximum_gap_hours} h;
              Swat/Charsadda Road{" "}
              {
                study.inflow_improvement.coverage["charsadda-road"]
                  .maximum_gap_hours
              }{" "}
              h. Complete timed upstream and lateral inputs are still required.
            </p>
            <p>
              Local inflows: {study.inflow_improvement.lateral_inflows.state}.
            </p>
            {!study.inflow_improvement.promoted_to_hydraulic_models && (
              <p>
                Candidate has not been applied to the HEC-RAS or LISFLOOD
                results shown in Model results.
              </p>
            )}
          </div>
        )}
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
