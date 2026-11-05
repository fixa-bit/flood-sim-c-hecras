import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Exposure, ExposureLayers, TributaryAudit } from "../lib/api";

type Context = { exposure?: Exposure; tributaries?: TributaryAudit };

/** Exposure layers, loaded once; they are independent of any result. */
export function useExposureLayers() {
  const [layers, setLayers] = useState<ExposureLayers>({});
  useEffect(() => {
    const controller = new AbortController();
    void api<ExposureLayers>("exposure", undefined, {
      signal: controller.signal,
    })
      .then(setLayers)
      .catch(() => {});
    return () => controller.abort();
  }, []);
  return layers;
}

/**
 * Exposure and tributary audit for one published result. Both are derived on
 * the server from the result's own rasters and boundary files, and cached by id.
 */
export function useResultContext(resultId: string | undefined) {
  const [cache, setCache] = useState<Record<string, Context>>({});
  const known = resultId ? cache[resultId] : undefined;
  useEffect(() => {
    if (!resultId || known) return;
    const controller = new AbortController();
    const id = encodeURIComponent(resultId);
    const options = { signal: controller.signal };
    void Promise.all([
      api<Exposure>(`results/${id}/exposure`, undefined, options).catch(
        (error: Error) => ({
          available: false as const,
          reason: error.message,
        }),
      ),
      api<TributaryAudit>(
        `results/${id}/tributaries`,
        undefined,
        options,
      ).catch((error: Error) => ({
        available: false as const,
        reason: error.message,
      })),
    ]).then(([exposure, tributaries]) => {
      if (!controller.signal.aborted)
        setCache((current) => ({
          ...current,
          [resultId]: { exposure, tributaries },
        }));
    });
    return () => controller.abort();
  }, [resultId, known]);
  return known ?? {};
}
