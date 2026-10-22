import { test, expect } from "@playwright/test";
import example from "../../examples/nowshera-2022.json" with { type: "json" };

test("Nowshera pilot, upstream boundaries and no fabricated output", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Nowshera / Kabul River" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run hydraulic model" }),
  ).toBeDisabled();
  await expect(page.getByText("Hydrograph awaits model output")).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Warsak" })).toBeChecked();
  await expect(page.locator(".globe canvas")).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".globe")).toHaveAttribute(
    "data-tiles-ready",
    "true",
    { timeout: 30000 },
  );
  await page.screenshot({
    path: "test-results/desktop-lab.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("upstream station selection changes downstream receptors", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Tarbela Indus" }).click();
  await expect(
    page.getByRole("heading", { name: "Tarbela / Indus River" }),
  ).toBeVisible();
  await expect(page.locator(".network-section")).toContainText(
    "Attock → Kalabagh → Chashma → Taunsa",
  );
  await expect(
    page.getByText(
      "Planning available. Hydraulic compute is limited to the Nowshera pilot.",
    ),
  ).toBeVisible();
});

test("scenario presets persist and export versioned JSON", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Experiment", { exact: true }).selectOption("climate");
  await expect(page.getByLabel("Rain multiplier")).toHaveValue("1.3");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await expect(page.getByText("Scenario saved to this browser.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Experiment", { exact: true })).toHaveValue(
    "climate",
  );
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export JSON" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.json$/);
});

test("readiness and provenance report missing scientific inputs", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Check readiness" }).click();
  await expect(page.locator(".preflight-list")).toContainText(
    "requirements to resolve",
  );
  await page.getByRole("button", { name: "Data & provenance" }).click();
  await expect(
    page.getByRole("heading", { name: "Data with a traceable origin" }),
  ).toBeVisible();
  await expect(page.locator(".source-list article")).toHaveCount(9);
  await page.getByRole("button", { name: "Plan verification" }).click();
  await expect(page.locator(".verification-list article")).toHaveCount(5);
});

test("custom outlet supports planning and invalid values block preparation", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Custom lat / long or gauge" })
    .click();
  await page.getByLabel("Latitude °N").fill("90");
  await expect(page.getByRole("alert")).toContainText("Pakistan study region");
  await expect(
    page.getByRole("button", { name: "Prepare domain" }),
  ).toBeDisabled();
});

test("mobile workspace fits without page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Nowshera / Kabul River" }),
  ).toBeVisible();
  const widths = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    viewport: innerWidth,
  }));
  expect(widths.scroll).toBeLessThanOrEqual(widths.viewport);
  await page.locator(".globe-shell").scrollIntoViewIfNeeded();
  await expect(page.locator(".globe canvas")).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".globe")).toHaveAttribute(
    "data-tiles-ready",
    "true",
    { timeout: 30000 },
  );
  await page.screenshot({
    path: "test-results/mobile-lab.png",
    fullPage: true,
  });
});

test("published output plays on model time and compares only exact timestamps", async ({
  page,
}) => {
  // UI-only fixture: this is never registered in the scientific workspace.
  const overlay = {
    url: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==",
    bounds: [71.96, 33.99, 72, 34.03],
  };
  const base = {
    scenario: example,
    scenario_sha256: "fixture",
    engine: "HEC-RAS 2D",
    terrain_sha256: "fixture",
    validation_status: "Synthetic UI fixture; unvalidated",
    validation_passed: false,
    hydrographs: [],
    extent_validation: null,
  };
  const a = {
    ...base,
    id: "test-a",
    frames: [
      { time: "2022-08-20T00:00:00Z", fields: { depth: overlay } },
      { time: "2022-08-20T01:00:00Z", fields: { depth: overlay } },
    ],
  };
  const b = {
    ...base,
    id: "test-b",
    frames: [
      { time: "2022-08-20T00:00:04.594Z", fields: { depth: overlay } },
      { time: "2022-08-20T01:00:00Z", fields: { depth: overlay } },
    ],
  };
  await page.route("**/api/results", (route) =>
    route.fulfill({ json: [a, b] }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Model results" }).click();
  await page.getByLabel("Result A", { exact: true }).selectOption("test-a");
  await page.getByLabel("Result B", { exact: true }).selectOption("test-b");
  await expect(
    page.getByText("B has no frame at this model time."),
  ).toBeVisible();
  await page
    .getByLabel("Comparison timing", { exact: true })
    .selectOption("nearby");
  await expect(
    page.getByLabel("Comparison split", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/B time offset: \+4\.594 s/)).toBeVisible();
  await expect(
    page.getByText("B · HEC-RAS 2D: 2022-08-20T00:00:04.594Z", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Comparison timing", { exact: true })
    .selectOption("exact");
  await expect(
    page.getByLabel("Comparison split", { exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("Model timestep").fill("1");
  await expect(page.getByText("2022-08-20 01:00 UTC")).toBeVisible();
  await expect(
    page.getByText("B has no frame at this model time."),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Play model output" }).click();
  await expect(page.getByText("2022-08-20 00:00 UTC")).toBeVisible();
  await expect(page.getByText("2022-08-20 01:00 UTC")).toBeVisible();
});
