import { useRef } from "react";
import type { ComponentProps } from "react";
import { PILOT_ID } from "../data/network";
import type { Scenario } from "../data/scenarios";
import type { Preflight } from "../lib/api";
import type { Job } from "../hooks/useJobPolling";
import { isActive } from "../hooks/useJobPolling";
import { ScenarioFields } from "./ScenarioFields";

type Props = ComponentProps<typeof ScenarioFields> & {
  stationId: string;
  errors: string[];
  message: string;
  notice: string;
  preflight?: Preflight;
  job?: Job;
  library: Scenario[];
  onPrepareDomain: () => void;
  /** Present while the running request can still be aborted. */
  onCancel?: () => void;
  onCheck: () => void;
  onRun: () => void;
  onSave: () => void;
  onExport: () => void;
  onImport: (file: File) => void;
};

export function ScenarioEditor({
  stationId,
  errors,
  message,
  notice,
  preflight,
  job,
  library,
  onPrepareDomain,
  onCancel,
  onCheck,
  onRun,
  onSave,
  onExport,
  onImport,
  ...fields
}: Props) {
  const fileInput = useRef<HTMLInputElement>(null);
  const { health, busy } = fields;
  return (
    <aside className="scenario-panel" aria-label="Scenario editor">
      <div className="panel-label">
        02 / SCENARIO DEFINITION <span>v1</span>
      </div>
      <div className="editor-title">
        <h2>Shape the scenario.</h2>
        <span className="draft-dot">DRAFT</span>
      </div>
      <p className="muted">
        A reproducible experiment.
        <br />
        Every assumption stays with the run.
      </p>
      <ScenarioFields {...fields} />
      <div className="editor-actions">
        {errors.length > 0 && (
          <div className="error-box" role="alert">
            {errors.join(" ")}
          </div>
        )}
        {message && (
          <div className="error-box" role="alert">
            {message}
          </div>
        )}
        {notice && (
          <div className="success-box" role="status">
            {notice}
          </div>
        )}
        <div className="action-row">
          <button
            className="secondary-button"
            disabled={!health || !!busy || !!errors.length}
            onClick={onPrepareDomain}
          >
            {busy === "Domain" ? "Preparing…" : "Prepare domain"}
          </button>
          <button
            className="secondary-button"
            disabled={!health || !!busy || !!errors.length}
            onClick={onCheck}
          >
            {busy === "Check" ? "Checking…" : "Check readiness"}
          </button>
          {onCancel && (
            <button className="secondary-button" onClick={onCancel}>
              Cancel
            </button>
          )}
        </div>
        {preflight && (
          <div className="preflight-list">
            <strong>
              {preflight.ready
                ? "Prepared for compute"
                : `${preflight.checks.filter((c) => !c.passed).length} requirements to resolve`}
            </strong>
            {preflight.checks.map((check) => (
              <p key={check.key} title={check.detail}>
                <span className={check.passed ? "ready-text" : "pending-text"}>
                  {check.passed ? "✓" : "○"}
                </span>{" "}
                {check.detail}
              </p>
            ))}
          </div>
        )}
        <button
          className="primary-button"
          disabled={!!busy || !preflight?.ready || isActive(job)}
          onClick={onRun}
        >
          Run hydraulic model <span>→</span>
        </button>
        <small className="field-help">
          {stationId !== PILOT_ID
            ? "Planning available. Hydraulic compute is limited to the Nowshera pilot."
            : "Compute unlocks when real data and a reviewed model pass preflight."}
        </small>
        {job && (
          <p className="job-state" role="status">
            Job {job.id.slice(0, 8)} · {job.state}
            <small>{job.detail}</small>
          </p>
        )}
        <div className="action-row file-actions">
          <button onClick={onSave}>Save draft</button>
          <button onClick={onExport}>Export JSON ↗</button>
          <button onClick={() => fileInput.current?.click()}>Import</button>
          <input
            ref={fileInput}
            type="file"
            accept=".json,application/json"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onImport(f);
              e.target.value = "";
            }}
          />
        </div>
        {library.length > 0 && (
          <label>
            Saved drafts
            <select
              value=""
              onChange={(e) => {
                const saved = library.find((s) => s.id === e.target.value);
                if (saved) fields.update(structuredClone(saved));
              }}
            >
              <option value="">Load a saved scenario…</option>
              {library.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
    </aside>
  );
}
