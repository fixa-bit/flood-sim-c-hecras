import { test, expect } from "@playwright/test";

test("one-click examples load distinct editable scenarios and preserve the terrain binding", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Example scenarios", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".example-card")).toHaveCount(2);
  await expect(
    page.getByText("Local data service connected", { exact: true }),
  ).toBeVisible();

  await page
    .getByRole("button", { name: "Load Nowshera 2022", exact: true })
    .click();
  await expect(page.getByLabel("Scenario name", { exact: true })).toHaveValue(
    "Example · Nowshera 2022",
  );
  await expect(
    page.getByRole("combobox", { name: "Boundary method", exact: true }),
  ).toHaveValue("inflow_hydrograph");
  await expect(
    page.getByRole("combobox", { name: "Soil moisture", exact: true }),
  ).toHaveValue("normal");
  await expect(
    page.getByRole("checkbox", { name: "Warsak", exact: true }),
  ).toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Charsadda Road (Swat)", exact: true }),
  ).toBeChecked();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();

  await page
    .getByRole("button", { name: "Load wetter monsoon", exact: true })
    .click();
  await expect(page.getByLabel("Experiment", { exact: true })).toHaveValue(
    "climate",
  );
  await expect(
    page.getByRole("combobox", { name: "Boundary method", exact: true }),
  ).toHaveValue("rain_on_grid");
  await expect(
    page.getByRole("combobox", { name: "Rainfall product", exact: true }),
  ).toHaveValue("CHIRPS");
  await expect(page.getByLabel("Rain multiplier", { exact: true })).toHaveValue(
    "1.3",
  );
  await expect(
    page.getByRole("combobox", { name: "Soil moisture", exact: true }),
  ).toHaveValue("saturated");
  await expect(
    page.getByRole("button", { name: "Run hydraulic model" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Save draft", exact: true }).click();

  const drafts = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("indus-lab-library-v1") ?? "[]"),
  );
  expect(drafts).toHaveLength(2);
  expect(new Set(drafts.map((draft: { id: string }) => draft.id)).size).toBe(2);
  const assets = await (await page.request.get("/api/assets")).json();
  for (const draft of drafts) {
    const response = await page.request.post("/api/scenarios/validate", {
      data: draft,
    });
    expect(response.ok()).toBeTruthy();
    expect(draft.domain.dem_sha256).toBe(assets.dem?.sha256 ?? null);
  }
  await page.reload();
  await expect(page.getByLabel("Scenario name", { exact: true })).toHaveValue(
    "Example · Wetter monsoon +30%",
  );
});

test("example cards remain usable on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Load wetter monsoon", exact: true })
    .click();
  await expect(page.locator(".example-card.selected")).toContainText(
    "Wetter monsoon +30%",
  );
  const widths = await page.evaluate(() => ({
    content: document.documentElement.scrollWidth,
    viewport: innerWidth,
  }));
  expect(widths.content).toBeLessThanOrEqual(widths.viewport);
  await page
    .locator(".scenario-examples")
    .screenshot({ path: "test-results/example-scenarios-mobile.png" });
});
