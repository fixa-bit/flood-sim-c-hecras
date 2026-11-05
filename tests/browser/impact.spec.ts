import { expect, test } from "@playwright/test";

const RESULT = "nowshera-hecras-0b012877-f7bc61d16eb7";

test("published output shows modelled exposure, flooded facilities and the tributary audit", async ({
  page,
}) => {
  test.setTimeout(90000);
  const exposure = await (
    await page.request.get(`/api/results/${RESULT}/exposure`)
  ).json();
  test.skip(
    !exposure.available,
    "Run python -m server.exposure acquire and publish the HEC-RAS case first.",
  );
  const audit = await (
    await page.request.get(`/api/results/${RESULT}/tributaries`)
  ).json();
  const peak = exposure.frames.findIndex(
    (frame: { time: string }) => frame.time === exposure.peak.time,
  );
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Model results" }).click();
  await page.getByLabel("Result A", { exact: true }).selectOption(RESULT);
  await page.getByLabel("Model timestep", { exact: true }).fill(String(peak));
  const panel = page.getByRole("region", { name: "Impact and tributaries" });
  const rounded = (
    Math.round(exposure.peak.people[0] / 100) * 100
  ).toLocaleString("en-US");
  await expect(panel.locator(".impact-cards > div").first()).toContainText(
    rounded,
  );
  for (const name of audit.summary.unrepresented_major)
    await expect(panel.getByRole("note")).toContainText(
      `${name} receives no water in this model.`,
    );
  await expect(panel.locator(".tributary-table")).toContainText(
    "Inflow: HMS Inflow",
  );
  const flooded = exposure.facilities.items.filter(
    (item: { depth_m?: number[] }) =>
      (item.depth_m?.[peak] ?? 0) >= exposure.facility_flood_m,
  );
  await expect(panel.locator(".impact-cards > div").nth(2)).toContainText(
    `${flooded.length} / ${exposure.facilities.in_extent}`,
  );
  await page.getByRole("button", { name: "Population", exact: true }).click();
  await page.getByRole("button", { name: "Facilities", exact: true }).click();
  await expect(page.getByLabel("Population density key")).toBeVisible();
  const columns = page.getByRole("button", {
    name: "Population 3D",
    exact: true,
  });
  await columns.click();
  await expect(columns).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("Population column key")).toContainText(
    "100 m = 500",
  );
  await expect(page.locator(".globe")).toHaveAttribute(
    "data-tiles-ready",
    "true",
    {
      timeout: 30000,
    },
  );
  await page.screenshot({ path: "test-results/impact.png", fullPage: true });
  expect(errors).toEqual([]);
});
