import type { Page } from "@playwright/test";

/** The case runner is its own panel tab, opened from Scenario setup. */
export async function openCaseRunner(page: Page) {
  await page
    .getByRole("button", { name: "Run a scenario case", exact: true })
    .click();
  return page.getByRole("region", { name: "Run a scenario case", exact: true });
}

/** Show one of the panels beside the map. */
export async function openPanel(page: Page, name: string) {
  await page.getByRole("tab", { name, exact: true }).click();
}

/** The scenario editor starts closed; open it unless it already is. */
export async function openEditor(page: Page) {
  const toggle = page.getByRole("button", {
    name: "Shape the scenario",
    exact: true,
  });
  if ((await toggle.getAttribute("aria-expanded")) !== "true")
    await toggle.click();
}
