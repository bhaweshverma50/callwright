import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

// T099 (FR-021) on the Settings form. Never-saved create forms arrive with 002 and reuse LeaveGuard.
test("edited form prompts on in-app navigation; Stay keeps input, Leave discards", async ({ page }) => {
  await signIn(page, "/settings");
  await page.getByLabel("Workspace name").fill("Unsaved name");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Billing" }).click();
  const dialog = page.getByRole("alertdialog", { name: "Leave without saving?" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Stay" }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByLabel("Workspace name")).toHaveValue("Unsaved name");

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Billing" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Leave" }).click();
  await expect(page).toHaveURL(/\/billing$/);
});

test("edited form prompts on reload (beforeunload)", async ({ page }) => {
  await signIn(page, "/settings");
  await page.getByLabel("Workspace name").fill("Unsaved name");
  // Chromium only shows beforeunload after a user gesture on the page, which fill() provides.
  let prompted = false;
  page.once("dialog", async (d) => {
    prompted = d.type() === "beforeunload";
    await d.dismiss();
  });
  await page.reload({ timeout: 3_000 }).catch(() => undefined);
  expect(prompted).toBe(true);
  await expect(page.getByLabel("Workspace name")).toHaveValue("Unsaved name");
});

test("clean form leaves without a prompt", async ({ page }) => {
  await signIn(page, "/settings");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Billing" }).click();
  await expect(page).toHaveURL(/\/billing$/);
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
});
