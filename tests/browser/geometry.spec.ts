import { expect, test } from "@playwright/test";

test("native HEC-RAS roughness zones are selectable and retain honest geometry status", async ({
  page,
}) => {
  test.setTimeout(90000);
  const cases = await (await page.request.get("/api/prepared-cases")).json();
  const candidate = cases.find((item: { scenario: { id: string } }) =>
    item.scenario.id.startsWith("nowshera-hecras-zoned-"),
  );
  test.skip(!candidate, "Compute the zoned-roughness HEC-RAS case first.");
  const results = await (await page.request.get("/api/results")).json();
  const output = results.find(
    (item: { id: string }) => item.id === candidate.result_id,
  );
  expect(output.frames).toHaveLength(385);
  expect(output.provenance.geometry_and_roughness.bed_is_surveyed).toBe(false);
  expect(
    output.provenance.geometry_and_roughness
      .roughness_is_measured_or_calibrated,
  ).toBe(false);
  const native = output.provenance.numerical_review.roughness_zones[0];
  expect(native.passed).toBe(true);
  expect(native.cell_distinct_count).toBeGreaterThan(1);
  expect(native.face_distinct_count).toBeGreaterThan(1);
  expect(output.validation_passed).toBe(false);

  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  const runner = page.getByRole("region", {
    name: "Run a scenario case",
    exact: true,
  });
  await runner
    .getByRole("combobox", { name: "Base scenario case" })
    .selectOption(`prepared:${candidate.scenario.id}`);
  await runner
    .getByRole("combobox", { name: "Engine for this run" })
    .selectOption("HEC-RAS 2D");
  await expect(
    runner.getByRole("combobox", { name: "Base scenario case" }),
  ).toHaveValue(`prepared:${candidate.scenario.id}`);
  const submitted = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/jobs") &&
      response.request().method() === "POST",
  );
  await runner
    .getByRole("button", { name: "Prepare & run case", exact: true })
    .click();
  const response = await submitted;
  expect(response.request().postDataJSON().id).toBe(candidate.scenario.id);
  const job = await response.json();
  expect(job.state).toBe("published");
  expect(job.result_id).toBe(candidate.result_id);
  await expect(
    page.getByRole("button", { name: "Play model output", exact: true }),
  ).toBeEnabled({ timeout: 30000 });
  const overlay = await page.request.get(
    `/outputs/${candidate.result_id}/00000-depth.png`,
  );
  expect(overlay.ok()).toBe(true);

  await page.getByRole("button", { name: "Data & provenance" }).click();
  const geometry = page.getByRole("region", {
    name: "Geometry and roughness",
    exact: true,
  });
  await expect(geometry).toContainText(
    "Surveyed channel geometry is still missing",
  );
  await expect(geometry.locator("tbody tr")).toHaveCount(7);
  await expect(geometry).toContainText(candidate.label);
  await geometry.screenshot({
    path: "test-results/geometry-roughness-priors.png",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  const widths = await page.evaluate(() => ({
    content: document.documentElement.scrollWidth,
    viewport: innerWidth,
  }));
  expect(widths.content).toBeLessThanOrEqual(widths.viewport);
  expect(errors).toEqual([]);
});
