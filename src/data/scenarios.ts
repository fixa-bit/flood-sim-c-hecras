import type { Station } from "./stations";

export type ScenarioKind =
  | "historical"
  | "ffd_class"
  | "design_storm"
  | "soil_state"
  | "reservoir_release"
  | "breach"
  | "land_cover"
  | "climate";
export type Scenario = {
  schema_version: 1;
  id: string;
  name: string;
  kind: ScenarioKind;
  outlet: {
    station_id: string | null;
    lat: number;
    lon: number;
    crs: "EPSG:4326";
  };
  domain: {
    radius_km: number;
    mesh_m: number;
    model_crs: "EPSG:32642" | "EPSG:32643";
    dem_source: "FABDEM";
    dem_sha256: string | null;
  };
  time: { start: string; end: string; output_interval_minutes: number };
  forcing: {
    mode: "inflow_hydrograph" | "rain_on_grid";
    rainfall_product: "GPM IMERG" | "CHIRPS" | "PMD gauges" | "design storm";
    rainfall_multiplier: number;
    design_storm_mm: number | null;
    return_period_years: number | null;
    bias_correction: string;
    soil_moisture: "dry" | "normal" | "saturated" | "SMAP";
    infiltration: "Green-Ampt" | "SCS-CN";
    inflow_asset: string | null;
    upstream_station_ids: string[];
    ffd_class: "low" | "medium" | "high" | "veryHigh" | "exceptional" | null;
  };
  hydraulics: {
    engine: "HEC-RAS 2D" | "LISFLOOD-FP";
    equations: "full SWE" | "local inertial";
    manning_source: "ESA WorldCover" | "Dynamic World" | "Prepared model";
    structures: {
      type: "barrage" | "levee" | "reservoir" | "breach";
      name: string;
      specification: string;
    }[];
  };
  validation: {
    gauge_ids: string[];
    extent_source: "Sentinel-1" | "UNOSAT";
    target_nse: number;
    target_kge: number;
    target_csi: number;
  };
  provenance: {
    created_at: string;
    purpose: string;
    notes: string;
    sources: string[];
  };
};
export const KIND_LABELS: Record<ScenarioKind, string> = {
  historical: "2022 historical replay",
  ffd_class: "FFD discharge class",
  design_storm: "Return-period rainfall",
  soil_state: "Saturated soil",
  reservoir_release: "Reservoir release",
  breach: "Embankment breach",
  land_cover: "Land-cover change",
  climate: "Climate rainfall multiplier",
};
export function defaultScenarioFor(station: Station): Scenario {
  return {
    schema_version: 1,
    id: `${station.id}-2022`,
    name: `2022 monsoon · ${station.name}`,
    kind: "historical",
    outlet: {
      station_id: station.id,
      lat: station.lat,
      lon: station.lon,
      crs: "EPSG:4326",
    },
    domain: {
      radius_km: 20,
      mesh_m: 100,
      model_crs: station.lon < 72 ? "EPSG:32642" : "EPSG:32643",
      dem_source: "FABDEM",
      dem_sha256: null,
    },
    time: {
      start: "2022-08-20T00:00:00Z",
      end: "2022-09-05T00:00:00Z",
      output_interval_minutes: 60,
    },
    forcing: {
      mode: "inflow_hydrograph",
      rainfall_product: "GPM IMERG",
      rainfall_multiplier: 1,
      design_storm_mm: null,
      return_period_years: null,
      bias_correction: "",
      soil_moisture: "SMAP",
      infiltration: "Green-Ampt",
      inflow_asset: null,
      upstream_station_ids: station.id === "nowshera" ? ["warsak"] : [],
      ffd_class: null,
    },
    hydraulics: {
      engine: "HEC-RAS 2D",
      equations: "full SWE",
      manning_source: "ESA WorldCover",
      structures: [],
    },
    validation: {
      gauge_ids: [station.id],
      extent_source: "Sentinel-1",
      target_nse: 0.65,
      target_kge: 0.6,
      target_csi: 0.5,
    },
    provenance: {
      created_at: new Date().toISOString(),
      purpose:
        "R&D scenario; requires prepared inputs and independent validation.",
      notes:
        "Historical window only. No observed discharge or modeled inundation is bundled. Warsak alone does not represent all Kabul/Swat tributary inflow.",
      sources: [
        "https://ffd.pmd.gov.pk/flood-limits",
        "https://global-hydrodynamics.github.io/MERIT_Hydro/",
      ],
    },
  };
}
export function applyPreset(base: Scenario, kind: ScenarioKind): Scenario {
  const next = structuredClone(base);
  next.kind = kind;
  next.name = `${KIND_LABELS[kind]} · ${base.outlet.station_id ?? "custom outlet"}`;
  next.forcing.ffd_class = kind === "ffd_class" ? "high" : null;
  next.forcing.rainfall_multiplier = kind === "climate" ? 1.3 : 1;
  next.forcing.soil_moisture = kind === "soil_state" ? "saturated" : "SMAP";
  next.forcing.rainfall_product =
    kind === "design_storm" ? "design storm" : "GPM IMERG";
  next.forcing.design_storm_mm = kind === "design_storm" ? 150 : null;
  next.forcing.return_period_years = kind === "design_storm" ? 100 : null;
  next.hydraulics.structures =
    kind === "breach"
      ? [{ type: "breach", name: "Proposed breach", specification: "" }]
      : kind === "reservoir_release"
        ? [{ type: "reservoir", name: "Upstream release", specification: "" }]
        : [];
  next.provenance.notes =
    kind === "design_storm"
      ? "150 mm is an editable design assumption. A 100-year label requires a sourced, local IDF analysis."
      : kind === "ffd_class"
        ? "A discharge threshold is a boundary target; it does not define a hydrograph, water level, or flood extent."
        : base.provenance.notes;
  return next;
}
export function scenarioErrors(s: Scenario): string[] {
  const errors: string[] = [];
  if (!s.name?.trim()) errors.push("Give the scenario a name.");
  if (
    !Number.isFinite(s.outlet.lat) ||
    s.outlet.lat < 23 ||
    s.outlet.lat > 38 ||
    !Number.isFinite(s.outlet.lon) ||
    s.outlet.lon < 60 ||
    s.outlet.lon > 80
  )
    errors.push(
      "Outlet must be in the Pakistan study region (23–38°N, 60–80°E).",
    );
  if (!(s.domain.radius_km >= 1 && s.domain.radius_km <= 50))
    errors.push("Domain radius must be 1–50 km.");
  if (!(s.domain.mesh_m >= 10 && s.domain.mesh_m <= 1000))
    errors.push("Mesh size must be 10–1,000 m.");
  const start = Date.parse(s.time.start),
    end = Date.parse(s.time.end);
  if (
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    end <= start ||
    end - start > 93 * 86400000
  )
    errors.push("Choose an increasing time window of at most 93 days.");
  if (!(
    s.time.output_interval_minutes >= 1 &&
    s.time.output_interval_minutes <= 1440
  ))
    errors.push("Output interval must be 1–1,440 minutes.");
  if (!(
    s.forcing.rainfall_multiplier > 0 && s.forcing.rainfall_multiplier <= 5
  ))
    errors.push("Rainfall multiplier must be greater than 0 and at most 5.");
  if (s.kind === "design_storm" && !(s.forcing.design_storm_mm! > 0))
    errors.push("Enter a positive design-storm depth.");
  if (
    s.domain.dem_sha256 !== null &&
    !/^[a-f0-9]{64}$/.test(s.domain.dem_sha256)
  )
    errors.push("DEM hash must be a SHA-256 digest.");
  return errors;
}
export const lakhToM3s = (lakh: number) => lakh * 100000 * 0.028316846592;
export const boundsFor = (s: Scenario): [number, number, number, number] => {
  const dy = s.domain.radius_km / 111.32;
  const dx = dy / Math.cos((s.outlet.lat * Math.PI) / 180);
  return [
    s.outlet.lon - dx,
    s.outlet.lat - dy,
    s.outlet.lon + dx,
    s.outlet.lat + dy,
  ];
};
