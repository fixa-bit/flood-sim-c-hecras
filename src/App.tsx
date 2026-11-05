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
import {
  downstreamOf,
  HYDRAULIC_SITES,
  PILOT_ID,
  upstreamOf,
} from "./data/network";
import { defaultScenarioFor, scenarioErrors } from "./data/scenarios";
import type { Scenario } from "./data/scenarios";
import { examplesFor, exampleScenario } from "./data/examples";
import type { Example } from "./data/examples";
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
import { useExposureLayers, useResultContext } from "./hooks/useResultContext";
import { ImpactPanel } from "./components/ImpactPanel";
import { ResizablePane } from "./components/ResizablePane";
import { ObservedFlows } from "./components/ObservedFlows";
import { facilityDepth } from "./lib/exposure";
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

type DockTab = "setup" | "runner" | "live";
// "Simulation" shows impact, hydrograph and network together during playback.
const DOCK_TABS: [DockTab, string][] = [
  ["setup", "Scenario setup"],
  ["runner", "Run scenario case"],
  ["live", "Simulation"],
];

function App() {
  const [scenario, setScenario] = useState<Scenario>(initialScenario);
  const [tab, setTab] = useState<Tab>("scenario");
  const [view, setView] = useState<"planning" | "results">("planning");
  const [health, setHealth] = useState<Health | null>(null);
  const [assets, setAssets] = useState<Record<string, Asset>>({});
  // Input catalogs of the other hydraulic sites (Nowshera's is `assets`).
  const [siteAssets, setSiteAssets] = useState<
    Record<string, Record<string, Asset>>
  >({});
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
  const outletStation = scenario.outlet.station_id;
  const examples = useMemo(
    () => examplesFor(outletStation ? STATION_BY_ID[outletStation] : undefined),
    [outletStation],
  );
  const exampleCases = useMemo(
    () =>
      examples.map((item) => ({
        key: `example:${item.id}`,
        label: `Example · ${item.title}`,
        scenario: exampleScenario(item, demFor(item.stationId)),
      })),
    // demFor reads the catalogs listed here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [examples, assets, siteAssets],
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
  // The scenario editor opens on demand, and by itself when something in it
  // needs attention: a validation error or a run message.
  const [editorOpen, setEditorOpen] = useState(false);
  const editorAlert = errors.join(" ") || message;
  const [seenAlert, setSeenAlert] = useState(editorAlert);
  if (editorAlert !== seenAlert) {
    setSeenAlert(editorAlert);
    if (editorAlert) setEditorOpen(true);
  }
  const details = useResultDetails([resultId, compareId], results, setMessage);
  const resultSummary = results.find((r) => r.id === resultId);
  const result = details[resultId];
  const comparing = details[compareId];
  const showResults = view === "results" && !!result;
  const loadingResult = view === "results" && !!resultSummary && !result;
  const playback = usePlayback(result?.frames.length ?? 0, showResults);
  const { rewind, stop } = playback;
  const frame = result?.frames[playback.frameIndex];
  const exposureLayers = useExposureLayers();
  const { exposure, tributaries } = useResultContext(
    showResults ? resultId : undefined,
  );
  const [dock, setDock] = useState<DockTab>("setup");
  const [dockOpen, setDockOpen] = useState(true);
  // The case runner is its own tab, opened from Scenario setup.
  const [runnerOpen, setRunnerOpen] = useState(false);
  // The runner tab exists only while open; otherwise fall back to setup.
  const dockTab = dock === "runner" && !runnerOpen ? "setup" : dock;
  const facilityDepths = useMemo(() => {
    if (!showResults || !exposure?.available) return undefined;
    return Object.fromEntries(
      exposure.facilities.items.map((item) => [
        item.id,
        facilityDepth(item, playback.frameIndex),
      ]),
    );
  }, [showResults, exposure, playback.frameIndex]);
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
      const otherSites = HYDRAULIC_SITES.filter((site) => site !== PILOT_ID);
      const siteCatalogs = Promise.all(
        otherSites.map((site) =>
          api<Record<string, Asset>>(`assets?site=${site}`, undefined, {
            signal: refreshTimeout(),
          }).catch(() => ({}) as Record<string, Asset>),
        ),
      ).then((catalogs) =>
        Object.fromEntries(otherSites.map((site, i) => [site, catalogs[i]])),
      );
      const [h, a, r, prepared, sites] = await Promise.all([
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
        siteCatalogs,
      ]);
      setHealth(h);
      setAssets(a);
      setSiteAssets(sites);
      setResults(r);
      setPreparedCases(prepared);
      const current = scenarioRef.current;
      const output = r.find(
        (item) => item.frame_count && sameScenario(item.scenario, current),
      );
      if (output) openOutput(output);
      const currentSite = siteOf(current.outlet.station_id);
      const currentDem = (currentSite === PILOT_ID ? a : sites[currentSite])
        ?.dem;
      if (currentDem && current.domain.dem_sha256 !== currentDem.sha256) {
        const next = {
          ...current,
          domain: { ...current.domain, dem_sha256: currentDem.sha256 },
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
  /** The hydraulic site whose catalog a station uses. */
  function siteOf(id: string | null | undefined) {
    return id && HYDRAULIC_SITES.includes(id) ? id : PILOT_ID;
  }
  function catalogFor(id: string | null | undefined) {
    const site = siteOf(id);
    return site === PILOT_ID ? assets : (siteAssets[site] ?? {});
  }
  function demFor(id: string | null | undefined) {
    return catalogFor(id).dem?.sha256 ?? null;
  }
  function selectStation(id: string) {
    const s = defaultScenarioFor(STATION_BY_ID[id]);
    s.domain.dem_sha256 = demFor(id);
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
  function loadExample(example: Example) {
    update(exampleScenario(example, demFor(example.stationId)));
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
          demFor(base.outlet.station_id),
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
      <div className={`workspace ${editorOpen ? "" : "editor-closed"}`}>
        <StationCatalog
          stationId={stationId}
          connected={!!health}
          onSelect={selectStation}
          onCustom={customOutlet}
          onRefresh={() => void refresh()}
        />

        <main className={`main-panel ${tab === "scenario" ? "lab" : ""}`}>
          <div className="main-head">
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
            <button
              className={`editor-toggle ${editorOpen ? "active" : ""}`}
              aria-expanded={editorOpen}
              aria-controls="scenario-editor"
              onClick={() => setEditorOpen(!editorOpen)}
            >
              Shape the scenario{" "}
              <span aria-hidden="true">{editorOpen ? "▸" : "◂"}</span>
            </button>
          </div>

          {tab === "scenario" && (
            <div className="lab-layout">
              <div className="map-column">
                <div className="map-toolbar">
                  <div className="segmented">
                    <button
                      className={view === "planning" ? "active" : ""}
                      onClick={() => {
                        setView("planning");
                        setDock("setup");
                        stop();
                      }}
                    >
                      Domain overview
                    </button>
                    <button
                      className={view === "results" ? "active" : ""}
                      onClick={() => {
                        // Prefer this exact case, then any result at the selected
                        // station; only with nothing open fall back to any result.
                        const here = scenario.outlet.station_id;
                        if (
                          !result ||
                          result.scenario.outlet.station_id !== here
                        ) {
                          const output =
                            results.find(
                              (item) =>
                                item.frame_count &&
                                sameScenario(item.scenario, scenario),
                            ) ??
                            results.find(
                              (item) =>
                                item.frame_count &&
                                item.scenario.outlet.station_id === here,
                            ) ??
                            (result
                              ? undefined
                              : results.find((item) => item.frame_count));
                          if (output) openOutput(output);
                        }
                        setView("results");
                        setDock("live");
                      }}
                    >
                      Model results <span>{results.length}</span>
                    </button>
                  </div>
                  {view === "results" ? (
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
                  ) : (
                    <span className="toolbar-caption">
                      {`${scenario.domain.radius_km * 2} km study window`}
                    </span>
                  )}
                </div>
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
                    population={exposureLayers.population?.overlay}
                    facilityDepths={facilityDepths}
                    facilityFloodM={
                      exposure?.available
                        ? exposure.facility_flood_m
                        : undefined
                    }
                    tributaries={
                      showResults && tributaries?.available
                        ? tributaries.entering
                        : undefined
                    }
                    columnsUrl={
                      showResults && exposure?.available
                        ? exposure.columns?.url
                        : undefined
                    }
                    frameIndex={playback.frameIndex}
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
                    No result selected. Publish timestamped HEC-RAS or
                    LISFLOOD-FP rasters to enable scientific playback.
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
                <div className="map-footer">
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
                </div>
              </div>
              <section
                className={`dock ${dockOpen ? "" : "collapsed"}`}
                aria-label="Scenario panels"
              >
                <div className="dock-tabs" role="tablist">
                  {DOCK_TABS.filter(
                    ([id]) => id !== "runner" || runnerOpen,
                  ).map(([id, label]) => (
                    <span key={id} className="dock-tab">
                      <button
                        id={`dock-tab-${id}`}
                        role="tab"
                        aria-selected={dockOpen && dockTab === id}
                        aria-controls={`dock-${id}`}
                        className={dockOpen && dockTab === id ? "active" : ""}
                        onClick={() => {
                          setDock(id);
                          setDockOpen(true);
                        }}
                      >
                        {label}
                      </button>
                      {id === "runner" && (
                        <button
                          className="dock-close"
                          aria-label="Close scenario case runner"
                          title="Close"
                          onClick={() => {
                            setRunnerOpen(false);
                            setDock("setup");
                          }}
                        >
                          ×
                        </button>
                      )}
                    </span>
                  ))}
                  <button
                    className="dock-toggle"
                    aria-expanded={dockOpen}
                    title={
                      dockOpen
                        ? "Hide panels to enlarge the map"
                        : "Show panels"
                    }
                    onClick={() => setDockOpen(!dockOpen)}
                  >
                    {dockOpen ? "Hide panels ▸" : "◂ Panels"}
                  </button>
                </div>
                <div
                  role="tabpanel"
                  id="dock-setup"
                  aria-labelledby="dock-tab-setup"
                  className="dock-panel"
                  hidden={!dockOpen || dockTab !== "setup"}
                >
                  <div className="setup-grid">
                    <section
                      className="scenario-examples"
                      aria-label="Example scenarios"
                    >
                      <div className="section-title">
                        <h2>Example scenarios</h2>
                        <span>LOAD · EDIT · CHECK READINESS</span>
                      </div>
                      <div className="example-grid">
                        {examples.length === 0 && (
                          <p className="footnote">
                            No example scenarios for a custom outlet. Pick a
                            station to load its examples.
                          </p>
                        )}
                        {examples.map((example) => (
                          <article
                            key={example.id}
                            className={`example-card ${scenario.id === example.id ? "selected" : ""}`}
                          >
                            <span className="example-label">
                              {example.label}
                            </span>
                            <h3>{example.title}</h3>
                            <p>{example.description}</p>
                            <button
                              className="small-button"
                              disabled={!!busy}
                              onClick={() => loadExample(example)}
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
                    <div className="runner-launch">
                      <button
                        className="secondary-button"
                        onClick={() => {
                          setRunnerOpen(true);
                          setDock("runner");
                        }}
                      >
                        Run a scenario case <span aria-hidden="true">↗</span>
                      </button>
                      <p>
                        Load a runnable public or HEC-RAS case, or supply its
                        values as JSON, then prepare and run it.
                      </p>
                    </div>
                  </div>
                </div>
                <div
                  role="tabpanel"
                  id="dock-runner"
                  aria-labelledby="dock-tab-runner"
                  className="dock-panel"
                  hidden={!dockOpen || dockTab !== "runner"}
                >
                  <ScenarioCaseRunner
                    cases={scenarioCases}
                    connected={!!health}
                    busy={busy || (isActive(job) ? "Model running" : "")}
                    outcome={caseOutcome}
                    onChange={() => setCaseOutcome(undefined)}
                    onApply={applyScenarioCase}
                    onCancel={
                      cancellable &&
                      (busy === "Case load" || busy === "Case run")
                        ? cancel
                        : undefined
                    }
                  />
                </div>
                <div
                  role="tabpanel"
                  id="dock-live"
                  aria-labelledby="dock-tab-live"
                  className="dock-panel live-panel"
                  hidden={!dockOpen || dockTab !== "live"}
                >
                  {showResults && (
                    <ResizablePane label="exposure and streams">
                      <ImpactPanel
                        exposure={exposure}
                        tributaries={tributaries}
                        layers={exposureLayers}
                        frameIndex={playback.frameIndex}
                      />
                    </ResizablePane>
                  )}
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
                      width={420}
                    />
                  </section>
                  <ObservedFlows
                    stationId={scenario.outlet.station_id}
                    stationName={station?.name}
                    time={showResults ? frame?.time : undefined}
                  />
                  <NetworkSummary
                    station={station}
                    upstream={upstream}
                    downstream={downstream}
                  />
                </div>
              </section>
            </div>
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

        <div className="editor-slot" id="scenario-editor" hidden={!editorOpen}>
          <ScenarioEditor
            onClose={() => setEditorOpen(false)}
            scenario={scenario}
            station={station}
            stationId={stationId}
            assets={catalogFor(scenario.outlet.station_id)}
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
