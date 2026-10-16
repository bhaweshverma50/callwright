import { expect, test } from "@playwright/test";
import { balanceChip, signUp } from "./real";

// T051 (US2.1, US2.5, SC-002): $4 is refused inline; a $25 top-up through hosted checkout (the
// dev fake checkout page) shows a $30.00 balance and the new row within 10 s. Real API only.
test("refuses $4, then a $25 top-up lands within 10 seconds", async ({ page, request }) => {
  await signUp(page, request);
  await page.goto("/billing");

  const amount = page.getByLabel("Amount", { exact: true });
  await amount.fill("4");
  await amount.blur();
  await expect(page.getByRole("alert").filter({ hasText: "The minimum top-up is $5." })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Add funds$/ }).last()).toBeDisabled();

  await page.getByRole("button", { name: "$25", exact: true }).click();
  await expect(amount).toHaveValue("25.00");
  await page.getByRole("button", { name: "Add funds $25.00" }).click();

  // Hosted checkout (STRIPE_MODE=fake serves it from the API).
  await page.waitForURL(/\/dev\/fake-checkout\//);
  await page.getByRole("button", { name: "Pay $25.00" }).click();

  await page.waitForURL(/\/billing\?checkout=success/);
  const paidAt = Date.now();
  await expect(balanceChip(page)).toHaveText("$30.000", { timeout: 10_000 });
  const timeline = page.getByRole("region", { name: "Credit transactions, newest first" });
  const row = timeline.getByRole("listitem").filter({ hasText: "Top-up" }).first();
  await expect(row).toContainText("+$25.000", { timeout: 10_000 });
  await expect(row).toContainText("$30.000");
  expect(Date.now() - paidAt).toBeLessThan(10_000);
  await expect(page.getByText("Funds added", { exact: true })).toBeVisible();
});
