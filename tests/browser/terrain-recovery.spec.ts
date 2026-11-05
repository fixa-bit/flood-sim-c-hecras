import { expect, test } from "@playwright/test";

test("terrain recovers after the local API is briefly unavailable", async ({
  page,
}) => {
  test.setTimeout(90000);
  const meta = await (await page.request.get("/api/terrain/metadata")).json();
  test.skip(!meta.available, "Local FABDEM terrain is not prepared.");
  let down = true;
  const failed = new Set<string>();
  const recovered = new Set<string>();
  await page.route("**/api/terrain/*/*/*.bin", (route) => {
    const url = route.request().url();
    if (down) {
      failed.add(url);
      return route.abort("connectionrefused");
    }
    if (failed.has(url)) recovered.add(url);
    return route.continue();
  });
  await page.goto("/");
  await page.getByRole("button", { name: /^Warsak Kabul/ }).click();
  await expect.poll(() => failed.size, { timeout: 30000 }).toBeGreaterThan(0);
  down = false;
  // Tiles whose first request failed are requested again, not left flat.
  await expect
    .poll(() => recovered.size, { timeout: 30000 })
    .toBeGreaterThan(0);
  await expect(page.locator(".globe")).toHaveAttribute(
    "data-tiles-ready",
    "true",
    {
      timeout: 45000,
    },
  );
  await expect(page.getByText(/Online imagery is slow/)).toHaveCount(0);
  await expect(page.locator(".terrain-tag")).toHaveText(
    "FABDEM ~30 m · local terrain",
  );
});
