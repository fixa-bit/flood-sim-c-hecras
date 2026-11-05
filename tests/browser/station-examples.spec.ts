import { expect, test } from "@playwright/test";
import { openEditor } from "./panels";

test("each station shows its own example scenarios, and Warsak loads its below-dam case", async ({
  page,
}) => {
  const warsak = await (
    await page.request.get("/api/assets?site=warsak")
  ).json();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  const examples = page.getByRole("region", { name: "Example scenarios" });
  await expect(
    examples.getByRole("heading", { name: "Nowshera 2022", exact: true }),
  ).toBeVisible();

  await page.getByRole("button", { name: /^Warsak Kabul/ }).click();
  await expect(
    examples.getByRole("heading", {
      name: "Warsak 2022 below the dam",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    examples.getByRole("heading", { name: "Nowshera 2022", exact: true }),
  ).toHaveCount(0);
  await examples
    .getByRole("button", { name: "Load Warsak 2022", exact: true })
    .click();
  await openEditor(page);
  await expect(page.getByLabel("Compute engine")).toHaveValue("LISFLOOD-FP");
  await expect(page.getByLabel("Scenario name", { exact: true })).toHaveValue(
    "Example · Warsak 2022 below the dam",
  );
  if (warsak.dem)
    // Warsak scenarios bind to the Warsak terrain, not Nowshera's.
    await expect(
      page.getByText(`hash ${warsak.dem.sha256.slice(0, 10)}`),
    ).toBeVisible();
  await expect(
    page.getByText(/Runs start once a continuous Warsak Dam release record/),
  ).toBeVisible();

  await page.getByRole("button", { name: /^Tarbela Indus/ }).click();
  await expect(
    examples.getByRole("heading", { name: "Tarbela 2022", exact: true }),
  ).toBeVisible();
  await expect(
    examples.getByRole("button", { name: "Load wetter monsoon", exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
