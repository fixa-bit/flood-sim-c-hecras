import { upstreamOf } from "./network";
import { defaultScenarioFor } from "./scenarios";
import type { Scenario } from "./scenarios";
import { STATION_BY_ID } from "./stations";
import type { Station } from "./stations";

export type Example = {
  id: string;
  stationId: string;
  label: string;
  title: string;
  description: string;
  button: string;
};

/** The Nowshera pilot's examples; their ids are stable for saved drafts. */
export const EXAMPLE_SCENARIOS: Example[] = [
  {
    id: "example-nowshera-2022",
    stationId: "nowshera",
    label: "01 / HISTORICAL",
    title: "Nowshera 2022",
    description:
      "Kabul River baseline with Warsak and lower Swat gauge inputs, 20 Aug–5 Sep.",
    button: "Load Nowshera 2022",
  },
  {
    id: "example-nowshera-wetter-monsoon",
    stationId: "nowshera",
    label: "02 / WHAT IF",
    title: "Wetter monsoon +30%",
    description:
      "Explore the same river valley with 30% more rainfall and saturated soil.",
    button: "Load wetter monsoon",
  },
];

function wetter(station: Station): Example {
  return {
    id: `example-${station.id}-wetter-monsoon`,
    stationId: station.id,
    label: "02 / WHAT IF",
    title: "Wetter monsoon +30%",
    description: `Rain-on-grid sensitivity around ${station.name}: 30% more 2022 rainfall and saturated soil.`,
    button: "Load wetter monsoon",
  };
}

/** Examples for the selected station; none for a custom outlet. */
export function examplesFor(station: Station | undefined): Example[] {
  if (!station) return [];
  if (station.id === "nowshera") return EXAMPLE_SCENARIOS;
  if (station.id === "warsak")
    return [
      {
        id: "example-warsak-2022",
        stationId: "warsak",
        label: "01 / HISTORICAL",
        title: "Warsak 2022 below the dam",
        description:
          "Kabul River below Warsak Dam, 20 Aug–5 Sep, forced by the dam release. Waits for a continuous release record.",
        button: "Load Warsak 2022",
      },
      wetter(station),
    ];
  return [
    {
      id: `example-${station.id}-2022`,
      stationId: station.id,
      label: "01 / HISTORICAL",
      title: `${station.name} 2022`,
      description: `${station.riverName} River at ${station.name}, 2022 monsoon window 20 Aug–5 Sep. Planning setup; no hydraulic model is prepared here.`,
      button: `Load ${station.name} 2022`,
    },
    wetter(station),
  ];
}

export function exampleScenario(
  example: Example,
  demHash: string | null,
): Scenario {
  const station = STATION_BY_ID[example.stationId];
  const scenario = defaultScenarioFor(station);
  const wet = example.id.endsWith("-wetter-monsoon");
  scenario.id = example.id;
  scenario.domain.dem_sha256 = demHash;
  scenario.forcing.rainfall_product = "CHIRPS";
  scenario.provenance.purpose =
    "Editable R&D example scenario; hydraulic inputs and model review are required before compute.";
  scenario.provenance.sources.push(
    "https://www.ffc.gov.pk/",
    "https://www.chc.ucsb.edu/data/chirps",
  );
  if (station.id === "nowshera") {
    scenario.forcing.upstream_station_ids = ["warsak", "charsadda-road"];
  } else if (station.id === "warsak") {
    scenario.forcing.upstream_station_ids = ["warsak"];
  } else {
    scenario.forcing.upstream_station_ids = upstreamOf(station.id);
  }
  if (wet) {
    scenario.name = `Example · ${station.name} wetter monsoon +30%`;
    if (station.id === "nowshera")
      scenario.name = "Example · Wetter monsoon +30%";
    scenario.kind = "climate";
    scenario.forcing.mode = "rain_on_grid";
    scenario.forcing.rainfall_multiplier = 1.3;
    scenario.forcing.soil_moisture = "saturated";
    scenario.forcing.infiltration = "SCS-CN";
    scenario.provenance.notes =
      "Illustrative sensitivity experiment: multiply historical CHIRPS rainfall by 1.3 and assume saturated soil. This is not a forecast or assigned return period. Rainfall correction, runoff/infiltration parameters, all contributing boundaries and a separately prepared hydraulic model still require review.";
    return scenario;
  }
  scenario.time.start = "2022-08-20T01:00:00Z";
  scenario.time.end = "2022-09-05T01:00:00Z";
  scenario.forcing.soil_moisture = "normal";
  if (station.id === "nowshera") {
    scenario.name = "Example · Nowshera 2022";
    scenario.forcing.bias_correction =
      "Rainfall and soil moisture are unused in this gauge-driven setup. Supply reviewed Warsak, lower Swat at Charsadda Road, and remaining lateral inflows.";
    scenario.provenance.notes =
      "Matches the public upstream-routing study window. Daily gauge interpolation is exploratory, and the routing study failed its withheld KGE target. Complete boundary series, hydraulic geometry and independent flood validation remain required.";
  } else if (station.id === "warsak") {
    // Matches the prepared below-dam case in server/warsak.py.
    scenario.name = "Example · Warsak 2022 below the dam";
    scenario.hydraulics.engine = "LISFLOOD-FP";
    scenario.hydraulics.equations = "local inertial";
    scenario.validation.gauge_ids = [];
    scenario.forcing.bias_correction =
      "Gauge-driven: the Warsak Dam release is the only upstream boundary. Rainfall, infiltration and soil moisture are unused.";
    scenario.provenance.notes =
      "The reservoir above the dam is not modelled: its inflow from Afghanistan and the dam's gate operations are unavailable. The model starts about 4 km below the dam and is forced only by the Warsak release, which needs a continuous record (gaps of at most 3 hours) before it can run.";
  } else {
    scenario.name = `Example · ${station.name} 2022`;
    scenario.forcing.bias_correction =
      "Gauge-driven planning setup. Supply reviewed inflows for every upstream boundary.";
    scenario.provenance.notes = `Planning example for ${station.name}. No hydraulic model or inputs are prepared for this station yet; runs are limited to the Nowshera and Warsak sites.`;
  }
  return scenario;
}
