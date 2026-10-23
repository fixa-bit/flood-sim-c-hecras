import type { Scenario } from "../data/scenarios";

// JSON object key order is not part of a scenario's identity. Array order and
// every value still matter so edited drafts never borrow another case's output.
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.entries(value)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`)
      .join(",")}}`;
  return JSON.stringify(value);
}

export function sameScenario(a: Scenario, b: Scenario): boolean {
  return canonical(a) === canonical(b);
}
