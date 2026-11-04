import type { Page } from "@playwright/test";

type Fixture = { id: string; frames: unknown[]; hydrographs?: unknown[] };

/**
 * Serve UI fixture results like the API: `/api/results` lists summaries
 * (no frames or hydrographs) and `/api/results/{id}` returns the full result.
 */
export async function routeResults(page: Page, results: Fixture[]) {
  await page.route("**/api/results", (route) =>
    route.fulfill({
      json: results.map((result) => ({
        ...Object.fromEntries(
          Object.entries(result).filter(
            ([key]) => key !== "frames" && key !== "hydrographs",
          ),
        ),
        frame_count: result.frames.length,
      })),
    }),
  );
  await page.route("**/api/results/*", (route) => {
    const id = decodeURIComponent(route.request().url().split("/").pop()!);
    const result = results.find((item) => item.id === id);
    return result
      ? route.fulfill({ json: result })
      : route.fulfill({ status: 404, json: { detail: "Unknown result" } });
  });
}
