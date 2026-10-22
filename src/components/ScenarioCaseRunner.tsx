import { useRef, useState } from "react";
import type { Scenario } from "../data/scenarios";

export type ScenarioCase = { key: string; label: string; scenario: Scenario };
export type CaseOutcome = {
  state: "loaded" | "blocked" | "submitted" | "error";
  text: string;
  issues?: string[];
};

export function ScenarioCaseRunner({
  cases,
  connected,
  busy,
  outcome,
  onChange,
  onApply,
}: {
  cases: ScenarioCase[];
  connected: boolean;
  busy: string;
  outcome?: CaseOutcome;
  onChange: () => void;
  onApply: (base: Scenario, values: string, run: boolean) => Promise<void>;
}) {
  const [selected, setSelected] = useState("current");
  const [values, setValues] = useState("");
  const [fileName, setFileName] = useState("");
  const [fileError, setFileError] = useState("");
  const [reading, setReading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const base = (cases.find((item) => item.key === selected) ?? cases[0])
    .scenario;
  const disabled = !connected || !!busy || reading || !!fileError;
  const prepared = cases.find((item) => item.key.startsWith("prepared:"));

  async function readFile(file: File) {
    setReading(true);
    setFileError("");
    setValues("");
    setFileName("");
    onChange();
    try {
      if (file.size > 1024 * 1024)
        throw new Error("Scenario JSON must be smaller than 1 MB.");
      setValues(await file.text());
      setFileName(file.name);
      setExpanded(true);
    } catch (error) {
      setFileError(
        error instanceof Error
          ? error.message
          : "Could not read the scenario file.",
      );
    } finally {
      setReading(false);
    }
  }

  return (
    <section className="scenario-case-runner" aria-label="Run a scenario case">
      <div className="section-title">
        <h2>Run a scenario case</h2>
        <span>APPLY VALUES TOGETHER</span>
      </div>
      <p className="case-description">
        Choose a case, or supply its values as JSON. Prepare &amp; run applies
        the values, prepares the domain and checks the model before starting
        compute.
      </p>
      {prepared && (
        <div className="case-ready">
          <button
            className="secondary-button"
            disabled={!connected || !!busy || reading}
            onClick={() => {
              setSelected(prepared.key);
              setValues("");
              setFileName("");
              setFileError("");
              void onApply(prepared.scenario, "", false);
            }}
          >
            Load runnable public case
          </button>
          <span>
            LISFLOOD-FP · 100 m grid · warmed river · estimated bed depths
          </span>
        </div>
      )}
      <div className="case-source-row">
        <label>
          Base scenario case
          <select
            value={selected}
            disabled={!!busy || reading}
            onChange={(event) => {
              setSelected(event.target.value);
              setFileError("");
              onChange();
            }}
          >
            {cases.map((item) => (
              <option key={item.key} value={item.key}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <button
          className="secondary-button"
          disabled={!!busy || reading}
          onClick={() => fileInput.current?.click()}
        >
          {reading ? "Reading file…" : "Choose JSON file"}
        </button>
        <input
          ref={fileInput}
          aria-label="Scenario case JSON file"
          type="file"
          accept=".json,application/json"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void readFile(file);
            event.target.value = "";
          }}
        />
      </div>
      <details
        open={expanded}
        onToggle={(event) => setExpanded(event.currentTarget.open)}
      >
        <summary>Paste or adjust case values</summary>
        <label>
          Case values (JSON)
          <textarea
            rows={6}
            spellCheck={false}
            value={values}
            disabled={!!busy || reading}
            placeholder={
              '{\n  "name": "Rainfall sensitivity",\n  "forcing": { "rainfall_multiplier": 1.5 }\n}'
            }
            onChange={(event) => {
              setValues(event.target.value);
              setFileName("");
              setFileError("");
              onChange();
            }}
          />
        </label>
        <p className="case-help">
          Paste a full exported scenario, or only the nested fields to change in
          the selected base case. Leave blank to use the base unchanged. Lists
          replace the base list. Use null for the DEM hash to select registered
          terrain; explicit hashes are preserved.
        </p>
        {values && (
          <button
            className="small-button"
            disabled={!!busy || reading}
            onClick={() => {
              setValues("");
              setFileName("");
              setFileError("");
              onChange();
            }}
          >
            Clear case values
          </button>
        )}
      </details>
      {fileName && <p className="case-file-name">File ready: {fileName}</p>}
      <div className="case-actions">
        <button
          className="secondary-button"
          disabled={disabled}
          onClick={() => void onApply(base, values, false)}
        >
          {busy === "Case load" ? "Loading case…" : "Load case values"}
        </button>
        <button
          className="primary-button"
          disabled={disabled}
          onClick={() => void onApply(base, values, true)}
        >
          {busy === "Case run" ? "Preparing case…" : "Prepare & run case"}
        </button>
      </div>
      <p className="case-help">
        Hydraulic runs currently support the Nowshera pilot. Complete inflows
        and a prepared model matching these values are required. Play becomes
        available when timestamped flood results are published.
      </p>
      {fileError && (
        <p className="case-outcome error" role="alert">
          {fileError}
        </p>
      )}
      {outcome && (
        <div
          className={`case-outcome ${outcome.state}`}
          role={outcome.state === "error" ? "alert" : "status"}
        >
          <strong>{outcome.text}</strong>
          {!!outcome.issues?.length && (
            <ul>
              {outcome.issues.map((issue, index) => (
                <li key={index}>{issue}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
