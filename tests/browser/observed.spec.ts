import { expect, test } from "@playwright/test";
import { openPanel } from "./panels";

test("the Simulation tab shows observed 2022 flows for stations that have them", async ({
  page,
}) => {
  const summary = await (await page.request.get("/api/observations")).json();
  test.skip(
    !summary.stations?.marala,
    "Run python -m server.observations acquire and build first.",
  );
  await page.setViewportSize({ width: 1366, height: 768 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("button", { name: /^Marala Chenab/ }).click();
  await openPanel(page, "Simulation");
  const card = page.getByRole("region", { name: "Observed 2022 flows" });
  await expect(
    card.getByRole("img", { name: "Observed 2022 discharge at Marala" }),
  ).toBeVisible();
  for (const label of [
    "FFC inflow · 06:00",
    "FFC outflow · 06:00",
    "WAPDA inflow · daily",
  ])
    await expect(card.getByText(label)).toBeVisible();
  await card.screenshot({ path: "test-results/observed-marala.png" });

  await page.getByRole("button", { name: /^Warsak Kabul/ }).click();
  await expect(card.getByText("FFC outflow · 06:00")).toBeVisible();
  await expect(card.getByText("FFC inflow · 06:00")).toHaveCount(0);

  await page.getByRole("button", { name: "Browse all 29 stations" }).click();
  await page.getByRole("button", { name: /^Kohala Jhelum/ }).click();
  await expect(card).toContainText(
    "No observed 2022 flows in the project for Kohala",
  );
  expect(errors).toEqual([]);
});
