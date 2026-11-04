import {
  lazy,
  Suspense,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { STATION_BY_ID } from "./data/stations";
import { downstreamOf, PILOT_ID, upstreamOf } from "./data/network";
import { defaultScenarioFor, scenarioErrors } from "./data/scenarios";
import type { Scenario } from "./data/scenarios";
import { EXAMPLE_SCENARIOS, exampleScenario } from "./data/examples";
import type { ExampleId } from "./data/examples";
import { api, CancelledError, download } from "./lib/api";
import type {
  Asset,
  DomainResult,
  Health,
  Preflight,
  PreparedCase,
  ResultSummary,
} from "./lib/api";
import type { Field } from "./lib/legend";
import { scenarioCaseValues } from "./lib/scenarioCase";
import { sameScenario } from "./lib/scenarioMatch";
import { comparisonFrame as findComparisonFrame } from "./lib/comparison";
import { usePlayback } from "./hooks/usePlayback";
import { useResultDetails } from "./hooks/useResultDetails";
import { isActive, useJobPolling } from "./hooks/useJobPolling";
import type { Job } from "./hooks/useJobPolling";
import { Hydrograph } from "./components/Hydrograph";
import { ScenarioCaseRunner } from "./components/ScenarioCaseRunner";
import type { CaseOutcome } from "./components/ScenarioCaseRunner";
import { StationCatalog } from "./components/StationCatalog";
import { NetworkSummary } from "./components/NetworkSummary";
import {
  MapLegend,
  PlaybackBar,
  ResultDetails,
  ResultPicker,
} from "./components/ResultControls";
import type { ComparisonTiming } from "./components/ResultControls";
import { DataView } from "./components/DataView";
import { VerificationView } from "./components/VerificationView";
import { ScenarioEditor } from "./components/ScenarioEditor";
import "./App.css";

const Globe = lazy(() => import("./components/Globe"));
type Tab = "scenario" | "data" | "verification";
const STORAGE = "indus-lab-scenario-v1";
const LIBRARY = "indus-lab-library-v1";
/** A server answer that belongs to one exact scenario draft. */
type ForScenario<T> = { scenario: Scenario; value: T };

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
const REFRESH_TIMEOUT_MS = 30_000;
const refreshTimeout = () => AbortSignal.timeout(REFRESH_TIMEOUT_MS);
/** Returns false when browser storage is unavailable or full. */
function persistDraft(scenario: Scenario) {
  try {
    localStorage.setItem(STORAGE, JSON.stringify(scenario));
    return true;
  } catch {
    return false;
  }
}

function App() {
  const [scenario, setScenario] = useState<Scenario>(initialScenario);
  const [tab, setTab] = useState<Tab>("scenario");
  const [view, setView] = useState<"planning" | "results">("planning");
  const [health, setHealth] = useState<Health | null>(null);
  const [assets, setAssets] = useState<Record<string, Asset>>({});
  const [results, setResults] = useState<ResultSummary[]>([]);
  const [preparedCases, setPreparedCases] = useState<PreparedCase[]>([]);
  const [resultId, setResultId] = useState("");
  const [compareId, setCompareId] = useState("");
  const [comparisonTiming, setComparisonTiming] =
    useState<ComparisonTiming>("exact");
  const [domainFor, setDomainFor] = useState<ForScenario<DomainResult>>();
  const [preflightFor, setPreflightFor] = useState<ForScenario<Preflight>>();
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");
  const [caseOutcome, setCaseOutcome] = useState<CaseOutcome>();
  const [field, setField] = useState<Field>("depth");
  const [showObserved, setShowObserved] = useState(false);
  const [library, setLibrary] = useState<Scenario[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(LIBRARY) ?? "[]");
    } catch {
      return [];
    }
  });
  const [job, setJob] = useJobPolling(setMessage);
  const abort = useRef<AbortController>(undefined);
  const [cancellable, setCancellable] = useState(false);
  const scenarioRef = useRef(scenario);
  useLayoutEffect(() => {
    scenarioRef.current = scenario;
  }, [scenario]);

  // Domain and readiness answers apply only to the draft they were computed for.
  const domain =
    domainFor?.scenario === scenario ? domainFor.value : undefined;
  const preflight =
    preflightFor?.scenario === scenario ? preflightFor.value : undefined;
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
  const details = useResultDetails([resultId, compareId], results, setMessage);
  const resultSummary = results.find((r) => r.id === resultId);
  const result = details[resultId];
  const comparing = details[compareId];
  const showResults = view === "results" && !!result;
  const loadingResult = view === "results" && !!resultSummary && !result;
  const playback = usePlayback(result?.frames.length ?? 0, showResults);
  const { rewind, stop } = playback;
  const frame = result?.frames[playback.frameIndex];
  const comparisonFrame = findComparisonFrame(
    comparing?.frames ?? [],
    frame?.time,
    comparisonTiming === "nearby" ? 60 : 0,
  );
  const graph = result?.hydrographs.find(
    (g) => g.station_id === result.scenario.outlet.station_id,
  );
  const scoreTargets = result?.scenario.validation ?? scenario.validation;
  const mapScenario = showResults ? result.scenario : scenario;

  useEffect(() => {
    if (job?.state !== "published" || !job.result_id) return;
    let active = true;
    void api<ResultSummary[]>("results")
      .then((published) => {
        if (!active) return;
        setResults(published);
        const output = published.find((item) => item.id === job.result_id);
        if (output && sameScenario(output.scenario, scenarioRef.current)) {
          setResultId(output.id);
          rewind();
          setField("depth");
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
  }, [job?.state, job?.result_id, rewind]);

  async function refresh() {
    try {
      const [h, a, r, prepared] = await Promise.all([
        api<Health>("health", undefined, { signal: refreshTimeout() }),
        api<Record<string, Asset>>("assets", undefined, {
          signal: refreshTimeout(),
        }),
        api<ResultSummary[]>("results", undefined, {
          signal: refreshTimeout(),
        }),
        api<PreparedCase[]>("prepared-cases", undefined, {
          signal: refreshTimeout(),
        }).catch(() => []),
      ]);
      setHealth(h);
      setAssets(a);
      setResults(r);
      setPreparedCases(prepared);
      const current = scenarioRef.current;
      const output = r.find(
        (item) => item.frame_count && sameScenario(item.scenario, current),
      );
      if (output) openOutput(output);
      if (a.dem && current.domain.dem_sha256 !== a.dem.sha256) {
        const next = {
          ...current,
          domain: { ...current.domain, dem_sha256: a.dem.sha256 },
        };
        scenarioRef.current = next;
        setScenario(next);
        persistDraft(next);
      }
    } catch {
      setHealth(null);
    }
  }
  useEffect(() => {
    void refresh();
    // Load the workspace once on mount; later refreshes are user-initiated.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const update = (next: Scenario) => {
    scenarioRef.current = next;
    setScenario(next);
    setView("planning");
    stop();
    setMessage("");
    setCaseOutcome(undefined);
    setNotice(
      persistDraft(next)
        ? ""
        : "Browser storage is full. Export the scenario to preserve changes.",
    );
  };
  function openOutput(output: ResultSummary) {
    setResultId(output.id);
    rewind();
    setField("depth");
    setView("results");
  }
  function selectStation(id: string) {
    const s = defaultScenarioFor(STATION_BY_ID[id]);
    if (assets.dem) s.domain.dem_sha256 = assets.dem.sha256;
    update(s);
  }
  function customOutlet() {
    const s = defaultScenarioFor(STATION_BY_ID[PILOT_ID]);
    s.id = "custom-outlet";
    s.name = "Custom outlet study";
    s.outlet.station_id = null;
    s.forcing.upstream_station_ids = [];
    if (assets.dem) s.domain.dem_sha256 = assets.dem.sha256;
    update(s);
  }
  function loadExample(id: ExampleId) {
    update(exampleScenario(id, assets.dem?.sha256 ?? null));
    rewind();
    setNotice("Example loaded. Edit its inputs, then check readiness.");
  }
  function edit(change: (next: Scenario) => void) {
    const next = structuredClone(scenario);
    change(next);
    update(next);
  }
  async function action(
    name: string,
    work: (signal: AbortSignal) => Promise<void>,
  ) {
    const controller = new AbortController();
    abort.current = controller;
    setCancellable(true);
    setBusy(name);
    setMessage("");
    setNotice("");
    try {
      await work(controller.signal);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "The operation could not complete.",
      );
    } finally {
      if (abort.current === controller) abort.current = undefined;
      setBusy("");
    }
  }
  function cancel() {
    if (cancellable) abort.current?.abort();
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
    await action("Import", async (signal) => {
      const value = JSON.parse(await file.text());
      const valid = await api<Scenario>("scenarios/validate", value, {
        signal,
      });
      update(valid);
      setNotice("Scenario imported and validated against schema version 1.");
    });
  }
  async function applyScenarioCase(
    base: Scenario,
    values: string,
    run: boolean,
    engine?: Scenario["hydraulics"]["engine"],
  ) {
    await action(run ? "Case run" : "Case load", async (signal) => {
      try {
        const previous = scenarioRef.current;
        const candidate = scenarioCaseValues(
          values,
          base,
          assets.dem?.sha256 ?? null,
          engine,
        );
        const valid = await api<Scenario>("scenarios/validate", candidate, {
          signal,
        });
        if (previous !== scenarioRef.current)
          throw new Error(
            "The scenario changed while loading. Apply the case again to continue.",
          );
        update(valid);
        rewind();
        setTab("scenario");
        if (!run) {
          const output = results.find(
            (item) => item.frame_count && sameScenario(item.scenario, valid),
          );
          if (output) openOutput(output);
          setCaseOutcome({
            state: "loaded",
            text: output
              ? "Case values loaded. Published output for these exact values is ready. Press Play below the map."
              : "Case values loaded into the editor. Choose Prepare & run case when ready.",
          });
          return;
        }
        let prepared: DomainResult | undefined;
        let preparationError: string | undefined;
        try {
          prepared = await api<DomainResult>("domain", valid, { signal });
        } catch (error) {
          if (error instanceof CancelledError) throw error;
          preparationError =
            error instanceof Error
              ? error.message
              : "Domain preparation failed.";
        }
        if (valid !== scenarioRef.current)
          throw new Error(
            "The scenario changed during preparation. Prepare the updated case again.",
          );
        if (prepared) setDomainFor({ scenario: valid, value: prepared });
        const check = await api<Preflight>("preflight", valid, { signal });
        if (valid !== scenarioRef.current)
          throw new Error(
            "The scenario changed during readiness checks. Prepare the updated case again.",
          );
        setPreflightFor({ scenario: valid, value: check });
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
        // Not cancellable: aborting after the server accepts would lose the job.
        setCancellable(false);
        const submitted = await api<Job>("jobs", valid);
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
  async function bindModel(project: string, plan: string, review: string) {
    await action("Bind model", async (signal) => {
      const current = scenarioRef.current;
      await api(
        "model-bindings",
        { scenario: current, project, plan, review },
        { signal },
      );
      const check = await api<Preflight>("preflight", current, { signal });
      if (current === scenarioRef.current) {
        setPreflightFor({ scenario: current, value: check });
        setNotice(
          `${current.hydraulics.engine} model attached. Prepare & run case to start when all requirements pass.`,
        );
      }
    });
  }
  function prepareDomain() {
    void action("Domain", async (signal) => {
      const current = scenarioRef.current;
      const prepared = await api<DomainResult>("domain", current, { signal });
      if (current === scenarioRef.current) {
        setDomainFor({ scenario: current, value: prepared });
        setNotice(
          `Outlet snapped ${prepared.snapped_outlet.distance_m} m. ${prepared.catchment_status}.`,
        );
      }
    });
  }
  function checkReadiness() {
    void action("Check", async (signal) => {
      const current = scenarioRef.current;
      const check = await api<Preflight>("preflight", current, { signal });
      if (current === scenarioRef.current)
        setPreflightFor({ scenario: current, value: check });
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
            Flood<span className="brand-light"> Simulation</span>
            <small>PAKISTAN FLOOD SCENARIOS</small>
          </span>
        </a>
        <nav aria-label="Workspace">
          {(
            [
              ["scenario", "Scenario lab"],
              ["data", "Data & provenance"],
              ["verification", "Plan verification"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              className={tab === id ? "active" : ""}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
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
        <StationCatalog
          stationId={stationId}
          connected={!!health}
          onSelect={selectStation}
          onCustom={customOutlet}
          onRefresh={() => void refresh()}
        />

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
                busy={busy || (isActive(job) ? "Model running" : "")}
                outcome={caseOutcome}
                onChange={() => setCaseOutcome(undefined)}
                onApply={applyScenarioCase}
                onCancel={
                  cancellable && (busy === "Case load" || busy === "Case run")
                    ? cancel
                    : undefined
                }
              />
              <div className="map-toolbar">
                <div className="segmented">
                  <button
                    className={view === "planning" ? "active" : ""}
                    onClick={() => {
                      setView("planning");
                      stop();
                    }}
                  >
                    Domain overview
                  </button>
                  <button
                    className={view === "results" ? "active" : ""}
                    onClick={() => {
                      if (!result) {
                        const output =
                          results.find(
                            (item) =>
                              item.frame_count &&
                              sameScenario(item.scenario, scenario),
                          ) ?? results.find((item) => item.frame_count);
                        if (output) openOutput(output);
                      }
                      setView("results");
                    }}
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
                <ResultPicker
                  results={results}
                  result={resultSummary}
                  compareId={compareId}
                  timing={comparisonTiming}
                  field={field}
                  onResult={(id) => {
                    setResultId(id);
                    rewind();
                  }}
                  onCompare={setCompareId}
                  onTiming={setComparisonTiming}
                  onField={setField}
                />
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
              {loadingResult && (
                <div className="inline-note" role="status">
                  Loading published output…
                </div>
              )}
              {view === "results" && !resultSummary && (
                <div className="inline-note">
                  No result selected. Publish timestamped HEC-RAS or LISFLOOD-FP
                  rasters to enable scientific playback.
                </div>
              )}
              {showResults && (
                <ResultDetails
                  result={result}
                  frame={frame}
                  field={field}
                  comparing={comparing}
                  comparisonFrame={comparisonFrame}
                  timing={comparisonTiming}
                  showObserved={showObserved}
                  onShowObserved={setShowObserved}
                />
              )}
              <PlaybackBar
                enabled={showResults}
                frameCount={result?.frames.length ?? 0}
                frameIndex={playback.frameIndex}
                time={frame?.time}
                playing={playback.playing}
                speed={playback.speed}
                onToggle={playback.toggle}
                onSeek={playback.seek}
                onSpeed={playback.setSpeed}
              />
              <MapLegend
                field={field}
                result={showResults ? result : undefined}
              />
              <NetworkSummary
                station={station}
                upstream={upstream}
                downstream={downstream}
              />
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
            <DataView
              health={health}
              assets={assets}
              onRefresh={() => void refresh()}
            />
          )}

          {tab === "verification" && (
            <VerificationView
              phaseEvidence={{
                domain: !!domain,
                inflow: !!assets.inflow,
                preflight: !!preflight?.ready,
              }}
              results={results}
              result={result}
              graph={graph}
              targets={scoreTargets}
              onReport={report}
            />
          )}
        </main>

        <ScenarioEditor
          scenario={scenario}
          station={station}
          stationId={stationId}
          assets={assets}
          health={health}
          boundaryIds={boundaryIds}
          busy={busy}
          edit={edit}
          update={update}
          onBind={bindModel}
          errors={errors}
          message={message}
          notice={notice}
          preflight={preflight}
          job={job}
          library={library}
          onPrepareDomain={prepareDomain}
          onCancel={
            cancellable &&
            ["Domain", "Check", "Bind model", "Import"].includes(busy)
              ? cancel
              : undefined
          }
          onCheck={checkReadiness}
          onRun={() =>
            void action("Run", async () => {
              setCancellable(false);
              setJob(await api<Job>("jobs", scenario));
            })
          }
          onSave={save}
          onExport={() => download(`${scenario.id}.json`, scenario)}
          onImport={(file) => void importScenario(file)}
        />
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
