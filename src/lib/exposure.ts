import type { ColumnSeries, Facility } from "./api";

/** Depth at a facility for one frame; facilities that never got wet read 0. */
export function facilityDepth(facility: Facility, frameIndex: number) {
  return facility.depth_m?.[frameIndex] ?? 0;
}

/** Residents of a column in water at one threshold, for one frame. */
export function columnCount(
  series: ColumnSeries | undefined,
  frameIndex: number,
) {
  if (!series) return 0;
  return series.people[frameIndex - series.from] ?? 0;
}
