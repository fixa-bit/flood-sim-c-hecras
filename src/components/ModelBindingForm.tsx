import { useState } from "react";
import type { Scenario } from "../data/scenarios";

export function ModelBindingForm({
  engine,
  disabled,
  onBind,
}: {
  engine: Scenario["hydraulics"]["engine"];
  disabled: boolean;
  onBind: (project: string, plan: string, review: string) => Promise<void>;
}) {
  const ras = engine === "HEC-RAS 2D";
  const [project, setProject] = useState("");
  const [plan, setPlan] = useState(ras ? "01" : "screen.par");
  const [review, setReview] = useState("");
  return (
    <details className="model-binding-form">
      <summary>Attach prepared {engine} model</summary>
      <p className="field-help">
        Attach a model prepared for the current scenario, boundaries and
        terrain.
        {ras
          ? " The supplied HEC-RAS public case publishes map rasters automatically. Other HEC-RAS projects need a documented raster export for playback."
          : " Use a prepared local-inertial ACC project. The public screening case already includes automatic raster publication."}
      </p>
      <label>
        Prepared model folder
        <input
          value={project}
          disabled={disabled}
          placeholder={
            ras ? "D:\\models\\Nowshera" : "D:\\models\\Nowshera-ACC"
          }
          onChange={(event) => setProject(event.target.value)}
        />
      </label>
      <label>
        {ras ? "HEC-RAS plan number" : "LISFLOOD parameter file"}
        <input
          value={plan}
          disabled={disabled}
          onChange={(event) => setPlan(event.target.value)}
        />
      </label>
      <label>
        Model review reference
        <textarea
          rows={3}
          value={review}
          disabled={disabled}
          placeholder="Review document covering boundaries, terrain, mesh and stability"
          onChange={(event) => setReview(event.target.value)}
        />
      </label>
      <button
        className="secondary-button"
        disabled={disabled || !project.trim() || !plan.trim() || !review.trim()}
        onClick={() => void onBind(project.trim(), plan.trim(), review.trim())}
      >
        Attach {engine} model
      </button>
      <p className="field-help">
        Scenario edits require a matching prepared model and a new attachment.
      </p>
    </details>
  );
}
