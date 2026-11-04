import { expect, test } from "@playwright/test";
import example from "../../examples/nowshera-2022.json" with { type: "json" };
import { routeResults } from "./results";

test("keyboard steps frames, speed applies, and the WSE legend follows the result", async ({
  page,
}) => {
  // UI fixture only: frame metadata without rasters, not model output.
  const published = {
    id: "keyboard-fixture",
    scenario: example,
    engine: example.hydraulics.engine,
    terrain_sha256: example.domain.dem_sha256,
    validation_status: "UI fixture",
    legend: { wse: [286.4, 288.1, 289.8, 291.5] },
    frames: Array.from({ length: 30 }, (_, i) => ({
      time: new Date(Date.UTC(2022, 7, 20, i)).toISOString(),
      fields: {},
    })),
    hydrographs: [],
    extent_validation: null,
  };
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { status: "ok", runtimes: {} } }),
  );
  await page.route("**/api/assets", (route) => route.fulfill({ json: {} }));
  await page.route("**/api/prepared-cases", (route) =>
    route.fulfill({ json: [] }),
  );
  await routeResults(page, [published]);
  await page.addInitScript(
    (value) =>
      localStorage.setItem("indus-lab-scenario-v1", JSON.stringify(value)),
    example,
  );
  await page.goto("/");
  const slider = page.getByLabel("Model timestep", { exact: true });
  await expect(page.getByLabel("Result A", { exact: true })).toHaveValue(
    published.id,
  );
  await page.locator("body").click({ position: { x: 1, y: 1 } });
  await page.keyboard.press("ArrowRight");
  await expect(slider).toHaveValue("1");
  await page.keyboard.press("Shift+ArrowRight");
  await expect(slider).toHaveValue("11");
  await page.keyboard.press("ArrowLeft");
  await expect(slider).toHaveValue("10");
  await page.getByLabel("Playback speed").selectOption("16");
  await page.locator("body").click({ position: { x: 1, y: 1 } });
  await page.keyboard.press(" ");
  // 16× advances a frame every 50 ms: the 19 remaining frames finish in about a second.
  await expect(slider).toHaveValue("29", { timeout: 4000 });
  await page.getByLabel("Model field", { exact: true }).selectOption("wse");
  const legend = page.locator(".map-legend");
  await expect(legend).toContainText("WSE / m");
  await expect(legend).toContainText("<286.4");
  await expect(legend).toContainText("286.4–288.1");
  await expect(legend).toContainText(">291.5");
});

test("loading and reopening an exact published case enables playback without another compute job", async ({
  page,
}) => {
  // Isolated UI fixture: existing published frames, not a hydraulic computation.
  const scenario = { ...example, name: "Playback regression case" };
  const published = {
    id: "playback-fixture",
    scenario: Object.fromEntries(Object.entries(scenario).reverse()),
    engine: scenario.hydraulics.engine,
    terrain_sha256: scenario.domain.dem_sha256,
    validation_status: "UI fixture",
    frames: [0, 1, 2].map((hour) => ({
      time: `2022-08-20T0${hour}:00:00Z`,
      fields: {},
    })),
    hydrographs: [],
    extent_validation: null,
  };
  await page.route("**/api/health", (route) =>
    route.fulfill({ json: { status: "ok", runtimes: {} } }),
  );
  await page.route("**/api/assets", (route) => route.fulfill({ json: {} }));
  await page.route("**/api/prepared-cases", (route) =>
    route.fulfill({
      json: [{ label: "Playback case", scenario, ready: true }],
    }),
  );
  await routeResults(page, [published]);
  await page.route("**/api/scenarios/validate", (route) =>
    route.fulfill({ json: route.request().postDataJSON() }),
  );
  let jobs = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/api/jobs")) jobs++;
  });
  await page.goto("/");
  const runner = page.getByRole("region", {
    name: "Run a scenario case",
    exact: true,
  });
  await runner
    .getByLabel("Base scenario case")
    .selectOption(`prepared:${scenario.id}`);
  await runner
    .getByRole("button", { name: "Load case values", exact: true })
    .click();
  await expect(runner.locator(".case-outcome")).toContainText(
    "Published output for these exact values is ready",
  );
  await expect(page.getByLabel("Result A", { exact: true })).toHaveValue(
    published.id,
  );
  await page
    .getByRole("button", { name: "Play model output", exact: true })
    .click();
  await expect(page.getByLabel("Model timestep", { exact: true })).toHaveValue(
    "1",
  );
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Play model output", exact: true }),
  ).toBeEnabled();
  await expect(page.getByLabel("Result A", { exact: true })).toHaveValue(
    published.id,
  );
  // Changing even one input must not present the old output as the new draft.
  await page.getByLabel("Scenario name", { exact: true }).fill("Changed draft");
  await runner.getByLabel("Base scenario case").selectOption("current");
  await runner
    .getByRole("button", { name: "Load case values", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Play model output", exact: true }),
  ).toBeDisabled();
  expect(jobs).toBe(0);
});
