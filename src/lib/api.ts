import type { Scenario } from "../data/scenarios";
import type { Legend } from "./legend";

export type Overlay = {
  url: string;
  bounds: [number, number, number, number];
  raster_url?: string;
};
export type Result = {
  id: string;
  scenario: Scenario;
  scenario_sha256: string;
  engine: string;
  terrain_sha256: string;
  validation_status: string;
  validation_passed: boolean;
  vertical_datum: string;
  /** Overlay class edges; absent on results published before per-result legends. */
  legend?: Partial<Legend>;
  frames: {
    time: string;
    fields: { depth: Overlay; wse?: Overlay; velocity?: Overlay };
  }[];
  hydrographs: Hydrograph[];
  extent_validation: {
    csi: number | null;
    pod: number | null;
    far: number | null;
    time: string;
    source: string;
    overlay?: Overlay;
  } | null;
};
/** `/api/results` listing entry; fetch `/api/results/{id}` for frames and hydrographs. */
export type ResultSummary = Omit<Result, "frames" | "hydrographs"> & {
  frame_count: number;
};
export type Hydrograph = {
  station_id: string;
  samples: {
    time: string;
    observed_m3s: number | null;
    simulated_m3s: number | null;
    lower_m3s?: number;
    upper_m3s?: number;
  }[];
  metrics: {
    pairs: number;
    nse: number | null;
    kge: number | null;
    rmse_m3s: number | null;
  };
};
export type Asset = {
  sha256: string;
  source: string;
  license: string;
  product: string;
  acquisition?: { notes?: string };
};
export type PreparedCase = {
  label: string;
  scenario: Scenario;
  limitations: string[];
  ready: boolean;
};
export type Preflight = {
  ready: boolean;
  scenario_sha256: string;
  checks: { key: string; passed: boolean; detail: string }[];
};
export type DomainResult = {
  scenario_sha256: string;
  bounds: number[];
  snapped_outlet: { lat: number; lon: number; distance_m: number };
  clips: Record<string, { sha256: string }>;
  catchment_status: string;
  catchment: object | null;
};
/** `/api/exposure`: context layers that never enter a hydraulic model. */
export type ExposureLayers = {
  population?: {
    product: string;
    license: string;
    source: string;
    total_population: number;
    density_edges_per_km2: number[];
    overlay: Overlay;
    notes: string;
  };
  facilities?: {
    product: string;
    license: string;
    osm_timestamp: string | null;
    count: number;
    counts: Record<string, number>;
    notes: string;
  };
};
export type Facility = {
  id: string;
  kind: "health" | "education" | "emergency";
  amenity: string;
  name: string | null;
  coordinates: [number, number];
  max_depth_m: number;
  max_time: string;
  first_flooded_time: string | null;
  /** Depth at the facility per frame; omitted when it never exceeds 5 cm. */
  depth_m?: number[];
};
export type Exposure =
  | { available: false; reason: string }
  | {
      available: true;
      result_id: string;
      thresholds_m: number[];
      facility_flood_m: number;
      population_in_extent: number;
      population_excluded_start_wet: number;
      /** `danger`: residents at hazard rating >= 0.75, when the result publishes speed. */
      frames: { time: string; people: number[]; danger?: number }[];
      hazard?: {
        rating: string;
        danger_threshold: number;
        source: string;
      } | null;
      excluded_baseline?: string;
      peak: { time: string; people: number[] };
      facilities: {
        in_extent: number;
        ever_flooded: number;
        items: Facility[];
      };
      inputs: {
        population_product: string;
        facilities_osm_timestamp: string | null;
      };
      columns?: { count: number; cell_deg: number; url: string };
      method: string;
      notes: string;
    };
/** Residents per flooded-frame series, trimmed of leading and trailing zeros. */
export type ColumnSeries = { from: number; people: number[] } | null;
export type PopulationColumn = {
  /** [west, south, east, north] in degrees. */
  bounds: [number, number, number, number];
  people: number;
  /** Viewer-terrain base height; absent when no local terrain is registered. */
  ground_m?: number;
  /** One series per exposure threshold; absent when the column never floods. */
  flooded?: ColumnSeries[];
};
/** `/api/results/{id}/exposure/columns`: residents aggregated for 3D display. */
export type PopulationColumns =
  | { available: false; reason: string }
  | {
      available: true;
      cell_deg: number;
      frames: number;
      thresholds_m: number[];
      ground_source: string | null;
      columns: PopulationColumn[];
    };
export type Tributary = {
  hyriv_id: number;
  name: string | null;
  upland_km2: number;
  mean_discharge_m3s: number;
  strahler_order: number;
  edge: string;
  crossing: [number, number];
  joins: [number, number];
  downstream_of_gauge: boolean | null;
  represented: boolean;
  boundary: string | null;
  significance: "major" | "minor";
  geometry: object;
  reference_observation: {
    river: string;
    location: string;
    report_date: string;
    max_discharge_cusecs: number;
    max_discharge_m3s: number;
    reports: number;
    source: string;
    status: string;
  } | null;
};
export type TributaryAudit =
  | { available: false; reason: string }
  | {
      available: true;
      engine: string;
      entering: Tributary[];
      summary: {
        entering: number;
        represented: number;
        unrepresented: number;
        unrepresented_major: string[];
        unrepresented_upland_km2: number;
        main_inflow_upland_km2: number | null;
      };
      method: string;
    };

export type Health = {
  status: string;
  runtimes: {
    hec_ras: boolean;
    ras_commander: boolean;
    hec_hms: boolean;
    lisflood_fp: boolean;
  };
};

/** Thrown when the caller aborts a request; work already started on the server may still finish. */
export class CancelledError extends Error {
  constructor() {
    super(
      "Cancelled. The local service may still finish work it had already started; check readiness again before running.",
    );
    this.name = "CancelledError";
  }
}

export async function api<T>(
  path: string,
  body?: unknown,
  options: { signal?: AbortSignal } = {},
): Promise<T> {
  let response: Response;
  let raw: string;
  try {
    response = await fetch(
      `/api/${path}`,
      body === undefined
        ? { signal: options.signal }
        : {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
            signal: options.signal,
          },
    );
    raw = await response.text();
  } catch (error) {
    if (options.signal?.aborted) throw new CancelledError();
    throw new Error(
      "Local data service is unavailable. Start the Python service on port 8010.",
      { cause: error },
    );
  }
  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    throw new Error(
      "Local data service is unavailable. Start the Python service on port 8010.",
    );
  }
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map((item: { msg: string; loc?: (string | number)[] }) => {
                const path = item.loc
                  ?.filter((part) => part !== "body")
                  .join(".");
                return path ? `${path}: ${item.msg}` : item.msg;
              })
              .join("; ")
          : "Request could not be completed. Check the preparation requirements.",
    );
  }
  return data as T;
}

export function download(
  name: string,
  data: unknown,
  type = "application/json",
) {
  const url = URL.createObjectURL(
    new Blob(
      [typeof data === "string" ? data : JSON.stringify(data, null, 2)],
      { type },
    ),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 500);
}
