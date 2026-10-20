import type { Station } from "./stations";

export type SoilState = "dry" | "normal" | "saturated" | "observed";
export type RainfallSource =
  | "open-meteo-archive"
  | "open-meteo-forecast"
  | "design";
export type FfdClass = "low" | "medium" | "high" | "veryHigh" | "exceptional";
export type ScenarioKind =
  | "historical"
  | "ffd_class"
  | "design_storm"
  | "soil_state";

export type Scenario = {
  id: string;
  name: string;
  stationId: string;
  kind: ScenarioKind;
  startDate: string;
  endDate: string;
  soilState: SoilState;
  rainfallSource: RainfallSource;
  rainfallMultiplier: number;
  ffdClass: FfdClass | null;
  designStormMm: number | null;
  notes: string;
  engine: "geometric-screening";
};

export function defaultScenarioFor(station: Station): Scenario {
  if (station.id === "sukkur" || station.river === "indus") {
    return {
      id: "hist-2022-monsoon",
      name: "2022 monsoon replay",
      stationId: station.id,
      kind: "historical",
      startDate: "2022-08-10",
      endDate: "2022-09-10",
      soilState: "observed",
      rainfallSource: "open-meteo-archive",
      rainfallMultiplier: 1,
      ffdClass: null,
      designStormMm: null,
      notes:
        "Historical window covering the 2022 Indus super-flood. Rainfall and soil moisture from Open-Meteo ERA5-Land reanalysis. Inundation is geometric screening on Cesium terrain, not HEC-RAS.",
      engine: "geometric-screening",
    };
  }
  if (station.id === "nowshera") {
    return {
      id: "hist-2022-kabul",
      name: "2022 Kabul catchment rains",
      stationId: station.id,
      kind: "historical",
      startDate: "2022-08-20",
      endDate: "2022-09-05",
      soilState: "observed",
      rainfallSource: "open-meteo-archive",
      rainfallMultiplier: 1,
      ffdClass: null,
      designStormMm: null,
      notes:
        "Nowshera / Kabul River window during the 2022 monsoon. Screening hydrology only.",
      engine: "geometric-screening",
    };
  }
  return {
    id: "forecast-14d",
    name: "14-day observed + forecast",
    stationId: station.id,
    kind: "historical",
    startDate: "",
    endDate: "",
    soilState: "observed",
    rainfallSource: "open-meteo-forecast",
    rainfallMultiplier: 1,
    ffdClass: null,
    designStormMm: null,
    notes:
      "Open-Meteo past 7 days plus 7-day forecast. Use for live-ish what-if, not official FFD warning.",
    engine: "geometric-screening",
  };
}

export function scenarioCatalog(station: Station): Scenario[] {
  const hist = defaultScenarioFor(station);
  return [
    hist,
    {
      id: "ffd-high",
      name: "FFD High flood at station",
      stationId: station.id,
      kind: "ffd_class",
      startDate: hist.startDate,
      endDate: hist.endDate,
      soilState: "saturated",
      rainfallSource: hist.rainfallSource,
      rainfallMultiplier: 1,
      ffdClass: "high",
      designStormMm: null,
      notes:
        "Forces screening water surface from the FFD High flood discharge class for this station.",
      engine: "geometric-screening",
    },
    {
      id: "ffd-exceptional",
      name: "FFD Exceptional / Very High",
      stationId: station.id,
      kind: "ffd_class",
      startDate: hist.startDate,
      endDate: hist.endDate,
      soilState: "saturated",
      rainfallSource: hist.rainfallSource,
      rainfallMultiplier: 1,
      ffdClass: station.limits.exceptional != null ? "exceptional" : "veryHigh",
      designStormMm: null,
      notes: "Upper FFD class. Geometric bathtub on sampled DEM.",
      engine: "geometric-screening",
    },
    {
      id: "saturated-1.3x",
      name: "Saturated soil + 1.3× rain",
      stationId: station.id,
      kind: "soil_state",
      startDate: hist.startDate,
      endDate: hist.endDate,
      soilState: "saturated",
      rainfallSource: hist.rainfallSource,
      rainfallMultiplier: 1.3,
      ffdClass: null,
      designStormMm: null,
      notes:
        "Antecedent moisture set to saturated; rainfall scaled 30%. Tests runoff sensitivity.",
      engine: "geometric-screening",
    },
    {
      id: "design-150",
      name: "150 mm design burst",
      stationId: station.id,
      kind: "design_storm",
      startDate: hist.startDate || "2022-08-15",
      endDate: hist.endDate || "2022-08-18",
      soilState: "normal",
      rainfallSource: "design",
      rainfallMultiplier: 1,
      ffdClass: null,
      designStormMm: 150,
      notes: "Synthetic 150 mm / 24 h burst in the station domain.",
      engine: "geometric-screening",
    },
  ];
}
