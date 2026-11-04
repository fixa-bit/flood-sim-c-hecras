import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Result, ResultSummary } from "../lib/api";

/**
 * Full manifests (frames, hydrographs) for the requested result IDs.
 * The listing is only a summary; details are fetched on demand and cached
 * until a new listing arrives, so restyled or republished results reload.
 * Pass a stable callback (such as a state setter) as onError.
 */
export function useResultDetails(
  ids: string[],
  listing: ResultSummary[],
  onError: (message: string) => void,
) {
  const [cache, setCache] = useState<{
    listing: ResultSummary[];
    items: Record<string, Result>;
  }>({ listing, items: {} });
  const items = cache.listing === listing ? cache.items : {};
  const known = new Set(listing.map((item) => item.id));
  const missing = [...new Set(ids)]
    .filter((id) => id && known.has(id) && !items[id])
    .join("\n");

  useEffect(() => {
    if (!missing) return;
    const controller = new AbortController();
    for (const id of missing.split("\n"))
      void api<Result>(`results/${encodeURIComponent(id)}`, undefined, {
        signal: controller.signal,
      })
        .then((result) =>
          setCache((current) => ({
            listing,
            items: {
              ...(current.listing === listing ? current.items : {}),
              [id]: result,
            },
          })),
        )
        .catch((error: Error) => {
          if (!controller.signal.aborted) onError(error.message);
        });
    return () => controller.abort();
  }, [missing, listing, onError]);

  return items;
}
