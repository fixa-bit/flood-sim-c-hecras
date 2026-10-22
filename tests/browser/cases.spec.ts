import { expect, test } from "@playwright/test";
import example from "../../examples/nowshera-2022.json" with { type: "json" };

async function openRunner(page: import("@playwright/test").Page) {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Load case values", exact: true }),
  ).toBeEnabled({ timeout: 30000 });
  return page.getByRole("region", { name: "Run a scenario case", exact: true });
}

test("nested case values fill multiple fields, save and reload without manual editing", async ({
  page,
}) => {
  const runner = await openRunner(page);
  await runner
    .getByRole("combobox", { name: "Base scenario case" })
    .selectOption("example:example-nowshera-wetter-monsoon");
  await runner
    .getByText("Paste or adjust case values", { exact: true })
    .click();
  await runner.getByLabel("Case values (JSON)").fill(
    JSON.stringify({
      id: "rainfall-case-17",
      name: "Public rainfall sensitivity case",
      domain: { mesh_m: 75 },
      time: { output_interval_minutes: 30 },
      forcing: { rainfall_multiplier: 1.7, upstream_station_ids: ["warsak"] },
    }),
  );
  await runner
    .getByRole("button", { name: "Load case values", exact: true })
    .click();
  await expect(runner.locator(".case-outcome")).toContainText(
    "Case values loaded",
  );
  await expect(page.getByLabel("Scenario name", { exact: true })).toHaveValue(
    "Public rainfall sensitivity case",
  );
  await expect(page.getByLabel("Rain multiplier", { exact: true })).toHaveValue(
    "1.7",
  );
  await expect(page.getByLabel("Mesh / m", { exact: true })).toHaveValue("75");
  await expect(
    page.getByLabel("Output / minutes", { exact: true }),
  ).toHaveValue("30");
  await expect(
    page.getByRole("combobox", { name: "Boundary method", exact: true }),
  ).toHaveValue("rain_on_grid");
  await expect(
    page.getByRole("checkbox", { name: "Charsadda Road (Swat)", exact: true }),
  ).not.toBeChecked();
  const scenario = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("indus-lab-scenario-v1")!),
  );
  const assets = await (await page.request.get("/api/assets")).json();
  expect(scenario.domain.dem_sha256).toBe(assets.dem.sha256);
  expect(scenario.forcing.upstream_station_ids).toEqual(["warsak"]);
  expect(scenario.forcing.soil_moisture).toBe("saturated");
  await page.getByRole("button", { name: "Save draft", exact: true }).click();
  await page.reload();
  await expect(page.getByLabel("Scenario name", { exact: true })).toHaveValue(
    "Public rainfall sensitivity case",
  );
  await page
    .getByRole("combobox", { name: "Base scenario case" })
    .selectOption("saved:rainfall-case-17");
  await page
    .getByRole("button", { name: "Load case values", exact: true })
    .click();
  await expect(page.getByLabel("Rain multiplier", { exact: true })).toHaveValue(
    "1.7",
  );
});

test("JSON files preserve full case identity and bad values leave the editor unchanged", async ({
  page,
}) => {
  const runner = await openRunner(page);
  const uploaded = {
    ...example,
    id: "imported-river-case",
    name: "Imported river case",
    domain: { ...example.domain, dem_sha256: "a".repeat(64) },
    time: {
      ...example.time,
      start: "2022-08-20T01:00:00Z",
      end: "2022-09-05T01:00:00Z",
    },
  };
  await runner.getByLabel("Scenario case JSON file").setInputFiles({
    name: "river-case.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(uploaded)),
  });
  await expect(
    runner.getByText("File ready: river-case.json", { exact: true }),
  ).toBeVisible();
  await runner
    .getByRole("button", { name: "Load case values", exact: true })
    .click();
  await expect(page.getByLabel("Scenario name", { exact: true })).toHaveValue(
    uploaded.name,
  );
  const loaded = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("indus-lab-scenario-v1")!),
  );
  expect(loaded.id).toBe(uploaded.id);
  expect(loaded.domain.dem_sha256).toBe(uploaded.domain.dem_sha256);
  expect(loaded.time).toEqual(uploaded.time);
  expect(loaded.provenance.created_at).toBe(uploaded.provenance.created_at);

  let jobs = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/api/jobs")) jobs++;
  });
  for (const [text, expected] of [
    ['{"forcing":', "valid JSON"],
    ["[]", "JSON object"],
    [
      JSON.stringify({ forcing: { rainfall_multiplier: -2 } }),
      "forcing.rainfall_multiplier",
    ],
    [JSON.stringify({ invented_depth: 4 }), "invented_depth"],
  ]) {
    await runner.getByLabel("Case values (JSON)").fill(text);
    await runner
      .getByRole("button", { name: "Prepare & run case", exact: true })
      .click();
    await expect(runner.getByRole("alert")).toContainText(expected);
    await expect(page.getByLabel("Scenario name", { exact: true })).toHaveValue(
      uploaded.name,
    );
  }
  expect(jobs).toBe(0);
  await runner.getByLabel("Scenario case JSON file").setInputFiles({
    name: "oversized-case.json",
    mimeType: "application/json",
    buffer: Buffer.alloc(1024 * 1024 + 1),
  });
  await expect(runner.getByRole("alert")).toContainText("smaller than 1 MB");
  await expect(
    runner.getByRole("button", { name: "Prepare & run case", exact: true }),
  ).toBeDisabled();
  await expect(page.getByLabel("Scenario name", { exact: true })).toHaveValue(
    uploaded.name,
  );
});

test("a case with missing scientific inputs shows readiness failures and submits no job", async ({
  page,
}) => {
  // Domain response is a UI fixture, never registered in the scientific workspace.
  let jobs = 0;
  let prepared = false;
  await page.route("**/api/domain", (route) => {
    prepared = true;
    return route.fulfill({ json: { clips: {}, catchment: null } });
  });
  await page.route("**/api/preflight", (route) =>
    route.fulfill({
      json: {
        ready: false,
        scenario_sha256: "isolated-ui-fixture",
        checks: [
          {
            key: "inflow",
            passed: false,
            detail:
              "Missing inflow asset. Register a documented local input with the CLI.",
          },
          {
            key: "prepared_model",
            passed: false,
            detail:
              "Bind a reviewed, scenario-specific engine project with python -m server.cli bind.",
          },
        ],
      },
    }),
  );
  page.on("request", (request) => {
    if (request.url().endsWith("/api/jobs")) jobs++;
  });
  const runner = await openRunner(page);
  await runner
    .getByRole("combobox", { name: "Base scenario case" })
    .selectOption("example:example-nowshera-2022");
  await runner
    .getByRole("button", { name: "Prepare & run case", exact: true })
    .click();
  await expect(runner.locator(".case-outcome.blocked")).toContainText(
    "Missing inflow asset",
  );
  await expect(runner.locator(".case-outcome.blocked")).toContainText(
    "Bind a reviewed, scenario-specific engine project",
  );
  expect(prepared).toBeTruthy();
  expect(jobs).toBe(0);
  await expect(
    page.getByRole("button", { name: "Run hydraulic model" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Play model output" }),
  ).toBeDisabled();
});

test("a ready case passes the exact validated values through preparation and job submission", async ({
  page,
}) => {
  // Isolated request fixtures verify orchestration, not actual hydraulic readiness.
  const calls: { endpoint: string; values: unknown }[] = [];
  for (const endpoint of ["domain", "preflight", "jobs"]) {
    await page.route(`**/api/${endpoint}`, (route) => {
      calls.push({ endpoint, values: route.request().postDataJSON() });
      const json =
        endpoint === "domain"
          ? { clips: {}, catchment: null }
          : endpoint === "preflight"
            ? { ready: true, scenario_sha256: "ui-fixture", checks: [] }
            : {
                id: "ui-fixture",
                state: "computed",
                detail: "UI orchestration fixture only",
              };
      return route.fulfill({ json });
    });
  }
  const runner = await openRunner(page);
  await runner
    .getByRole("combobox", { name: "Base scenario case" })
    .selectOption("example:example-nowshera-2022");
  const validation = page.waitForResponse((response) =>
    response.url().endsWith("/api/scenarios/validate"),
  );
  await runner
    .getByRole("button", { name: "Prepare & run case", exact: true })
    .click();
  const valid = await (await validation).json();
  await expect(runner.locator(".case-outcome.submitted")).toContainText(
    "Case submitted to the hydraulic model",
  );
  expect(calls.map((call) => call.endpoint)).toEqual([
    "domain",
    "preflight",
    "jobs",
  ]);
  for (const call of calls) expect(call.values).toEqual(valid);
  await expect(
    page.getByRole("button", { name: "Play model output" }),
  ).toBeDisabled();
});

test("editing a case while preparation is pending prevents submitting stale values", async ({
  page,
}) => {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  const laterRequests: string[] = [];
  await page.route("**/api/domain", async (route) => {
    await pending;
    await route.fulfill({ json: { clips: {}, catchment: null } });
  });
  page.on("request", (request) => {
    if (/\/api\/(preflight|jobs)$/.test(request.url()))
      laterRequests.push(request.url());
  });
  const runner = await openRunner(page);
  const preparation = page.waitForRequest((request) =>
    request.url().endsWith("/api/domain"),
  );
  await runner
    .getByRole("button", { name: "Prepare & run case", exact: true })
    .click();
  await preparation;
  try {
    await page
      .getByLabel("Scenario name", { exact: true })
      .fill("Changed while preparing");
  } finally {
    release();
  }
  await expect(runner.getByRole("alert")).toContainText(
    "scenario changed during preparation",
  );
  expect(laterRequests).toEqual([]);
});

test("the case runner fits a phone with pasted values and feedback visible", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const runner = await openRunner(page);
  await runner
    .getByText("Paste or adjust case values", { exact: true })
    .click();
  await runner
    .getByLabel("Case values (JSON)")
    .fill('{"name":"Phone scenario case"}');
  await runner
    .getByRole("button", { name: "Load case values", exact: true })
    .click();
  await expect(runner.locator(".case-outcome.loaded")).toBeVisible();
  const sizes = await page.evaluate(() => ({
    content: document.documentElement.scrollWidth,
    viewport: innerWidth,
  }));
  expect(sizes.content).toBeLessThanOrEqual(sizes.viewport);
  await runner.screenshot({
    path: "test-results/scenario-case-runner-mobile.png",
  });
});
