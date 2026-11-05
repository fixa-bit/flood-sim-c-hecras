import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { openCaseRunner, openPanel } from "./panels";

const RESULT = "nowshera-hecras-0b012877-f7bc61d16eb7";

async function fitsOneScreen(page: Page) {
  const [content, viewport] = await page.evaluate(() => [
    document.documentElement.scrollHeight,
    window.innerHeight,
  ]);
  expect(content).toBeLessThanOrEqual(viewport);
}

test("domain overview fits one laptop screen with setup, runner and simulation panels beside the map", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await fitsOneScreen(page);

  // The scenario editor starts closed and opens beside the panels on demand.
  const editor = page.getByRole("complementary", { name: "Scenario editor" });
  const toggle = page.getByRole("button", {
    name: "Shape the scenario",
    exact: true,
  });
  await expect(editor).toBeHidden();
  const closedWidth = (await page.locator(".globe-shell").boundingBox())!.width;
  await toggle.click();
  await expect(editor).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await fitsOneScreen(page);
  await expect
    .poll(async () => (await page.locator(".globe-shell").boundingBox())!.width)
    .toBeLessThan(closedWidth - 150);
  await page
    .getByRole("button", { name: "Close scenario editor", exact: true })
    .click();
  await expect(editor).toBeHidden();

  await expect(
    page.getByRole("tab", { name: "Scenario setup", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(
    page.getByRole("heading", { name: "Example scenarios", exact: true }),
  ).toBeVisible();

  // The runner is not a tab until its button is pressed, and can be closed.
  await expect(
    page.getByRole("tab", { name: "Run scenario case", exact: true }),
  ).toHaveCount(0);
  const runner = await openCaseRunner(page);
  await expect(runner).toBeVisible();
  await expect(
    page.getByRole("tab", { name: "Run scenario case", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page
    .getByRole("button", { name: "Close scenario case runner", exact: true })
    .click();
  await expect(
    page.getByRole("tab", { name: "Run scenario case", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Example scenarios", exact: true }),
  ).toBeVisible();

  // Simulation shows the hydrograph and network together, as separate cards.
  await openPanel(page, "Simulation");
  await expect(page.getByText("Hydrograph awaits model output")).toBeVisible();
  await expect(page.locator(".live-panel .network-section")).toBeVisible();
  await fitsOneScreen(page);

  // Hiding the panels gives the map the room.
  const before = (await page.locator(".globe-shell").boundingBox())!.width;
  await page.getByRole("button", { name: /Hide panels/ }).click();
  await expect
    .poll(async () => (await page.locator(".globe-shell").boundingBox())!.width)
    .toBeGreaterThan(before + 200);
  await page.getByRole("button", { name: /Panels/ }).click();
  await expect(page.locator(".live-panel")).toBeVisible();
  await page.screenshot({ path: "test-results/layout-domain.png" });
  expect(errors).toEqual([]);
});

test("model results show impact, hydrograph and network together, and domain overview returns to setup", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  const results = await (await page.request.get("/api/results")).json();
  test.skip(
    !results.some((item: { id: string }) => item.id === RESULT),
    "Publish the HEC-RAS case first.",
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Model results" }).click();
  await page.getByLabel("Result A", { exact: true }).selectOption(RESULT);
  await expect(
    page.getByRole("tab", { name: "Simulation", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  const live = page.locator(".live-panel");
  await expect(
    live.getByRole("region", { name: "Impact and tributaries" }),
  ).toBeVisible();
  await expect(live.locator(".hydrograph-section")).toBeVisible();
  await expect(live.locator(".network-section")).toBeVisible();
  await fitsOneScreen(page);

  // Upstream -> downstream reads left to right on one row.
  const cards = live.locator(".network-cards > div");
  await expect(cards).toHaveCount(3);
  const tops = await cards.evaluateAll((items) =>
    items.map((item) => Math.round(item.getBoundingClientRect().top)),
  );
  expect(new Set(tops).size).toBe(1);

  // The exposure pane resizes by dragging its bar, and a double-click shows
  // all of it without inner scrolling.
  const pane = live.locator(".resizable-pane-body");
  const splitter = live.getByRole("separator", {
    name: "Resize exposure and streams",
  });
  const start = (await pane.boundingBox())!.height;
  const bar = (await splitter.boundingBox())!;
  await page.mouse.move(bar.x + bar.width / 2, bar.y + bar.height / 2);
  await page.mouse.down();
  await page.mouse.move(bar.x + bar.width / 2, bar.y + 120, { steps: 6 });
  await page.mouse.up();
  await expect
    .poll(async () => (await pane.boundingBox())!.height)
    .toBeGreaterThan(start + 80);
  await splitter.dblclick();
  await expect
    .poll(() => pane.evaluate((el) => el.scrollHeight - el.clientHeight))
    .toBeLessThanOrEqual(1);
  await page.screenshot({ path: "test-results/layout-results.png" });

  await page
    .locator(".map-toolbar")
    .getByRole("button", { name: "Domain overview", exact: true })
    .click();
  await expect(
    page.getByRole("tab", { name: "Scenario setup", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Result A", { exact: true })).toHaveCount(0);
  await fitsOneScreen(page);
});
