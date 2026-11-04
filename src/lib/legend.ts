export type Field = "depth" | "wse" | "velocity";
export type Legend = Record<Field, number[]>;

/** Matches server/publish.py FIELD_EDGES; used for results published before per-result legends. */
export const DEFAULT_EDGES: Legend = {
  depth: [0.3, 1, 2, 5],
  wse: [100, 300, 500, 1000],
  velocity: [0.5, 1, 2, 3],
};
export const LEGEND_COLORS = [
  "#91d7f1",
  "#3da9dc",
  "#226fc0",
  "#224391",
  "#64419c",
];
export const FIELD_TITLES: Record<Field, string> = {
  depth: "DEPTH / m",
  wse: "WSE / m",
  velocity: "SPEED / m/s",
};

const number = (value: number) =>
  value.toLocaleString("en-US", { maximumFractionDigits: 1 });

/** Five class labels for four edges. Depth and speed start at zero; WSE is open below. */
export function legendLabels(field: Field, legend?: Partial<Legend>) {
  const edges = legend?.[field] ?? DEFAULT_EDGES[field];
  const first =
    field === "wse" ? `<${number(edges[0])}` : `0–${number(edges[0])}`;
  return [
    first,
    ...edges.slice(1).map((edge, i) => `${number(edges[i])}–${number(edge)}`),
    `>${number(edges[edges.length - 1])}`,
  ];
}
