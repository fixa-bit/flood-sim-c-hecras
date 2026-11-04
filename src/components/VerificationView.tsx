import type { Scenario } from "../data/scenarios";
import { PILOT_ID } from "../data/network";
import type { Hydrograph, Result, ResultSummary } from "../lib/api";

type Props = {
  phaseEvidence: {
    domain: boolean;
    inflow: boolean;
    preflight: boolean;
  };
  results: ResultSummary[];
  result?: Result;
  graph?: Hydrograph;
  targets: Scenario["validation"];
  onReport: () => void;
};

const fmt = (n: number | null | undefined, digits = 2) =>
  n == null ? "—" : n.toFixed(digits);

export function VerificationView({
  phaseEvidence,
  results,
  result,
  graph,
  targets,
  onReport,
}: Props) {
  const phases: [string, string, string, string, boolean][] = [
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
      phaseEvidence.domain,
    ],
    [
      "2",
      "Hydrology & scenarios",
      "Versioned JSON, all eight scenario families, soil and rainfall assumptions, upstream boundaries and boundary CSV intake.",
      "HEC-HMS / rain-on-grid hydrology requires a prepared, calibrated model. No runoff or routing is invented in the browser.",
      phaseEvidence.inflow,
    ],
    [
      "3",
      "Hydraulic model",
      "Preflight, scenario-bound prepared model inputs, isolated worker, HEC-RAS / LISFLOOD adapters and HDF inspection.",
      "Actual mesh, structures, boundary conditions and numerical checks must be reviewed before compute.",
      phaseEvidence.preflight,
    ],
    [
      "4",
      "Animation & validation",
      "Time-stamped raster playback, A/B on exact matching times, hydrographs, NSE/KGE, extent CSI/POD/FAR and report export.",
      "The 2022 Nowshera pilot must meet the documented skill targets against independent gauges and Sentinel-1 / UNOSAT.",
      results.some(
        (r) => r.scenario.outlet.station_id === PILOT_ID && r.validation_passed,
      ),
    ],
  ];
  const metrics: [string, number | null | undefined, number][] = [
    ["NSE", graph?.metrics.nse, targets.target_nse],
    ["KGE", graph?.metrics.kge, targets.target_kge],
    ["Extent CSI", result?.extent_validation?.csi, targets.target_csi],
  ];
  return (
    <section className="verification-view">
      <span className="eyebrow">PLAN COVERAGE / IMPLEMENTATION EVIDENCE</span>
      <h2>A picture must match the physics.</h2>
      <p className="muted">
        Each phase has a working software path and a separate scientific
        acceptance condition. A passing build does not validate a flood model.
      </p>
      <div className="verification-list">
        {phases.map(([number, title, implemented, remaining, ready]) => (
          <article key={number}>
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
        {metrics.map(([name, value, target]) => (
          <div key={name}>
            <span>{name}</span>
            <strong>{fmt(value)}</strong>
            <small>Target ≥ {String(target)}</small>
          </div>
        ))}
      </div>
      <p className="footnote">
        Targets are editable acceptance assumptions. Constant or missing
        observations produce undefined scores, never a fabricated pass.
      </p>
      <button className="secondary-button" onClick={onReport}>
        Export scenario & verification report ↗
      </button>
    </section>
  );
}
