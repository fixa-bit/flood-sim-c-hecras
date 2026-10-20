import { STATION_BY_ID } from "./stations";

// Planning topology, not channel geometry or calibrated routing.
// No travel times or downstream discharge are inferred here.
export const DOWNSTREAM: Record<string, string[]> = {
  warsak: ["nowshera"],
  nowshera: ["attock"],
  tarbela: ["attock"],
  attock: ["kalabagh"],
  kalabagh: ["chashma"],
  chashma: ["taunsa"],
  taunsa: ["guddu"],
  guddu: ["sukkur"],
  sukkur: ["kotri"],
  kotri: [],
  kohala: ["mangla"],
  mangla: ["rasul"],
  rasul: ["trimmu"],
  "jammu-tawi": ["marala"],
  akhnur: ["marala"],
  marala: ["khanki"],
  khanki: ["qadirabad"],
  qadirabad: ["chiniot"],
  chiniot: ["trimmu"],
  trimmu: ["panjnad"],
  panjnad: ["guddu"],
  jassar: ["ravi-syphon"],
  "ravi-syphon": ["shahdara"],
  shahdara: ["balloki"],
  balloki: ["sidhnai"],
  sidhnai: ["panjnad"],
  "gs-wala": ["suleimanki"],
  suleimanki: ["islam"],
  islam: ["panjnad"],
};

export function downstreamOf(id: string): string[] {
  const seen = new Set<string>();
  const visit = (node: string) => {
    for (const next of DOWNSTREAM[node] ?? []) {
      if (!seen.has(next)) {
        seen.add(next);
        visit(next);
      }
    }
  };
  visit(id);
  return [...seen];
}
export function upstreamOf(id: string): string[] {
  return Object.keys(DOWNSTREAM).filter((node) =>
    downstreamOf(node).includes(id),
  );
}
export const PILOT_ID = "nowshera";
export const STARTING_STATIONS = [
  "nowshera",
  "warsak",
  "tarbela",
  "kohala",
  "akhnur",
  "marala",
];
export const stationNames = (ids: string[]) =>
  ids.map((id) => STATION_BY_ID[id]?.name ?? id).join(" → ");
