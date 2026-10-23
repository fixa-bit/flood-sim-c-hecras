import { expect, test } from "@playwright/test";
import example from "../../examples/nowshera-2022.json" with { type: "json" };

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
  await page.route("**/api/results", (route) =>
    route.fulfill({ json: [published] }),
  );
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
