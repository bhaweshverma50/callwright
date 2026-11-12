import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

// 022 T090 against the mock API: connect Google, add a Drive folder to a knowledge base, see the
// source sync, Sync now, and open its history.
test("connect Google and sync a Drive folder into a knowledge base", async ({ page }) => {
  await signIn(page, "/settings/connections");
  await page.getByRole("button", { name: "Connect Google" }).click();
  await expect(page.getByText("Google connected", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/settings\/connections$/);
  await expect(page.getByRole("heading", { name: "drive.owner@example.com" })).toBeVisible();
  await expect(page.getByText("Drive (read-only)")).toBeVisible();
  await expect(page.getByText("Healthy")).toBeVisible();

  // In-app navigation: a page load would reset the mock API's in-memory connection.
  await page.getByRole("link", { name: "Knowledge", exact: true }).first().click();
  await page.getByRole("button", { name: "New knowledge base" }).first().click();
  await page.getByLabel("Name").fill("Clinic policies");
  await page.getByRole("button", { name: "Create" }).click();
  await page.waitForURL(/\/knowledge-base\/kb_/);
  await expect(page.getByRole("dialog")).toBeVisible(); // the upload dialog opens after creating
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.getByRole("button", { name: "Add Google Drive source" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Add a Google Drive source" });
  await dialog.getByRole("button", { name: /Clinic policies/ }).click();
  await expect(dialog.getByRole("switch")).toBeChecked();
  await dialog.getByRole("button", { name: "Sync Clinic policies" }).click();
  await expect(page.getByText("Drive source added", { exact: true })).toBeVisible();

  const card = page.getByRole("region", { name: "Source Clinic policies" });
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "History" }).click();
  await expect(page.getByRole("list", { name: "Sync runs" }).getByText(/First sync/)).toBeVisible();
});
