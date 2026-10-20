import { defaultScenarioFor } from "./scenarios";
import type { Scenario } from "./scenarios";
import { STATION_BY_ID } from "./stations";

export const EXAMPLE_SCENARIOS = [
  {
    id: "example-nowshera-2022",
    label: "01 / HISTORICAL",
    title: "Nowshera 2022",
    description:
      "Kabul River baseline with Warsak and lower Swat gauge inputs, 20 Aug–5 Sep.",
    button: "Load Nowshera 2022",
  },
  {
    id: "example-nowshera-wetter-monsoon",
    label: "02 / WHAT IF",
    title: "Wetter monsoon +30%",
    description:
      "Explore the same river valley with 30% more rainfall and saturated soil.",
    button: "Load wetter monsoon",
  },
] as const;

export type ExampleId = (typeof EXAMPLE_SCENARIOS)[number]["id"];

export function exampleScenario(
  id: ExampleId,
  demHash: string | null,
): Scenario {
  const scenario = defaultScenarioFor(STATION_BY_ID.nowshera);
  scenario.id = id;
  scenario.domain.dem_sha256 = demHash;
  scenario.forcing.rainfall_product = "CHIRPS";
  scenario.forcing.upstream_station_ids = ["warsak", "charsadda-road"];
  scenario.provenance.purpose =
    "Editable R&D example scenario; hydraulic inputs and model review are required before compute.";
  scenario.provenance.sources.push(
    "https://www.ffc.gov.pk/",
    "https://www.chc.ucsb.edu/data/chirps",
  );
  if (id === "example-nowshera-2022") {
    scenario.name = "Example · Nowshera 2022";
    scenario.time.start = "2022-08-20T01:00:00Z";
    scenario.time.end = "2022-09-05T01:00:00Z";
    scenario.forcing.soil_moisture = "normal";
    scenario.forcing.bias_correction =
      "Rainfall and soil moisture are unused in this gauge-driven setup. Supply reviewed Warsak, lower Swat at Charsadda Road, and remaining lateral inflows.";
    scenario.provenance.notes =
      "Matches the public upstream-routing study window. Daily gauge interpolation is exploratory, and the routing study failed its withheld KGE target. Complete boundary series, hydraulic geometry and independent flood validation remain required.";
  } else {
    scenario.name = "Example · Wetter monsoon +30%";
    scenario.kind = "climate";
    scenario.forcing.mode = "rain_on_grid";
    scenario.forcing.rainfall_multiplier = 1.3;
    scenario.forcing.soil_moisture = "saturated";
    scenario.forcing.infiltration = "SCS-CN";
    scenario.provenance.notes =
      "Illustrative sensitivity experiment: multiply historical CHIRPS rainfall by 1.3 and assume saturated soil. This is not a forecast or assigned return period. Rainfall correction, runoff/infiltration parameters, all contributing boundaries and a separately prepared hydraulic model still require review.";
  }
  return scenario;
}
