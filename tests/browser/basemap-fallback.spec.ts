import { expect, test } from "@playwright/test";

const ONLINE_IMAGERY = /arcgisonline\.com|tile\.openstreetmap\.org/;
const FALLBACK = /Online imagery is slow/;

test("slow but progressing imagery, slow terrain and playback do not trigger the imagery fallback", async ({
  page,
}) => {
  test.setTimeout(120000);
  const results = await (await page.request.get("/api/results")).json();
  test.skip(
    !results.some((r: { id: string }) => r.id.startsWith("warsak-")),
    "Publish a Warsak result first.",
  );
  const wait = (ms: number) =>
    new Promise((resolve) => setTimeout(resolve, ms));
  // A busy local API: terrain tiles take 4 s each.
  await page.route("**/api/terrain/*/*/*.bin", async (route) => {
    await wait(4000);
    await route.continue();
  });
  // A slow connection: online tiles arrive one at a time, 1.5 s apart, so the
  // globe keeps loading for far longer than 12 s while imagery still arrives.
  let queue = Promise.resolve();
  await page.route(ONLINE_IMAGERY, (route) => {
    queue = queue.then(() => wait(1500)).then(() => route.continue());
  });
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/");
  await page.getByRole("button", { name: /^Warsak Kabul/ }).click();
  const open = page.getByRole("button", { name: /^Model results/ });
  await expect(open).toContainText(String(results.length));
  await open.click();
  await expect(page.getByLabel("Result A", { exact: true })).toHaveValue(
    /^warsak-/,
  );
  await page
    .locator(".map-views")
    .getByRole("button", { name: "Domain overview" })
    .click();
  const play = page.getByRole("button", {
    name: "Play model output",
    exact: true,
  });
  await expect(play).toBeEnabled({ timeout: 30000 });
  await play.click();
  // The globe really is loading slowly here; that alone must not blame imagery.
  await expect(page.locator(".globe")).toHaveAttribute(
    "data-tiles-ready",
    "false",
  );
  await page.waitForTimeout(40000);
  await expect(page.getByText(FALLBACK)).toHaveCount(0);
});

test("stalled online imagery falls back, then retries by itself or on Satellite", async ({
  page,
}) => {
  test.setTimeout(120000);
  let stalled = true;
  await page.route(ONLINE_IMAGERY, (route) =>
    // Leave the request hanging, as a stalled connection would.
    stalled ? undefined : route.continue(),
  );
  await page.goto("/");
  await page.getByRole("button", { name: /^Warsak Kabul/ }).click();
  await expect(page.getByText(FALLBACK)).toBeVisible({ timeout: 40000 });
  // Still stalled: Satellite retries now, and the stall is detected again.
  await page.getByRole("button", { name: "Satellite", exact: true }).click();
  await expect(page.getByText(FALLBACK)).toHaveCount(0);
  await expect(page.getByText(FALLBACK)).toBeVisible({ timeout: 20000 });
  // The connection recovers: the next automatic retry restores imagery.
  stalled = false;
  await expect(page.getByText(FALLBACK)).toHaveCount(0, { timeout: 70000 });
  await page.waitForTimeout(15000);
  await expect(page.getByText(FALLBACK)).toHaveCount(0);
});
