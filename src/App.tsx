import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { STATIONS, STATION_BY_ID } from "./data/stations";
import {
  downstreamOf,
  PILOT_ID,
  STARTING_STATIONS,
  stationNames,
  upstreamOf,
} from "./data/network";
import {
  applyPreset,
  defaultScenarioFor,
  KIND_LABELS,
  lakhToM3s,
  scenarioErrors,
} from "./data/scenarios";
import type { Scenario, ScenarioKind } from "./data/scenarios";
import { SOURCES } from "./data/sources";
import { EXAMPLE_SCENARIOS, exampleScenario } from "./data/examples";
import type { ExampleId } from "./data/examples";
import { api, download } from "./lib/api";
import type {
  Asset,
  DomainResult,
  Health,
  Preflight,
  PreparedCase,
  Result,
} from "./lib/api";
import { Hydrograph } from "./components/Hydrograph";
import { StudyPanel } from "./components/StudyPanel";
import { ScenarioCaseRunner } from "./components/ScenarioCaseRunner";
import type { CaseOutcome } from "./components/ScenarioCaseRunner";
import { scenarioCaseValues } from "./lib/scenarioCase";
import "./App.css";

const Globe = lazy(() => import("./components/Globe"));
type Tab = "scenario" | "data" | "verification";
const STORAGE = "indus-lab-scenario-v1";
const LIBRARY = "indus-lab-library-v1";
function initialScenario(): Scenario {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE) ?? "null");
    if (
      saved?.schema_version === 1 &&
      saved.outlet &&
      saved.domain &&
      saved.time &&
      saved.forcing &&
      saved.hydraulics?.structures &&
      saved.validation?.gauge_ids &&
      saved.provenance &&
      scenarioErrors(saved).length === 0
    )
      return saved;
  } catch {
    /* Start clean if browser storage is unavailable or invalid. */
  }
  return defaultScenarioFor(STATION_BY_ID[PILOT_ID]);
}
const fmt = (n: number | null | undefined, digits = 2) =>
  n == null ? "—" : n.toFixed(digits);
const utc = (time?: string) =>
  time
    ? `${new Date(time).toISOString().slice(0, 16).replace("T", " ")} UTC`
    : "No model output";

function App() {
  const [scenario, setScenario] = useState<Scenario>(initialScenario);
  const [tab, setTab] = useState<Tab>("scenario");
  const [view, setView] = useState<"planning" | "results">("planning");
  const [query, setQuery] = useState("");
  const [allStations, setAllStations] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [assets, setAssets] = useState<Record<string, Asset>>({});
  const [results, setResults] = useState<Result[]>([]);
  const [preparedCases, setPreparedCases] = useState<PreparedCase[]>([]);
  const [resultId, setResultId] = useState("");
  const [compareId, setCompareId] = useState("");
  const [domain, setDomain] = useState<DomainResult>();
  const [preflight, setPreflight] = useState<Preflight>();
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");
  const [caseOutcome, setCaseOutcome] = useState<CaseOutcome>();
  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [field, setField] = useState<"depth" | "wse" | "velocity">("depth");
  const [showObserved, setShowObserved] = useState(false);
  const [library, setLibrary] = useState<Scenario[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(LIBRARY) ?? "[]");
    } catch {
      return [];
    }
  });
  const [job, setJob] = useState<{
    id: string;
    state: string;
    detail?: string;
    result_id?: string;
  }>();
  const jobId = job?.id;
  const jobState = job?.state;
  const fileInput = useRef<HTMLInputElement>(null);
  const scenarioRef = useRef(scenario);
  scenarioRef.current = scenario;
  const exampleCases = useMemo(
    () =>
      EXAMPLE_SCENARIOS.map((item) => ({
        key: `example:${item.id}`,
        label: `Example · ${item.title}`,
        scenario: exampleScenario(item.id, assets.dem?.sha256 ?? null),
      })),
    [assets.dem?.sha256],
  );
  const scenarioCases = [
    { key: "current", label: `Current · ${scenario.name}`, scenario },
    ...exampleCases,
    ...preparedCases.map((item) => ({
      key: `prepared:${item.scenario.id}`,
      label: item.label,
      scenario: item.scenario,
    })),
    ...library.map((saved) => ({
      key: `saved:${saved.id}`,
      label: `Saved · ${saved.name}`,
      scenario: saved,
    })),
  ];
  const station = scenario.outlet.station_id
    ? STATION_BY_ID[scenario.outlet.station_id]
    : undefined;
  const stationId = station?.id ?? "";
  const downstream = downstreamOf(stationId);
  const upstream = upstreamOf(stationId);
  const boundaryIds = [
    ...new Set([
      ...upstream,
      ...(stationId === PILOT_ID ? ["charsadda-road"] : []),
      ...scenario.forcing.upstream_station_ids,
    ]),
  ];
  const errors = scenarioErrors(scenario);
  const result = results.find((r) => r.id === resultId);
  const comparing = results.find((r) => r.id === compareId);
  const frame = result?.frames[frameIndex];
  const comparisonFrame = comparing?.frames.find(
    (f) => Date.parse(f.time) === Date.parse(frame?.time ?? ""),
  );
  const graph = result?.hydrographs.find(
    (g) => g.station_id === result.scenario.outlet.station_id,
  );
  const showResults = view === "results" && !!result;
  const scoreTargets = result?.scenario.validation ?? scenario.validation;
  const mapScenario = showResults ? result.scenario : scenario;
  const visibleStations = STATIONS.filter(
    (s) =>
      (allStations || STARTING_STATIONS.includes(s.id)) &&
      `${s.name} ${s.riverName}`.toLowerCase().includes(query.toLowerCase()),
  ).sort(
    (a, b) =>
      (STARTING_STATIONS.indexOf(a.id) < 0
        ? 100
        : STARTING_STATIONS.indexOf(a.id)) -
      (STARTING_STATIONS.indexOf(b.id) < 0
        ? 100
        : STARTING_STATIONS.indexOf(b.id)),
  );

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE, JSON.stringify(scenario));
    } catch {
      setNotice(
        "Browser storage is full. Export the scenario to preserve changes.",
      );
    }
  }, [scenario]);
  useEffect(() => {
    setDomain(undefined);
    setPreflight(undefined);
    setPlaying(false);
  }, [scenario]);
  useEffect(() => {
    if (!playing || !result) return;
    const timer = setInterval(
      () =>
        setFrameIndex((index) => {
          if (index >= result.frames.length - 1) {
            setPlaying(false);
            return index;
          }
          return index + 1;
        }),
      800,
    );
    return () => clearInterval(timer);
  }, [playing, result]);
  useEffect(() => {
    if (!jobId || !jobState || !["queued", "running"].includes(jobState))
      return;
    let active = true;
    const poll = () => {
      void api<NonNullable<typeof job>>(`jobs/${jobId}`)
        .then((next) => {
          if (active) setJob(next);
        })
        .catch((e) => {
          if (active) setMessage(e.message);
        });
    };
    poll();
    const timer = setInterval(poll, 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [jobId, jobState]);
  useEffect(() => {
    void refresh();
  }, []);
  useEffect(() => {
    if (job?.state !== "published" || !job.result_id) return;
    let active = true;
    void api<Result[]>("results")
      .then((published) => {
        if (!active) return;
        setResults(published);
        const output = published.find((item) => item.id === job.result_id);
        if (
          output &&
          JSON.stringify(output.scenario) ===
            JSON.stringify(scenarioRef.current)
        ) {
          setResultId(output.id);
          setFrameIndex(0);
          setField("depth");
          setPlaying(false);
          setView("results");
          setCaseOutcome({
            state: "loaded",
            text: "Computed output loaded. Press Play below the map. This public-data screening is exploratory and uncalibrated.",
          });
        }
      })
      .catch((error) => setMessage(error.message));
    return () => {
      active = false;
    };
  }, [job?.state, job?.result_id]);

  async function refresh() {
    try {
      const [h, a, r, prepared] = await Promise.all([
        api<Health>("health"),
        api<Record<string, Asset>>("assets"),
        api<Result[]>("results"),
        api<PreparedCase[]>("prepared-cases").catch(() => []),
      ]);
      setHealth(h);
      setAssets(a);
      setResults(r);
      setPreparedCases(prepared);
      if (a.dem)
        setScenario((s) =>
          s.domain.dem_sha256 === a.dem.sha256
            ? s
            : { ...s, domain: { ...s.domain, dem_sha256: a.dem.sha256 } },
        );
    } catch {
      setHealth(null);
    }
  }
  const update = (next: Scenario) => {
    scenarioRef.current = next;
    setScenario(next);
    setView("planning");
    setMessage("");
    setNotice("");
    setCaseOutcome(undefined);
  };
  function selectStation(id: string) {
    const s = defaultScenarioFor(STATION_BY_ID[id]);
    if (assets.dem) s.domain.dem_sha256 = assets.dem.sha256;
    update(s);
  }
  function loadExample(id: ExampleId) {
    update(exampleScenario(id, assets.dem?.sha256 ?? null));
    setFrameIndex(0);
    setNotice("Example loaded. Edit its inputs, then check readiness.");
  }
  function edit(change: (next: Scenario) => void) {
    const next = structuredClone(scenario);
    change(next);
    update(next);
  }
  async function action(name: string, work: () => Promise<void>) {
    setBusy(name);
    setMessage("");
    setNotice("");
    try {
      await work();
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "The operation could not complete.",
      );
    } finally {
      setBusy("");
    }
  }
  function save() {
    if (errors.length) {
      setMessage(errors.join(" "));
      return;
    }
    const next = [
      ...library.filter((s) => s.id !== scenario.id),
      structuredClone(scenario),
    ];
    try {
      localStorage.setItem(LIBRARY, JSON.stringify(next));
      setLibrary(next);
      setNotice("Scenario saved to this browser.");
    } catch {
      setMessage("Could not save locally. Export JSON to keep this scenario.");
    }
  }
  async function importScenario(file: File) {
    await action("Import", async () => {
      const value = JSON.parse(await file.text());
      const valid = await api<Scenario>("scenarios/validate", value);
      update(valid);
      setNotice("Scenario imported and validated against schema version 1.");
    });
  }
  async function applyScenarioCase(
    base: Scenario,
    values: string,
    run: boolean,
  ) {
    await action(run ? "Case run" : "Case load", async () => {
      try {
        const previous = scenarioRef.current;
        const candidate = scenarioCaseValues(
          values,
          base,
          assets.dem?.sha256 ?? null,
        );
        const valid = await api<Scenario>("scenarios/validate", candidate);
        if (previous !== scenarioRef.current)
          throw new Error(
            "The scenario changed while loading. Apply the case again to continue.",
          );
        update(valid);
        setFrameIndex(0);
        setTab("scenario");
        if (!run) {
          setCaseOutcome({
            state: "loaded",
            text: "Case values loaded into the editor. Choose Prepare & run case when ready.",
          });
          return;
        }
        let prepared: DomainResult | undefined;
        let preparationError: string | undefined;
        try {
          prepared = await api<DomainResult>("domain", valid);
        } catch (error) {
          preparationError =
            error instanceof Error
              ? error.message
              : "Domain preparation failed.";
        }
        if (valid !== scenarioRef.current)
          throw new Error(
            "The scenario changed during preparation. Prepare the updated case again.",
          );
        if (prepared) setDomain(prepared);
        const check = await api<Preflight>("preflight", valid);
        if (valid !== scenarioRef.current)
          throw new Error(
            "The scenario changed during readiness checks. Prepare the updated case again.",
          );
        setPreflight(check);
        if (!check.ready || !prepared) {
          const issues = check.checks
            .filter((item) => !item.passed)
            .map((item) => item.detail);
          if (preparationError)
            issues.unshift(`Domain preparation: ${preparationError}`);
          setCaseOutcome({
            state: "blocked",
            text: "Case loaded. Simulation needs the following inputs:",
            issues,
          });
          return;
        }
        const submitted = await api<NonNullable<typeof job>>("jobs", valid);
        setJob(submitted);
        setCaseOutcome({
          state: "submitted",
          text: "Case submitted to the hydraulic model. Track its status in the scenario editor.",
        });
      } catch (error) {
        setCaseOutcome({
          state: "error",
          text:
            error instanceof Error
              ? error.message
              : "Could not apply the scenario case.",
        });
        throw error;
      }
    });
  }
  function report() {
    download(`${scenario.id}-report.json`, {
      exported_at: new Date().toISOString(),
      purpose: "R&D only",
      scenario,
      input_assets: assets,
      domain: domain ?? null,
      preflight: preflight ?? null,
      viewed_result: showResults ? result : null,
      limitations: [
        "Station coordinates require snap and review.",
        "Network connections do not predict downstream timing.",
        "Unvalidated output is not an official flood warning.",
      ],
    });
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#">
          <span className="brand-mark">≋</span>
          <span>
            INDUS<span className="brand-light">LAB</span>
            <small>PAKISTAN FLOOD SCENARIOS</small>
          </span>
        </a>
        <nav aria-label="Workspace">
          <button
            className={tab === "scenario" ? "active" : ""}
            onClick={() => setTab("scenario")}
          >
            Scenario lab
          </button>
          <button
            className={tab === "data" ? "active" : ""}
            onClick={() => setTab("data")}
          >
            Data & provenance
          </button>
          <button
            className={tab === "verification" ? "active" : ""}
            onClick={() => setTab("verification")}
          >
            Plan verification
          </button>
        </nav>
        <div className="header-end">
          <span className="rd-badge">RESEARCH / DEVELOPMENT</span>
          <button
            className="icon-button"
            onClick={report}
            title="Export research report"
          >
            ↗ <span>Export report</span>
          </button>
        </div>
      </header>
      <div className="workspace">
        <aside className="station-panel" aria-label="Station catalog">
          <div className="panel-label">
            01 / STATION CATALOG <span>{STATIONS.length}</span>
          </div>
          <h2>Start upstream.</h2>
          <p className="muted">
            Trace the connected system
            <br />
            before testing the floodplain.
          </p>
          <label className="search-box">
            <span>⌕</span>
            <input
              aria-label="Search stations"
              placeholder="Search station or river"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="catalog-label">
            {allStations
              ? "NATIONAL REFERENCE CATALOG"
              : "UPPER BASIN STARTING POINTS"}
          </div>
          <div className="station-list">
            {visibleStations.map((s) => (
              <button
                key={s.id}
                className={`station-button ${stationId === s.id ? "selected" : ""}`}
                onClick={() => selectStation(s.id)}
              >
                <span className={`station-dot ${s.kind}`} />
                <span>
                  <strong>{s.name}</strong>
                  <small>
                    {s.riverName} <span>·</span>{" "}
                    {s.kind === "dam"
                      ? "Reservoir"
                      : s.kind === "barrage"
                        ? "Barrage"
                        : "River gauge"}
                  </small>
                </span>
                {s.id === PILOT_ID ? (
                  <span className="pilot-badge">PILOT</span>
                ) : (
                  <span className="station-arrow">↗</span>
                )}
              </button>
            ))}
          </div>
          {!visibleStations.length && (
            <p className="muted">No matching stations.</p>
          )}
          <button
            className="text-button catalog-toggle"
            onClick={() => setAllStations(!allStations)}
          >
            {allStations
              ? "← Upper basin selection"
              : `Browse all ${STATIONS.length} stations →`}
          </button>
          <button
            className="custom-button"
            onClick={() => {
              const s = defaultScenarioFor(STATION_BY_ID[PILOT_ID]);
              s.id = "custom-outlet";
              s.name = "Custom outlet study";
              s.outlet.station_id = null;
              s.forcing.upstream_station_ids = [];
              if (assets.dem) s.domain.dem_sha256 = assets.dem.sha256;
              update(s);
            }}
          >
            ＋ Custom lat / long or gauge
          </button>
          <div className="pilot-note">
            <span className="eyebrow">FIRST PROOF</span>
            <strong>Nowshera · August 2022</strong>
            <p>
              Warsak → Nowshera → Attock
              <br />
              Upstream boundaries first. Expand hydraulic runs after the pilot
              is validated.
            </p>
          </div>
          <div className="service-status">
            <i className={health ? "online" : ""} />
            <span>
              {health
                ? "Local data service connected"
                : "Local data service offline"}
            </span>
            <button
              title="Refresh service and data"
              onClick={() => void refresh()}
            >
              ↻
            </button>
          </div>
        </aside>

        <main className="main-panel">
          <div className="workspace-heading">
            <div>
              <span className="eyebrow">
                {showResults
                  ? "PUBLISHED MODEL OUTPUT"
                  : "UPSTREAM SCENARIO WORKSPACE"}
              </span>
              <h1>
                {showResults ? (
                  result.scenario.name
                ) : station ? (
                  <>
                    {station.name}
                    <span> / {station.riverName} River</span>
                  </>
                ) : (
                  "Custom outlet study"
                )}
              </h1>
              <p>
                {mapScenario.outlet.lat.toFixed(4)}° N <span>·</span>{" "}
                {mapScenario.outlet.lon.toFixed(4)}° E <span>·</span>{" "}
                {showResults ? result.engine : "Indus basin system"}
              </p>
            </div>
            <span
              className={`status-badge ${showResults && result.validation_passed ? "verified" : ""}`}
            >
              {showResults
                ? result.validation_passed
                  ? "VALIDATION TARGETS MET"
                  : "UNVALIDATED OUTPUT"
                : "SCENARIO PREPARATION"}
            </span>
          </div>
          <div className="pipeline" aria-label="Scientific workflow">
            {[
              "Catalog",
              "Domain",
              "Hydrology",
              "Hydraulics",
              "Validation",
              "Playback",
            ].map((step, i) => (
              <div key={step} className={i === 0 ? "current" : ""}>
                <span>{String(i + 1).padStart(2, "0")}</span>
                {step}
                {i < 5 && <b>›</b>}
              </div>
            ))}
          </div>

          {tab === "scenario" && (
            <>
              <section
                className="scenario-examples"
                aria-label="Example scenarios"
              >
                <div className="section-title">
                  <h2>Example scenarios</h2>
                  <span>LOAD · EDIT · CHECK READINESS</span>
                </div>
                <div className="example-grid">
                  {EXAMPLE_SCENARIOS.map((example) => (
                    <article
                      key={example.id}
                      className={`example-card ${scenario.id === example.id ? "selected" : ""}`}
                    >
                      <span className="example-label">{example.label}</span>
                      <h3>{example.title}</h3>
                      <p>{example.description}</p>
                      <button
                        className="small-button"
                        disabled={!!busy}
                        onClick={() => loadExample(example.id)}
                      >
                        {example.button}{" "}
                        <span aria-hidden="true">
                          {scenario.id === example.id ? "✓" : "↗"}
                        </span>
                      </button>
                    </article>
                  ))}
                </div>
              </section>
              <ScenarioCaseRunner
                cases={scenarioCases}
                connected={!!health}
                busy={
                  busy ||
                  (["queued", "running"].includes(job?.state ?? "")
                    ? "Model running"
                    : "")
                }
                outcome={caseOutcome}
                onChange={() => setCaseOutcome(undefined)}
                onApply={applyScenarioCase}
              />
              <div className="map-toolbar">
                <div className="segmented">
                  <button
                    className={view === "planning" ? "active" : ""}
                    onClick={() => {
                      setView("planning");
                      setPlaying(false);
                    }}
                  >
                    Domain overview
                  </button>
                  <button
                    className={view === "results" ? "active" : ""}
                    onClick={() => setView("results")}
                  >
                    Model results <span>{results.length}</span>
                  </button>
                </div>
                <span className="toolbar-caption">
                  {showResults
                    ? "Raster fields from the model"
                    : `${scenario.domain.radius_km * 2} km study window`}
                </span>
              </div>
              {view === "results" && (
                <div className="result-picker">
                  <label>
                    Result A
                    <select
                      aria-label="Result A"
                      value={resultId}
                      onChange={(e) => {
                        setResultId(e.target.value);
                        setFrameIndex(0);
                        setPlaying(false);
                      }}
                    >
                      <option value="">Select published output</option>
                      {results.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.scenario.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Compare B
                    <select
                      aria-label="Result B"
                      value={compareId}
                      onChange={(e) => setCompareId(e.target.value)}
                    >
                      <option value="">No comparison</option>
                      {results
                        .filter(
                          (r) =>
                            r.id !== resultId &&
                            (!result ||
                              r.scenario.outlet.station_id ===
                                result.scenario.outlet.station_id),
                        )
                        .map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.scenario.name}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Field
                    <select
                      aria-label="Model field"
                      value={field}
                      onChange={(e) => setField(e.target.value as typeof field)}
                    >
                      <option value="depth">Depth (m)</option>
                      <option value="wse">Water surface (m)</option>
                      <option value="velocity">Speed (m/s)</option>
                    </select>
                  </label>
                </div>
              )}
              <Suspense
                fallback={
                  <div className="map-loading">
                    Loading georeferenced workspace…
                  </div>
                }
              >
                <Globe
                  scenario={mapScenario}
                  domain={showResults ? undefined : domain}
                  overlay={showResults ? frame?.fields[field] : undefined}
                  compare={
                    showResults ? comparisonFrame?.fields[field] : undefined
                  }
                  observed={
                    showResults &&
                    showObserved &&
                    result.extent_validation &&
                    Date.parse(result.extent_validation.time) ===
                      Date.parse(frame?.time ?? "")
                      ? result.extent_validation.overlay
                      : undefined
                  }
                  time={showResults ? frame?.time : undefined}
                  onStation={selectStation}
                />
              </Suspense>
              {view === "results" && !result && (
                <div className="inline-note">
                  No result selected. Publish timestamped HEC-RAS or LISFLOOD-FP
                  rasters to enable scientific playback.
                </div>
              )}
              {showResults && (
                <div className="result-details">
                  <span>{result.validation_status}</span>
                  {frame && !frame.fields[field] && (
                    <strong>This field was not exported for this frame.</strong>
                  )}
                  {comparing && !comparisonFrame && (
                    <strong>B has no frame at this model time.</strong>
                  )}
                  {comparing &&
                    comparing.terrain_sha256 !== result.terrain_sha256 && (
                      <strong>
                        A/B use different terrain hashes; interpret differences
                        accordingly.
                      </strong>
                    )}
                  <label>
                    <input
                      type="checkbox"
                      checked={showObserved}
                      disabled={!result.extent_validation?.overlay}
                      onChange={(e) => setShowObserved(e.target.checked)}
                    />{" "}
                    Observed extent at matched acquisition time
                  </label>
                </div>
              )}
              <div className="timebar">
                <button
                  className="play-button"
                  aria-label={playing ? "Pause playback" : "Play model output"}
                  disabled={!showResults || !result.frames.length}
                  onClick={() => {
                    if (frameIndex === result!.frames.length - 1)
                      setFrameIndex(0);
                    setPlaying(!playing);
                  }}
                >
                  {playing ? "Ⅱ" : "▶"}
                </button>
                <div className="time-label">
                  <span>MODEL TIME</span>
                  <strong>
                    {showResults
                      ? utc(frame?.time)
                      : "Awaiting hydraulic output"}
                  </strong>
                </div>
                <input
                  aria-label="Model timestep"
                  type="range"
                  min="0"
                  max={Math.max(0, (result?.frames.length ?? 1) - 1)}
                  value={frameIndex}
                  disabled={!showResults}
                  onChange={(e) => {
                    setPlaying(false);
                    setFrameIndex(+e.target.value);
                  }}
                />
                <span className="frame-count">
                  {showResults
                    ? `${frameIndex + 1} / ${result.frames.length}`
                    : "— / —"}
                </span>
              </div>
              <div className="map-legend">
                <span>
                  {field === "depth"
                    ? "DEPTH / m"
                    : field === "velocity"
                      ? "SPEED / m/s"
                      : "WSE / m"}
                </span>
                {(field === "depth"
                  ? ["0–0.3", "0.3–1", "1–2", "2–5", ">5"]
                  : field === "velocity"
                    ? ["0–0.5", "0.5–1", "1–2", "2–3", ">3"]
                    : ["<100", "100–300", "300–500", "500–1,000", ">1,000"]
                ).map((label, i) => (
                  <span key={label}>
                    <i
                      style={{
                        background: [
                          "#91d7f1",
                          "#3da9dc",
                          "#226fc0",
                          "#224391",
                          "#64419c",
                        ][i],
                      }}
                    />
                    {label}
                  </span>
                ))}
                <small>
                  {showResults
                    ? "Dry / nodata transparent"
                    : "Legend activates with model rasters"}
                </small>
              </div>
              <section className="network-section">
                <div className="section-title">
                  <h2>Upstream → downstream</h2>
                  <span>CONNECTIVITY / PLANNING</span>
                </div>
                <div className="network-cards">
                  <div>
                    <span>UPSTREAM BOUNDARIES</span>
                    <strong>
                      {upstream.length
                        ? stationNames(upstream)
                        : station
                          ? "Headwater catalog entry"
                          : "Snap outlet first"}
                    </strong>
                    <small>
                      {upstream.length
                        ? "Supply each contributing boundary and lateral inflow"
                        : "Catchment and tributary review required"}
                    </small>
                  </div>
                  <span className="network-arrow">→</span>
                  <div className="network-current">
                    <span>STUDY OUTLET</span>
                    <strong>{station?.name ?? "Custom outlet"}</strong>
                    <small>{station?.riverName ?? "Unassigned channel"}</small>
                  </div>
                  <span className="network-arrow">→</span>
                  <div>
                    <span>DOWNSTREAM RECEPTORS</span>
                    <strong>
                      {downstream.length
                        ? stationNames(downstream.slice(0, 4))
                        : "No downstream station in catalog"}
                      {downstream.length > 4 && " …"}
                    </strong>
                    <small>
                      {downstream.length} connected stations · no travel time
                      assumed
                    </small>
                  </div>
                </div>
                <p className="footnote">
                  Connectivity is a schematic. Flow timing, reservoir operations
                  and tributary contributions come from a calibrated routing or
                  hydraulic model.
                </p>
              </section>
              <section className="hydrograph-section">
                <div className="section-title">
                  <h2>Discharge hydrograph</h2>
                  <span>
                    {showResults && graph
                      ? `${graph.metrics.pairs} ALIGNED GAUGE PAIRS`
                      : "OBSERVED + MODELED"}
                  </span>
                </div>
                <Hydrograph
                  graph={showResults ? graph : undefined}
                  time={frame?.time}
                />
              </section>
            </>
          )}

          {tab === "data" && (
            <section className="data-view">
              <div className="section-title">
                <h2>Data with a traceable origin</h2>
                <button className="small-button" onClick={() => void refresh()}>
                  ↻ Refresh assets
                </button>
              </div>
              <p className="muted">
                Clip one bounded hydraulic domain. Prepare hydrology over the
                full contributing catchment. Every registered input retains its
                source, license and SHA-256.
              </p>
              <div className="runtime-grid">
                {[
                  ["HEC-RAS", health?.runtimes.hec_ras],
                  ["RAS Commander", health?.runtimes.ras_commander],
                  ["HEC-HMS", health?.runtimes.hec_hms],
                  ["LISFLOOD-FP", health?.runtimes.lisflood_fp],
                ].map(([name, ready]) => (
                  <div key={String(name)}>
                    <span className={ready ? "ready-text" : "muted"}>●</span>
                    <strong>{name}</strong>
                    <small>
                      {ready
                        ? "Installed"
                        : health
                          ? "Not detected"
                          : "Service offline"}
                    </small>
                  </div>
                ))}
              </div>
              <div className="source-list">
                {SOURCES.map((source) => (
                  <article key={source.key}>
                    <div>
                      <span
                        className={`source-state ${assets[source.key] ? "available" : ""}`}
                      >
                        {assets[source.key] ? "REGISTERED" : "REQUIRED INPUT"}
                      </span>
                      <h3>{source.name}</h3>
                      <a
                        href={
                          assets[source.key]?.source.startsWith("https://")
                            ? assets[source.key].source
                            : source.href
                        }
                        target="_blank"
                        rel="noreferrer"
                      >
                        {assets[source.key]?.product ?? source.product} ↗
                      </a>
                      <p>{assets[source.key]?.license ?? source.license}</p>
                      {assets[source.key]?.acquisition?.notes && (
                        <p>{assets[source.key].acquisition!.notes}</p>
                      )}
                      <small>Fallback: {source.fallback}</small>
                      {assets[source.key] && (
                        <code title={assets[source.key].sha256}>
                          SHA-256 {assets[source.key].sha256.slice(0, 24)}…
                        </code>
                      )}
                    </div>
                  </article>
                ))}
              </div>
              <StudyPanel />
              <div className="inline-note">
                Register downloaded inputs using{" "}
                <code>python -m server.cli register --help</code>. Public STAC
                COG clipping is available through <code>stac-import</code>. The
                README documents file formats and the model handoff.
              </div>
            </section>
          )}

          {tab === "verification" && (
            <section className="verification-view">
              <span className="eyebrow">
                PLAN COVERAGE / IMPLEMENTATION EVIDENCE
              </span>
              <h2>A picture must match the physics.</h2>
              <p className="muted">
                Each phase has a working software path and a separate scientific
                acceptance condition. A passing build does not validate a flood
                model.
              </p>
              <div className="verification-list">
                {[
                  [
                    "0",
                    "Station catalog",
                    "FFD flood classes, source links, SI conversion, approximate WGS84 coordinates and upstream topology.",
                    "Coordinates need MERIT snap and gauge-location review.",
                    true,
                  ],
                  [
                    "1",
                    "Domain builder",
                    "Bounded raster clipping, real-channel snap, source hashes, public STAC COG import and supplied basin overlay.",
                    "Catchment delineation must be supplied from MERIT/HydroBASINS and reviewed. Local terrain tiles must come from the same DEM clip.",
                    !!domain,
                  ],
                  [
                    "2",
                    "Hydrology & scenarios",
                    "Versioned JSON, all eight scenario families, soil and rainfall assumptions, upstream boundaries and boundary CSV intake.",
                    "HEC-HMS / rain-on-grid hydrology requires a prepared, calibrated model. No runoff or routing is invented in the browser.",
                    !!assets.inflow,
                  ],
                  [
                    "3",
                    "Hydraulic model",
                    "Preflight, scenario-bound prepared model inputs, isolated worker, HEC-RAS / LISFLOOD adapters and HDF inspection.",
                    "Actual mesh, structures, boundary conditions and numerical checks must be reviewed before compute.",
                    !!preflight?.ready,
                  ],
                  [
                    "4",
                    "Animation & validation",
                    "Time-stamped raster playback, A/B on exact matching times, hydrographs, NSE/KGE, extent CSI/POD/FAR and report export.",
                    "The 2022 Nowshera pilot must meet the documented skill targets against independent gauges and Sentinel-1 / UNOSAT.",
                    !!results.find(
                      (r) =>
                        r.scenario.outlet.station_id === PILOT_ID &&
                        r.validation_passed,
                    ),
                  ],
                ].map(([number, title, implemented, remaining, ready]) => (
                  <article key={String(number)}>
                    <span className="phase-number">0{number}</span>
                    <div>
                      <div className="section-title">
                        <h3>{title}</h3>
                        <span className={ready ? "ready-text" : "pending-text"}>
                          {ready
                            ? "EVIDENCE AVAILABLE"
                            : "INPUT / MODEL EVIDENCE PENDING"}
                        </span>
                      </div>
                      <p>{implemented}</p>
                      <small>{remaining}</small>
                    </div>
                  </article>
                ))}
              </div>
              <div className="contract-grid">
                <div>
                  <h3>Hydrology</h3>
                  <p>Gauge inflow or HEC-HMS / documented infiltration.</p>
                </div>
                <span>→</span>
                <div>
                  <h3>Hydraulics</h3>
                  <p>HEC-RAS full SWE or LISFLOOD-FP screening.</p>
                </div>
                <span>→</span>
                <div>
                  <h3>Animation</h3>
                  <p>Georeferenced model rasters. Cesium computes no water.</p>
                </div>
              </div>
              <h3 className="validation-heading">Selected output validation</h3>
              <div className="metrics-grid">
                {[
                  ["NSE", graph?.metrics.nse, scoreTargets.target_nse],
                  ["KGE", graph?.metrics.kge, scoreTargets.target_kge],
                  [
                    "Extent CSI",
                    result?.extent_validation?.csi,
                    scoreTargets.target_csi,
                  ],
                ].map(([name, value, target]) => (
                  <div key={String(name)}>
                    <span>{name}</span>
                    <strong>{fmt(value as number | undefined)}</strong>
                    <small>Target ≥ {String(target)}</small>
                  </div>
                ))}
              </div>
              <p className="footnote">
                Targets are editable acceptance assumptions. Constant or missing
                observations produce undefined scores, never a fabricated pass.
              </p>
              <button className="secondary-button" onClick={report}>
                Export scenario & verification report ↗
              </button>
            </section>
          )}
        </main>

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
          <label>
            Scenario name
            <input
              value={scenario.name}
              onChange={(e) =>
                edit((s) => {
                  s.name = e.target.value;
                })
              }
            />
          </label>
          <label>
            Experiment
            <select
              aria-label="Experiment"
              value={scenario.kind}
              onChange={(e) =>
                update(applyPreset(scenario, e.target.value as ScenarioKind))
              }
            >
              {Object.entries(KIND_LABELS).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          {!station && (
            <div className="field-row">
              <label>
                Latitude °N
                <input
                  type="number"
                  min="23"
                  max="38"
                  step="0.0001"
                  value={scenario.outlet.lat}
                  onChange={(e) =>
                    edit((s) => {
                      s.outlet.lat = +e.target.value;
                    })
                  }
                />
              </label>
              <label>
                Longitude °E
                <input
                  type="number"
                  min="60"
                  max="80"
                  step="0.0001"
                  value={scenario.outlet.lon}
                  onChange={(e) =>
                    edit((s) => {
                      s.outlet.lon = +e.target.value;
                    })
                  }
                />
              </label>
            </div>
          )}
          <div className="editor-section">
            <h3>
              <span>01</span> Domain & time
            </h3>
            <div className="field-row">
              <label>
                Radius / km
                <input
                  type="number"
                  min="1"
                  max="50"
                  value={scenario.domain.radius_km}
                  onChange={(e) =>
                    edit((s) => {
                      s.domain.radius_km = +e.target.value;
                    })
                  }
                />
              </label>
              <label>
                Mesh / m
                <input
                  type="number"
                  min="10"
                  max="1000"
                  value={scenario.domain.mesh_m}
                  onChange={(e) =>
                    edit((s) => {
                      s.domain.mesh_m = +e.target.value;
                    })
                  }
                />
              </label>
            </div>
            <div className="field-row">
              <label>
                Start / UTC
                <input
                  type="date"
                  value={scenario.time.start.slice(0, 10)}
                  onChange={(e) =>
                    edit((s) => {
                      s.time.start = `${e.target.value}T00:00:00Z`;
                    })
                  }
                />
              </label>
              <label>
                End / UTC
                <input
                  type="date"
                  value={scenario.time.end.slice(0, 10)}
                  onChange={(e) =>
                    edit((s) => {
                      s.time.end = `${e.target.value}T00:00:00Z`;
                    })
                  }
                />
              </label>
            </div>
            <div className="field-row">
              <label>
                Output / minutes
                <input
                  type="number"
                  min="1"
                  max="1440"
                  value={scenario.time.output_interval_minutes}
                  onChange={(e) =>
                    edit((s) => {
                      s.time.output_interval_minutes = +e.target.value;
                    })
                  }
                />
              </label>
              <label>
                Model CRS
                <select
                  value={scenario.domain.model_crs}
                  onChange={(e) =>
                    edit((s) => {
                      s.domain.model_crs = e.target
                        .value as Scenario["domain"]["model_crs"];
                    })
                  }
                >
                  <option>EPSG:32642</option>
                  <option>EPSG:32643</option>
                </select>
              </label>
            </div>
            <small className="field-help">
              FABDEM default ·{" "}
              {assets.dem
                ? `hash ${assets.dem.sha256.slice(0, 10)}`
                : "terrain input pending"}
            </small>
          </div>
          <div className="editor-section">
            <h3>
              <span>02</span> Forcing & initial state
            </h3>
            <label>
              Boundary method
              <select
                value={scenario.forcing.mode}
                onChange={(e) =>
                  edit((s) => {
                    s.forcing.mode = e.target
                      .value as Scenario["forcing"]["mode"];
                  })
                }
              >
                <option value="inflow_hydrograph">
                  Gauge / HEC-HMS inflow
                </option>
                <option value="rain_on_grid">Documented rain-on-grid</option>
              </select>
            </label>
            <div className="field-row">
              <label>
                Rainfall product
                <select
                  value={scenario.forcing.rainfall_product}
                  onChange={(e) =>
                    edit((s) => {
                      s.forcing.rainfall_product = e.target
                        .value as Scenario["forcing"]["rainfall_product"];
                    })
                  }
                >
                  {["GPM IMERG", "CHIRPS", "PMD gauges", "design storm"].map(
                    (p) => (
                      <option key={p}>{p}</option>
                    ),
                  )}
                </select>
              </label>
              <label>
                Rain multiplier
                <input
                  type="number"
                  step="0.1"
                  min="0.1"
                  max="5"
                  value={scenario.forcing.rainfall_multiplier}
                  onChange={(e) =>
                    edit((s) => {
                      s.forcing.rainfall_multiplier = +e.target.value;
                    })
                  }
                />
              </label>
            </div>
            <div className="field-row">
              <label>
                Soil moisture
                <select
                  value={scenario.forcing.soil_moisture}
                  onChange={(e) =>
                    edit((s) => {
                      s.forcing.soil_moisture = e.target
                        .value as Scenario["forcing"]["soil_moisture"];
                    })
                  }
                >
                  {["SMAP", "dry", "normal", "saturated"].map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
              </label>
              <label>
                Infiltration
                <select
                  value={scenario.forcing.infiltration}
                  onChange={(e) =>
                    edit((s) => {
                      s.forcing.infiltration = e.target
                        .value as Scenario["forcing"]["infiltration"];
                    })
                  }
                >
                  <option>Green-Ampt</option>
                  <option>SCS-CN</option>
                </select>
              </label>
            </div>
            {scenario.kind === "design_storm" && (
              <div className="field-row">
                <label>
                  Storm depth / mm
                  <input
                    type="number"
                    value={scenario.forcing.design_storm_mm ?? 150}
                    onChange={(e) =>
                      edit((s) => {
                        s.forcing.design_storm_mm = +e.target.value;
                      })
                    }
                  />
                </label>
                <label>
                  Return period / years
                  <input
                    type="number"
                    value={scenario.forcing.return_period_years ?? 100}
                    onChange={(e) =>
                      edit((s) => {
                        s.forcing.return_period_years = +e.target.value;
                      })
                    }
                  />
                </label>
              </div>
            )}
            {scenario.kind === "ffd_class" && (
              <label>
                FFD target class
                <select
                  value={scenario.forcing.ffd_class ?? "high"}
                  onChange={(e) =>
                    edit((s) => {
                      s.forcing.ffd_class = e.target
                        .value as Scenario["forcing"]["ffd_class"];
                    })
                  }
                >
                  {["low", "medium", "high", "veryHigh", "exceptional"]
                    .filter(
                      (c) =>
                        !station ||
                        station.limits[c as keyof typeof station.limits] !==
                          null,
                    )
                    .map((c) => (
                      <option key={c} value={c}>
                        {c === "veryHigh" ? "Very high" : c}
                      </option>
                    ))}
                </select>
                {station && scenario.forcing.ffd_class && (
                  <small className="field-help">
                    {station.limits[scenario.forcing.ffd_class] == null
                      ? "Class not published for this station"
                      : `${station.limits[scenario.forcing.ffd_class]} lakh cusecs ≈ ${Math.round(lakhToM3s(station.limits[scenario.forcing.ffd_class]!)).toLocaleString()} m³/s. Boundary target only.`}
                  </small>
                )}
              </label>
            )}
            <label>
              Rainfall bias correction / hydrology notes
              <textarea
                rows={2}
                placeholder="Gauge adjustment, IDF source or why rainfall is unused…"
                value={scenario.forcing.bias_correction}
                onChange={(e) =>
                  edit((s) => {
                    s.forcing.bias_correction = e.target.value;
                  })
                }
              />
            </label>
            <fieldset className="boundary-options">
              <legend>Contributing station boundaries</legend>
              {boundaryIds.length ? (
                boundaryIds.map((id) => (
                  <label key={id}>
                    <input
                      type="checkbox"
                      checked={scenario.forcing.upstream_station_ids.includes(
                        id,
                      )}
                      onChange={(e) =>
                        edit((s) => {
                          s.forcing.upstream_station_ids = e.target.checked
                            ? [...s.forcing.upstream_station_ids, id]
                            : s.forcing.upstream_station_ids.filter(
                                (v) => v !== id,
                              );
                        })
                      }
                    />
                    {STATION_BY_ID[id]?.name ??
                      (id === "charsadda-road"
                        ? "Charsadda Road (Swat)"
                        : id === "nowshera-hms"
                          ? "Modeled Kabul inflow (HEC-HMS)"
                          : id)}
                  </label>
                ))
              ) : (
                <small>
                  Additional irrigation / nullah gauges can be named in the JSON
                  boundary manifest.
                </small>
              )}
            </fieldset>
          </div>
          <div className="editor-section">
            <h3>
              <span>03</span> Hydraulic model
            </h3>
            <label>
              Compute engine
              <select
                value={scenario.hydraulics.engine}
                onChange={(e) =>
                  edit((s) => {
                    s.hydraulics.engine = e.target
                      .value as Scenario["hydraulics"]["engine"];
                    s.hydraulics.equations =
                      e.target.value === "HEC-RAS 2D"
                        ? "full SWE"
                        : "local inertial";
                  })
                }
              >
                <option>HEC-RAS 2D</option>
                <option>LISFLOOD-FP</option>
              </select>
            </label>
            <div className="engine-caption">
              <i />
              {scenario.hydraulics.equations} <span>·</span>{" "}
              {scenario.hydraulics.engine === "HEC-RAS 2D"
                ? "Gold-standard hydraulics"
                : "Fast screening"}
            </div>
            <label>
              Manning map source
              <select
                value={scenario.hydraulics.manning_source}
                onChange={(e) =>
                  edit((s) => {
                    s.hydraulics.manning_source = e.target
                      .value as Scenario["hydraulics"]["manning_source"];
                  })
                }
              >
                <option>ESA WorldCover</option>
                <option>Dynamic World</option>
              </select>
            </label>
            {scenario.hydraulics.structures.map((structure, i) => (
              <div key={i} className="structure-editor">
                <div className="field-row">
                  <label>
                    Name
                    <input
                      value={structure.name}
                      onChange={(e) =>
                        edit((s) => {
                          s.hydraulics.structures[i].name = e.target.value;
                        })
                      }
                    />
                  </label>
                  <label>
                    Type
                    <select
                      value={structure.type}
                      onChange={(e) =>
                        edit((s) => {
                          s.hydraulics.structures[i].type = e.target
                            .value as typeof structure.type;
                        })
                      }
                    >
                      {["barrage", "levee", "reservoir", "breach"].map(
                        (type) => (
                          <option key={type}>{type}</option>
                        ),
                      )}
                    </select>
                  </label>
                </div>
                <label>
                  {structure.name} specification
                  <textarea
                    rows={2}
                    placeholder="Geometry, gate operations, release or breach timing…"
                    value={structure.specification}
                    onChange={(e) =>
                      edit((s) => {
                        s.hydraulics.structures[i].specification =
                          e.target.value;
                      })
                    }
                  />
                </label>
                <button
                  className="text-button"
                  onClick={() =>
                    edit((s) => {
                      s.hydraulics.structures.splice(i, 1);
                    })
                  }
                >
                  Remove structure
                </button>
              </div>
            ))}
            <button
              className="text-button"
              onClick={() =>
                edit((s) => {
                  s.hydraulics.structures.push({
                    type: "levee",
                    name: `Structure ${s.hydraulics.structures.length + 1}`,
                    specification: "",
                  });
                })
              }
            >
              ＋ Add structure specification
            </button>
          </div>
          <details className="advanced-options">
            <summary>Validation & provenance</summary>
            <div className="field-row">
              <label>
                NSE target
                <input
                  type="number"
                  step="0.05"
                  max="1"
                  value={scenario.validation.target_nse}
                  onChange={(e) =>
                    edit((s) => {
                      s.validation.target_nse = +e.target.value;
                    })
                  }
                />
              </label>
              <label>
                KGE target
                <input
                  type="number"
                  step="0.05"
                  max="1"
                  value={scenario.validation.target_kge}
                  onChange={(e) =>
                    edit((s) => {
                      s.validation.target_kge = +e.target.value;
                    })
                  }
                />
              </label>
            </div>
            <label>
              Extent CSI target
              <input
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={scenario.validation.target_csi}
                onChange={(e) =>
                  edit((s) => {
                    s.validation.target_csi = +e.target.value;
                  })
                }
              />
            </label>
            <label>
              Validation extent
              <select
                value={scenario.validation.extent_source}
                onChange={(e) =>
                  edit((s) => {
                    s.validation.extent_source = e.target
                      .value as Scenario["validation"]["extent_source"];
                  })
                }
              >
                <option>Sentinel-1</option>
                <option>UNOSAT</option>
              </select>
            </label>
            <label>
              Scenario notes
              <textarea
                rows={4}
                value={scenario.provenance.notes}
                onChange={(e) =>
                  edit((s) => {
                    s.provenance.notes = e.target.value;
                  })
                }
              />
            </label>
            <label>
              Scenario ID
              <input
                value={scenario.id}
                onChange={(e) =>
                  edit((s) => {
                    s.id = e.target.value;
                  })
                }
              />
            </label>
          </details>
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
                onClick={() =>
                  void action("Domain", async () => {
                    const current = scenarioRef.current;
                    const prepared = await api<DomainResult>("domain", current);
                    if (current === scenarioRef.current) {
                      setDomain(prepared);
                      setNotice(
                        `Outlet snapped ${prepared.snapped_outlet.distance_m} m. ${prepared.catchment_status}.`,
                      );
                    }
                  })
                }
              >
                {busy === "Domain" ? "Preparing…" : "Prepare domain"}
              </button>
              <button
                className="secondary-button"
                disabled={!health || !!busy || !!errors.length}
                onClick={() =>
                  void action("Check", async () => {
                    const current = scenarioRef.current;
                    const check = await api<Preflight>("preflight", current);
                    if (current === scenarioRef.current) setPreflight(check);
                  })
                }
              >
                {busy === "Check" ? "Checking…" : "Check readiness"}
              </button>
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
                    <span
                      className={check.passed ? "ready-text" : "pending-text"}
                    >
                      {check.passed ? "✓" : "○"}
                    </span>{" "}
                    {check.detail}
                  </p>
                ))}
              </div>
            )}
            <button
              className="primary-button"
              disabled={
                !!busy ||
                !preflight?.ready ||
                ["queued", "running"].includes(job?.state ?? "")
              }
              onClick={() =>
                void action("Run", async () => {
                  setJob(await api("jobs", scenario));
                })
              }
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
              <button onClick={save}>Save draft</button>
              <button onClick={() => download(`${scenario.id}.json`, scenario)}>
                Export JSON ↗
              </button>
              <button onClick={() => fileInput.current?.click()}>Import</button>
              <input
                ref={fileInput}
                type="file"
                accept=".json,application/json"
                hidden
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void importScenario(f);
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
                    if (saved) update(structuredClone(saved));
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
      </div>
      <footer className="app-footer">
        <span>
          <i /> SCIENTIFIC SCENARIO LAB
        </span>
        <span>Hydrology → Hydraulics → Georeferenced output</span>
        <span>R&D only · No official warning service</span>
      </footer>
    </div>
  );
}
export default App;
