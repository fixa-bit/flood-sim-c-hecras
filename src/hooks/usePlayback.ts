import { useCallback, useEffect, useState } from "react";

export const FRAME_MS = 800;
export const PLAYBACK_SPEEDS = [1, 4, 16] as const;
export type PlaybackSpeed = (typeof PLAYBACK_SPEEDS)[number];

/**
 * Frame index, play state and speed for published raster playback.
 * Keyboard: Space plays/pauses, ←/→ step one frame, Shift+←/→ step ten.
 */
export function usePlayback(frameCount: number, active: boolean) {
  const [frameIndex, setFrameIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<PlaybackSpeed>(1);
  const last = Math.max(0, frameCount - 1);

  useEffect(() => {
    if (!playing || !frameCount) return;
    const timer = setInterval(
      () =>
        setFrameIndex((index) => {
          if (index >= last) {
            setPlaying(false);
            return index;
          }
          return index + 1;
        }),
      FRAME_MS / speed,
    );
    return () => clearInterval(timer);
  }, [playing, frameCount, last, speed]);

  useEffect(() => {
    if (!active || !frameCount) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        event.altKey ||
        event.ctrlKey ||
        event.metaKey ||
        target?.closest("input, textarea, select, button, [contenteditable]")
      )
        return;
      if (event.key === " ") {
        event.preventDefault();
        setFrameIndex((index) => (index >= last ? 0 : index));
        setPlaying((value) => !value);
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const step =
          (event.shiftKey ? 10 : 1) * (event.key === "ArrowLeft" ? -1 : 1);
        setPlaying(false);
        setFrameIndex((index) => Math.min(last, Math.max(0, index + step)));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, frameCount, last]);

  /** Jump to a frame and stop playing. */
  const seek = useCallback((index: number) => {
    setPlaying(false);
    setFrameIndex(index);
  }, []);
  /** Return to the first frame, stopped. */
  const rewind = useCallback(() => seek(0), [seek]);
  const stop = useCallback(() => setPlaying(false), []);
  const toggle = () => {
    if (frameIndex >= last) setFrameIndex(0);
    setPlaying(!playing);
  };
  return { frameIndex, playing, speed, setSpeed, seek, rewind, stop, toggle };
}
