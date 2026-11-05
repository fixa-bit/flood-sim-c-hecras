import { useState } from "react";
import { STATIONS } from "../data/stations";
import { PILOT_ID, SITE_NOTES, STARTING_STATIONS } from "../data/network";

const rank = (id: string) =>
  STARTING_STATIONS.indexOf(id) < 0 ? 100 : STARTING_STATIONS.indexOf(id);

type Props = {
  stationId: string;
  connected: boolean;
  onSelect: (id: string) => void;
  onCustom: () => void;
  onRefresh: () => void;
};

export function StationCatalog({
  stationId,
  connected,
  onSelect,
  onCustom,
  onRefresh,
}: Props) {
  const [query, setQuery] = useState("");
  const [allStations, setAllStations] = useState(false);
  const visibleStations = STATIONS.filter(
    (s) =>
      (allStations || STARTING_STATIONS.includes(s.id)) &&
      `${s.name} ${s.riverName}`.toLowerCase().includes(query.toLowerCase()),
  ).sort((a, b) => rank(a.id) - rank(b.id));

  return (
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
            onClick={() => onSelect(s.id)}
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
            ) : SITE_NOTES[s.id] ? (
              <span className="pilot-badge site-badge" title={SITE_NOTES[s.id]}>
                PREPARED
              </span>
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
      <button className="custom-button" onClick={onCustom}>
        ＋ Custom lat / long or gauge
      </button>
      <div className="pilot-note">
        <span className="eyebrow">FIRST PROOF</span>
        <strong>Nowshera · August 2022</strong>
        <p>
          Warsak → Nowshera → Attock
          <br />
          Upstream boundaries first. Expand hydraulic runs after the pilot is
          validated.
        </p>
      </div>
      <div className="service-status">
        <i className={connected ? "online" : ""} />
        <span>
          {connected
            ? "Local data service connected"
            : "Local data service offline"}
        </span>
        <button title="Refresh service and data" onClick={onRefresh}>
          ↻
        </button>
      </div>
    </aside>
  );
}
