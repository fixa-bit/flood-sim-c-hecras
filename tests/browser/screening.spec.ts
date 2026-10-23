import { expect, test } from "@playwright/test";

test("the real prepared public case passes readiness and opens verified engine output for playback", async ({
  page,
}) => {
  test.setTimeout(180000);
  const prepared = await (await page.request.get("/api/prepared-cases")).json();
  test.skip(
    !prepared.length,
    "Local public-data model has not been prepared on this machine.",
  );
  const scenario = prepared[0].scenario;
  const check = await page.request.post("/api/preflight", { data: scenario });
  expect((await check.json()).ready).toBeTruthy();
  const available = await (await page.request.get("/api/results")).json();
  const output = available.find(
    (item: { scenario: { id: string } }) => item.scenario.id === scenario.id,
  );
  expect(output.frames.length).toBeGreaterThan(300);
  expect(output.engine).toBe("LISFLOOD-FP");
  expect(output.scenario.domain.mesh_m).toBe(100);
  expect(output.provenance.numerical_review.warmup_review.passed).toBe(true);
  expect(
    output.provenance.numerical_review.warmup_review
      .wet_connection_inlet_to_outlet,
  ).toBe(true);
  expect(
    output.provenance.numerical_review.warmup_seconds_excluded_from_playback,
  ).toBe(72 * 3600);
  expect(new Date(output.frames[0].time).getTime()).toBeGreaterThanOrEqual(
    new Date(scenario.time.start).getTime(),
  );
  expect(
    new Date(output.frames[0].time).getTime() -
      new Date(scenario.time.start).getTime(),
  ).toBeLessThan(21000);
  expect(output.validation_passed).toBe(false);
  expect(output.provenance.numerical_review.relative_mass_error).toBeLessThan(
    0.001,
  );

  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.goto("/");
  const runner = page.getByRole("region", {
    name: "Run a scenario case",
    exact: true,
  });
  const firstOverlayResponse = page.waitForResponse(
    (response) =>
      response.url().includes(`/outputs/${output.id}/00000-depth.png`),
    { timeout: 120000 },
  );
  await runner
    .getByRole("button", { name: "Load runnable public case", exact: true })
    .click();
  await expect(runner.locator(".case-outcome.loaded")).toBeVisible({
    timeout: 30000,
  });
  await expect(page.getByLabel("Scenario name", { exact: true })).toHaveValue(
    scenario.name,
  );
  await expect(
    page.getByRole("combobox", { name: "Compute engine", exact: true }),
  ).toHaveValue("LISFLOOD-FP");
  await expect(
    page.getByRole("checkbox", {
      name: "Modeled Kabul inflow (HEC-HMS)",
      exact: true,
    }),
  ).toBeChecked();
  await runner
    .getByRole("button", { name: "Prepare & run case", exact: true })
    .click();
  await expect(runner.locator(".case-outcome.loaded")).toContainText(
    "Computed output loaded",
    { timeout: 120000 },
  );
  await expect(
    page.getByRole("combobox", { name: "Result A", exact: true }),
  ).toHaveValue(output.id, { timeout: 120000 });
  const play = page.getByRole("button", {
    name: "Play model output",
    exact: true,
  });
  await expect(play).toBeEnabled();
  await expect(page.locator(".result-details")).toContainText(
    "Exploratory channel-conditioned screening",
  );
  expect((await firstOverlayResponse).ok()).toBeTruthy();
  await page.locator(".globe-shell").scrollIntoViewIfNeeded();
  await expect(page.locator(".globe")).toHaveAttribute(
    "data-tiles-ready",
    "true",
    { timeout: 30000 },
  );
  await page.locator(".globe-shell").screenshot({
    path: "test-results/nowshera-initialized-river.png",
  });
  const overlayResponse = page.waitForResponse((response) =>
    response.url().includes(`/outputs/${output.id}/00190-depth.png`),
  );
  await page
    .getByRole("slider", { name: "Model timestep", exact: true })
    .fill("190");
  expect((await overlayResponse).ok()).toBeTruthy();
  await page.locator(".globe-shell").scrollIntoViewIfNeeded();
  await expect(page.locator(".globe canvas")).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".globe")).toHaveAttribute(
    "data-tiles-ready",
    "true",
    { timeout: 30000 },
  );
  await play.click();
  await expect(
    page.getByRole("button", { name: "Pause playback", exact: true }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page
        .getByRole("slider", { name: "Model timestep", exact: true })
        .inputValue(),
    )
    .not.toBe("190");
  await page
    .getByRole("button", { name: "Pause playback", exact: true })
    .click();
  await page
    .locator(".globe-shell")
    .screenshot({ path: "test-results/nowshera-computed-map.png" });
  await page.screenshot({
    path: "test-results/nowshera-computed-playback.png",
    fullPage: true,
  });
  expect(pageErrors).toEqual([]);
});

test("the prepared case can be loaded on a phone without filling individual fields", async ({
  page,
}) => {
  const prepared = await (await page.request.get("/api/prepared-cases")).json();
  test.skip(
    !prepared.length,
    "Local public-data model has not been prepared on this machine.",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const runner = page.getByRole("region", {
    name: "Run a scenario case",
    exact: true,
  });
  await runner
    .getByRole("button", { name: "Load runnable public case", exact: true })
    .click();
  await expect(runner.locator(".case-outcome.loaded")).toBeVisible({
    timeout: 30000,
  });
  const sizes = await page.evaluate(() => ({
    content: document.documentElement.scrollWidth,
    viewport: innerWidth,
  }));
  expect(sizes.content).toBeLessThanOrEqual(sizes.viewport);
  await runner.screenshot({
    path: "test-results/nowshera-runnable-case-mobile.png",
  });
});
