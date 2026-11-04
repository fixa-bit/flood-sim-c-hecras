import { STATION_BY_ID } from "../data/stations";
import type { Station } from "../data/stations";
import { applyPreset, KIND_LABELS, lakhToM3s } from "../data/scenarios";
import type { Scenario, ScenarioKind } from "../data/scenarios";
import type { Asset, Health } from "../lib/api";
import { ModelBindingForm } from "./ModelBindingForm";

type Props = {
  scenario: Scenario;
  station?: Station;
  assets: Record<string, Asset>;
  health: Health | null;
  boundaryIds: string[];
  busy: string;
  edit: (change: (next: Scenario) => void) => void;
  update: (next: Scenario) => void;
  onBind: (project: string, plan: string, review: string) => Promise<void>;
};

const boundaryName = (id: string) =>
  STATION_BY_ID[id]?.name ??
  (id === "charsadda-road"
    ? "Charsadda Road (Swat)"
    : id === "nowshera-hms"
      ? "Modeled Kabul inflow (HEC-HMS)"
      : id);

/** Editable scenario inputs. Every change goes through `edit` on a cloned draft. */
export function ScenarioFields({
  scenario,
  station,
  assets,
  health,
  boundaryIds,
  busy,
  edit,
  update,
  onBind,
}: Props) {
  return (
    <>
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
                s.forcing.mode = e.target.value as Scenario["forcing"]["mode"];
              })
            }
          >
            <option value="inflow_hydrograph">Gauge / HEC-HMS inflow</option>
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
                    station.limits[c as keyof typeof station.limits] !== null,
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
                  checked={scenario.forcing.upstream_station_ids.includes(id)}
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
                {boundaryName(id)}
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
        <p className="field-help">
          {scenario.hydraulics.engine === "HEC-RAS 2D"
            ? health?.runtimes.hec_ras && health?.runtimes.ras_commander
              ? "HEC-RAS runtime available. Load the runnable HEC-RAS case or attach your own prepared project."
              : "Install HEC-RAS and RAS Commander to run this engine."
            : health?.runtimes.lisflood_fp
              ? "LISFLOOD runtime available. Load the public case or attach a prepared ACC model."
              : "Configure a LISFLOOD-FP runtime to run this engine."}
        </p>
        <ModelBindingForm
          key={scenario.hydraulics.engine}
          engine={scenario.hydraulics.engine}
          disabled={!health || !!busy}
          onBind={onBind}
        />
        <label>
          Manning roughness source
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
            <option>Prepared model</option>
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
                  {["barrage", "levee", "reservoir", "breach"].map((type) => (
                    <option key={type}>{type}</option>
                  ))}
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
                    s.hydraulics.structures[i].specification = e.target.value;
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
    </>
  );
}
