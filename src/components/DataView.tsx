import { SOURCES } from "../data/sources";
import type { Asset, Health } from "../lib/api";
import { StudyPanel } from "./StudyPanel";

type Props = {
  health: Health | null;
  assets: Record<string, Asset>;
  onRefresh: () => void;
};

export function DataView({ health, assets, onRefresh }: Props) {
  return (
    <section className="data-view">
      <div className="section-title">
        <h2>Data with a traceable origin</h2>
        <button className="small-button" onClick={onRefresh}>
          ↻ Refresh assets
        </button>
      </div>
      <p className="muted">
        Clip one bounded hydraulic domain. Prepare hydrology over the full
        contributing catchment. Every registered input retains its source,
        license and SHA-256.
      </p>
      <div className="runtime-grid">
        {(
          [
            ["HEC-RAS", health?.runtimes.hec_ras],
            ["RAS Commander", health?.runtimes.ras_commander],
            ["HEC-HMS", health?.runtimes.hec_hms],
            ["LISFLOOD-FP", health?.runtimes.lisflood_fp],
          ] as const
        ).map(([name, ready]) => (
          <div key={name}>
            <span className={ready ? "ready-text" : "muted"}>●</span>
            <strong>{name}</strong>
            <small>
              {ready ? "Installed" : health ? "Not detected" : "Service offline"}
            </small>
          </div>
        ))}
      </div>
      <div className="source-list">
        {SOURCES.map((source) => {
          const asset = assets[source.key];
          return (
            <article key={source.key}>
              <div>
                <span className={`source-state ${asset ? "available" : ""}`}>
                  {asset ? "REGISTERED" : "REQUIRED INPUT"}
                </span>
                <h3>{source.name}</h3>
                <a
                  href={
                    asset?.source.startsWith("https://")
                      ? asset.source
                      : source.href
                  }
                  target="_blank"
                  rel="noreferrer"
                >
                  {asset?.product ?? source.product} ↗
                </a>
                <p>{asset?.license ?? source.license}</p>
                {asset?.acquisition?.notes && <p>{asset.acquisition.notes}</p>}
                <small>Fallback: {source.fallback}</small>
                {asset && (
                  <code title={asset.sha256}>
                    SHA-256 {asset.sha256.slice(0, 24)}…
                  </code>
                )}
              </div>
            </article>
          );
        })}
      </div>
      <StudyPanel />
      <div className="inline-note">
        Register downloaded inputs using{" "}
        <code>python -m server.cli register --help</code>. Public STAC COG
        clipping is available through <code>stac-import</code>. The README
        documents file formats and the model handoff.
      </div>
    </section>
  );
}
