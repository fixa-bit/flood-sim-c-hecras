import type { Scenario } from "../data/scenarios";

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
export type Health = {
  status: string;
  runtimes: {
    hec_ras: boolean;
    ras_commander: boolean;
    hec_hms: boolean;
    lisflood_fp: boolean;
  };
};

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(
    `/api/${path}`,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const raw = await response.text();
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
