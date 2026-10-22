export function comparisonFrame<T extends { time: string }>(
  frames: readonly T[],
  target: string | undefined,
  toleranceSeconds = 0,
): T | undefined {
  const time = Date.parse(target ?? "");
  if (!Number.isFinite(time)) return undefined;
  let closest: T | undefined;
  let distance = Infinity;
  for (const frame of frames) {
    const delta = Math.abs(Date.parse(frame.time) - time);
    if (delta <= toleranceSeconds * 1000 && delta < distance) {
      closest = frame;
      distance = delta;
    }
  }
  return closest;
}
