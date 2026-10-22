import type { Scenario } from "../data/scenarios";

const MAX_CASE_BYTES = 1024 * 1024;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function overlay(
  base: unknown,
  values: Record<string, unknown>,
): Record<string, unknown> {
  const entries = new Map(Object.entries(record(base) ? base : {}));
  for (const [key, value] of Object.entries(values)) {
    entries.set(key, record(value) ? overlay(entries.get(key), value) : value);
  }
  return Object.fromEntries(entries);
}

// Full scenarios retain their identity and explicit hashes. Partial values inherit
// the selected case; arrays replace the base array rather than being appended.
// The server's strict schema validates the result before it reaches the editor.
export function scenarioCaseValues(
  text: string,
  base: Scenario,
  demHash: string | null,
): unknown {
  if (new Blob([text]).size > MAX_CASE_BYTES)
    throw new Error("Scenario JSON must be smaller than 1 MB.");
  const trimmed = text.trim();
  let candidate: Record<string, unknown>;
  if (!trimmed) {
    candidate = structuredClone(base);
  } else {
    let values: unknown;
    try {
      values = JSON.parse(trimmed);
    } catch {
      throw new Error(
        "Case values must be valid JSON. Check quotes, commas and brackets.",
      );
    }
    if (!record(values))
      throw new Error(
        "Case values must be a JSON object containing a scenario or nested scenario fields.",
      );
    candidate = "schema_version" in values ? values : overlay(base, values);
  }
  if (record(candidate.domain) && candidate.domain.dem_sha256 === null)
    candidate.domain.dem_sha256 = demHash;
  return candidate;
}
