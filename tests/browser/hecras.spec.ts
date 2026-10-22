import { expect, test } from "@playwright/test";

test("the prepared HEC-RAS case runs through the selected engine and opens native output", async ({
  page,
}) => {
  test.setTimeout(90000);
  const cases = await (await page.request.get("/api/prepared-cases")).json();
  const ras = cases.find(
    (item: { scenario: { hydraulics: { engine: string } } }) =>
      item.scenario.hydraulics.engine === "HEC-RAS 2D",
  );
  test.skip(!ras, "Build the local exploratory HEC-RAS case first.");
  const preflight = await page.request.post("/api/preflight", {
    data: ras.scenario,
  });
  expect((await preflight.json()).ready).toBe(true);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  const runner = page.getByRole("region", {
    name: "Run a scenario case",
    exact: true,
  });
  await runner
    .getByRole("button", { name: "Load runnable public case", exact: true })
    .click();
  await expect(
    page.getByRole("combobox", { name: "Compute engine", exact: true }),
  ).toHaveValue("LISFLOOD-FP");
  await runner
    .getByRole("combobox", { name: "Engine for this run" })
    .selectOption("HEC-RAS 2D");
  await expect(
    runner.getByRole("combobox", { name: "Base scenario case" }),
  ).toHaveValue(`prepared:${ras.scenario.id}`);
  const submitted = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/jobs") &&
      response.request().method() === "POST",
  );
  const overlay = page.waitForResponse((response) =>
    response.url().includes(`/outputs/${ras.result_id}/00000-depth.png`),
  );
  await runner
    .getByRole("button", { name: "Prepare & run case", exact: true })
    .click();
  const response = await submitted;
  expect(response.request().postDataJSON().hydraulics.engine).toBe(
    "HEC-RAS 2D",
  );
  const job = await response.json();
  expect(job.state).toBe("published");
  await expect(
    page.getByRole("combobox", { name: "Compute engine", exact: true }),
  ).toHaveValue("HEC-RAS 2D");
  const available = await (await page.request.get("/api/results")).json();
  const output = available.find(
    (item: { id: string }) => item.id === job.result_id,
  );
  expect(output.engine).toBe("HEC-RAS 2D");
  expect(output.frames).toHaveLength(385);
  expect(output.provenance.numerical_review.passed).toBe(true);
  expect(output.validation_passed).toBe(false);
  expect((await overlay).ok()).toBe(true);
  const play = page.getByRole("button", {
    name: "Play model output",
    exact: true,
  });
  await expect(play).toBeEnabled({ timeout: 30000 });
  await play.click();
  await expect(
    page.getByRole("button", { name: "Pause playback", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Pause playback", exact: true })
    .click();
  const lisflood = available.find(
    (item: { engine: string }) => item.engine === "LISFLOOD-FP",
  );
  expect(lisflood).toBeTruthy();
  await page.getByLabel("Result B", { exact: true }).selectOption(lisflood.id);
  await page
    .getByLabel("Comparison timing", { exact: true })
    .selectOption("nearby");
  await expect(
    page.getByLabel("Comparison split", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/B time offset:/)).toBeVisible();
  await page
    .locator(".globe-shell")
    .screenshot({
      path: "test-results/nowshera-hecras-lisflood-comparison.png",
    });
  expect(errors).toEqual([]);
});
