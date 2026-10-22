import { test, expect } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";

test("downloaded river reach shows actual terrain and public-data study", async ({
  page,
}) => {
  test.skip(
    !existsSync(
      "workspace/downloads/nowshera-2022/study/routing-calibration.json",
    ),
    "Acquire the local study data first.",
  );
  await page.goto("/");
  await expect(page.getByText("FABDEM ~30 m · local terrain")).toBeVisible({
    timeout: 30000,
  });
  await expect(page.locator(".globe")).toHaveAttribute(
    "data-tiles-ready",
    "true",
    { timeout: 30000 },
  );
  await expect(
    page.getByRole("button", { name: "River view", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Camera centered on mapped river water", { exact: false }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/river-terrain-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Data & provenance" }).click();
  await expect(
    page.getByRole("heading", { name: "Upstream routing study · 2022" }),
  ).toBeVisible();
  await expect(page.locator(".study-panel")).toContainText(
    "Routing validation targets are not all met.",
  );
  await expect(page.locator(".study-panel circle")).toHaveCount(15);
  if (
    existsSync(
      "workspace/downloads/nowshera-2022/study/inflow-improvement.json",
    )
  ) {
    const candidate = JSON.parse(
      readFileSync(
        "workspace/downloads/nowshera-2022/study/inflow-improvement.json",
        "utf8",
      ),
    );
    await expect(
      page.getByRole("heading", { name: "Inflow improvement candidate" }),
    ).toBeVisible();
    await expect(page.locator(".inflow-improvement")).toContainText(
      `${candidate.additional_reviewed_observations} additional timed upstream observations reviewed.`,
    );
    if (candidate.scores) {
      const score = candidate.scores.validation;
      await expect(page.locator(".inflow-improvement")).toContainText(
        `${score.baseline.kge.toFixed(3)} → ${score.candidate.kge.toFixed(3)}`,
      );
    }
    await expect(page.locator(".inflow-improvement")).toContainText(
      "has not been applied to the HEC-RAS or LISFLOOD results",
    );
  }
  await page.screenshot({
    path: "test-results/upstream-routing-study.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  const widths = await page.evaluate(() => ({
    content: document.documentElement.scrollWidth,
    viewport: innerWidth,
  }));
  expect(widths.content).toBeLessThanOrEqual(widths.viewport);
});
