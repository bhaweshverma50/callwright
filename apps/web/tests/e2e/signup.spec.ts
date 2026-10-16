import { expect, test } from "@playwright/test";
import { balanceChip, signUp } from "./real";

// T034 (US1.1, FR-001 to FR-005): register, verify through the mail catcher, land on the dashboard
// with the $5.00 trial credit and every product area in the navigation. Real API only.
test("register, verify by email and land in a funded workspace", async ({ page, request }) => {
  const email = await signUp(page, request);

  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(balanceChip(page)).toHaveText("$5.000");
  await expect(balanceChip(page)).toHaveAttribute("href", "/billing");

  const nav = page.getByRole("navigation", { name: "Main" });
  const areas = ["Dashboard", "Agents", "Calls", "Channels", "Knowledge", "Datasets", "Simulations", "Review", "Calibration", "Issues", "Billing"];
  await expect(nav.getByRole("link")).toHaveCount(11);
  for (const a of areas) await expect(nav.getByRole("link", { name: a, exact: true })).toBeVisible();

  await page.getByRole("button", { name: `Account menu for ${email.toLowerCase()}` }).click();
  await expect(page.getByRole("menuitem", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Sign out" })).toBeVisible();
});
