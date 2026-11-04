import type { Station } from "../data/stations";
import { stationNames } from "../data/network";

type Props = { station?: Station; upstream: string[]; downstream: string[] };

export function NetworkSummary({ station, upstream, downstream }: Props) {
  return (
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
            {downstream.length} connected stations · no travel time assumed
          </small>
        </div>
      </div>
      <p className="footnote">
        Connectivity is a schematic. Flow timing, reservoir operations and
        tributary contributions come from a calibrated routing or hydraulic
        model.
      </p>
    </section>
  );
}
