import { expect, test } from "@playwright/test";

test("Warsak model results open the satellite-checked snapshot with speed and the observed extent", async ({
  page,
}) => {
  const results = await (await page.request.get("/api/results")).json();
  const snapshot = results.find((r: { id: string }) =>
    r.id.startsWith("warsak-snapshot-20220825"),
  );
  test.skip(
    !snapshot,
    "Run python -m server.warsak_snapshot sweep and publish first.",
  );
  await page.setViewportSize({ width: 1366, height: 768 });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("button", { name: /^Warsak Kabul/ }).click();
  const open = page.getByRole("button", { name: /^Model results/ });
  // Wait for the published result list before asking for this station's result.
  await expect(open).toContainText(String(results.length));
  await open.click();
  await expect(page.getByLabel("Result A", { exact: true })).toHaveValue(
    /^warsak-snapshot-/,
  );
  const details = page.locator(".result-details");
  await expect(details).toContainText(/Satellite check at .* CSI \d\.\d\d/);
  // The observed extent belongs to the final steady frame.
  const last = String(snapshot.frame_count - 1);
  await page.getByLabel("Model timestep", { exact: true }).fill(last);
  const observed = page.getByRole("checkbox", {
    name: "Observed extent at matched acquisition time",
  });
  await expect(observed).toBeEnabled();
  await observed.check();
  await page
    .getByLabel("Model field", { exact: true })
    .selectOption("velocity");
  await expect(details).not.toContainText(
    "This field was not exported for this frame.",
  );
  await expect(page.locator(".globe")).toHaveAttribute(
    "data-tiles-ready",
    "true",
    { timeout: 45000 },
  );
  await page.screenshot({ path: "test-results/warsak-snapshot.png" });
  expect(errors).toEqual([]);
});
