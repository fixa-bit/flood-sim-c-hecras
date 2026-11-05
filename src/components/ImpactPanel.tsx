import type { ReactNode } from "react";
import type {
  Exposure,
  ExposureLayers,
  Facility,
  TributaryAudit,
} from "../lib/api";
import { facilityDepth } from "../lib/exposure";

const people = (n: number) =>
  n < 100
    ? String(n)
    : `≈ ${(Math.round(n / 100) * 100).toLocaleString("en-US")}`;
const utc = (time: string) => `${time.slice(0, 16).replace("T", " ")} UTC`;
const KIND_LABEL: Record<Facility["kind"], string> = {
  health: "Health",
  education: "School",
  emergency: "Emergency",
};

export function ImpactPanel({
  exposure,
  tributaries,
  layers,
  frameIndex,
}: {
  exposure?: Exposure;
  tributaries?: TributaryAudit;
  layers: ExposureLayers;
  frameIndex: number;
}) {
  return (
    <section className="impact-section" aria-label="Impact and tributaries">
      <div className="impact-part">
        <div className="section-title">
          <h2>Exposure at this model time</h2>
          <span>MODEL-DERIVED · NOT A CASUALTY ESTIMATE</span>
        </div>
        {!exposure ? (
          <p className="footnote">Loading exposure…</p>
        ) : !exposure.available ? (
          <p className="footnote">{exposure.reason}</p>
        ) : (
          <ExposureSummary exposure={exposure} frameIndex={frameIndex} />
        )}
        {layers.population && (
          <Notes summary="Sources">
            Population: {layers.population.product} ({layers.population.license}
            ).
            {layers.facilities &&
              ` Facilities: ${layers.facilities.count} mapped in OpenStreetMap (${layers.facilities.license}); volunteered mapping is incomplete.`}
          </Notes>
        )}
      </div>
      <div className="impact-part">
        <div className="section-title impact-subtitle">
          <h2>Streams entering the model</h2>
          <span>HYDRORIVERS × MODEL INFLOW BOUNDARIES</span>
        </div>
        {!tributaries ? (
          <p className="footnote">Loading tributary audit…</p>
        ) : !tributaries.available ? (
          <p className="footnote">{tributaries.reason}</p>
        ) : (
          <TributaryTable audit={tributaries} />
        )}
      </div>
    </section>
  );
}

function ExposureSummary({
  exposure,
  frameIndex,
}: {
  exposure: Extract<Exposure, { available: true }>;
  frameIndex: number;
}) {
  const now = exposure.frames[frameIndex];
  const [shallow, deep] = exposure.thresholds_m;
  const floodedNow = exposure.facilities.items.filter(
    (item) => facilityDepth(item, frameIndex) >= exposure.facility_flood_m,
  );
  return (
    <>
      <div className="impact-cards">
        <div>
          <span>RESIDENTS IN WATER ≥ {shallow} M</span>
          <strong>{now ? people(now.people[0]) : "—"}</strong>
          <small
            title={
              exposure.hazard
                ? `Dangerous water: hazard rating ${exposure.hazard.rating} ≥ ${exposure.hazard.danger_threshold} (${exposure.hazard.source})`
                : undefined
            }
          >
            {now ? `${people(now.people[1])} in ≥ ${deep} m` : "No depth frame"}
            {now?.danger !== undefined &&
              ` · ${people(now.danger)} in dangerous water`}
          </small>
        </div>
        <div>
          <span>EVENT PEAK</span>
          <strong>{people(exposure.peak.people[0])}</strong>
          <small>{utc(exposure.peak.time)}</small>
        </div>
        <div>
          <span>FACILITIES ≥ {exposure.facility_flood_m} M</span>
          <strong>
            {floodedNow.length} / {exposure.facilities.in_extent}
          </strong>
          <small>{exposure.facilities.ever_flooded} flooded at some time</small>
        </div>
      </div>
      {floodedNow.length > 0 && (
        <ul className="facility-list" aria-label="Facilities flooded now">
          {floodedNow.slice(0, 6).map((item) => (
            <li key={item.id}>
              <i className={`facility-dot ${item.kind}`} />
              {item.name ?? `Unnamed ${item.amenity}`}
              <span>
                {KIND_LABEL[item.kind]} ·{" "}
                {facilityDepth(item, frameIndex).toFixed(2)} m
              </span>
            </li>
          ))}
          {floodedNow.length > 6 && <li>+{floodedNow.length - 6} more</li>}
        </ul>
      )}
      <Notes summary="How these counts are made">
        {exposure.population_in_extent.toLocaleString("en-US")} residents live
        in the model raster;{" "}
        {exposure.population_excluded_start_wet.toLocaleString("en-US")} in{" "}
        {exposure.excluded_baseline === undefined ||
        exposure.excluded_baseline === "cells wet in the first published frame"
          ? "cells already wet at the first frame"
          : `the ${exposure.excluded_baseline}`}{" "}
        are excluded. {exposure.method} {exposure.notes}
        {exposure.hazard &&
          ` Dangerous water: hazard rating ${exposure.hazard.rating} ≥ ${exposure.hazard.danger_threshold} (${exposure.hazard.source}).`}
      </Notes>
    </>
  );
}

function TributaryTable({
  audit,
}: {
  audit: Extract<TributaryAudit, { available: true }>;
}) {
  const major = audit.entering.filter((item) => item.significance === "major");
  const minor = audit.entering.filter((item) => item.significance === "minor");
  const missingMinor = minor.filter((item) => !item.represented);
  return (
    <>
      {major
        .filter((item) => !item.represented)
        .map((item) => (
          <p className="tributary-alert" role="note" key={item.hyriv_id}>
            <strong>
              {item.name ?? `HydroRIVERS ${item.hyriv_id}`} receives no water in
              this model.
            </strong>{" "}
            It drains {Math.round(item.upland_km2).toLocaleString("en-US")} km²,
            enters from the {item.edge}
            {item.downstream_of_gauge
              ? " and joins the main river downstream of the Nowshera gauge line, so gauge scores cannot reveal its absence"
              : ""}
            .{" "}
            {item.reference_observation &&
              `PDMA reported up to ${Math.round(item.reference_observation.max_discharge_m3s).toLocaleString("en-US")} m³/s at ${item.reference_observation.location} (${item.reference_observation.report_date}; untimed daily value, reference only). `}
            Flooding below the confluence may be underestimated.
          </p>
        ))}
      <table className="tributary-table">
        <thead>
          <tr>
            <th>Stream</th>
            <th>Drains</th>
            <th>Long-term mean</th>
            <th>Enters</th>
            <th>In this model</th>
          </tr>
        </thead>
        <tbody>
          {major.map((item) => (
            <tr
              key={item.hyriv_id}
              className={item.represented ? "" : "missing"}
            >
              <td>{item.name ?? `HydroRIVERS ${item.hyriv_id}`}</td>
              <td>{Math.round(item.upland_km2).toLocaleString("en-US")} km²</td>
              <td>{item.mean_discharge_m3s.toFixed(1)} m³/s</td>
              <td>{item.edge}</td>
              <td>
                {item.represented ? `Inflow: ${item.boundary}` : "No inflow"}
              </td>
            </tr>
          ))}
          {minor.length > 0 && (
            <tr className={missingMinor.length ? "missing" : ""}>
              <td>{minor.length} minor local streams</td>
              <td>
                {Math.round(Math.min(...minor.map((m) => m.upland_km2)))}–
                {Math.round(Math.max(...minor.map((m) => m.upland_km2)))} km²
                each
              </td>
              <td>
                {minor
                  .reduce((sum, m) => sum + m.mean_discharge_m3s, 0)
                  .toFixed(1)}{" "}
                m³/s total
              </td>
              <td>{[...new Set(minor.map((m) => m.edge))].join(", ")}</td>
              <td>
                {missingMinor.length === minor.length
                  ? "No inflow"
                  : `${minor.length - missingMinor.length} fed`}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <Notes summary="How streams are checked">{audit.method}</Notes>
    </>
  );
}

/** Long method and source text, folded so the live panels stay compact. */
function Notes({
  summary,
  children,
}: {
  summary: string;
  children: ReactNode;
}) {
  return (
    <details className="impact-notes">
      <summary>{summary}</summary>
      <p className="footnote">{children}</p>
    </details>
  );
}
