import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

// T057 (US3): history, compare with readable labels and a line diff, publish, restore in 3 clicks.
test("compare, restore and publish versions", async ({ page }) => {
  await signIn(page, "/agents");
  await page.getByRole("link", { name: "Front desk agent" }).click();
  await expect(page.getByLabel("Agent name")).toHaveValue("Front desk agent");

  await page.getByRole("button", { name: "History" }).click();
  const drawer = page.getByRole("dialog", { name: "Version history" });
  const versions = drawer.getByRole("list", { name: "Versions, newest first" }).getByRole("listitem");
  await expect(versions).toHaveCount(3);
  await expect(versions.nth(1).getByText("Live", { exact: true })).toBeVisible();

  // Compare version 1 with version 2.
  await versions.nth(2).getByRole("button", { name: "Compare" }).click();
  await page.getByRole("menuitem", { name: "With the live version (2)" }).click();
  await expect(page.getByText("System prompt")).toBeVisible();
  await expect(page.getByText("Greeting", { exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: "Line changes" }).first()).toBeVisible();
  await page.getByRole("button", { name: "All versions" }).click();

  // Restore version 1 (History, Restore, Restore to draft).
  await versions.nth(2).getByRole("button", { name: "Restore" }).click();
  await page.getByRole("dialog", { name: "Restore version 1?" }).getByRole("button", { name: "Restore to draft" }).click();
  await expect(page.getByText("Version 1 restored as version 4").first()).toBeVisible();
  await expect(page.getByText("Version 4", { exact: true })).toBeVisible();
  await expect(page.getByText("Live on version 2")).toBeVisible();

  await page.getByRole("button", { name: "History" }).click();
  await expect(versions).toHaveCount(4);
  await expect(versions.nth(0).getByText("Restored from version 1")).toBeVisible();
  await expect(versions.nth(2).getByText("Live", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");

  // Publish the restored version from the header.
  await page.getByRole("button", { name: "Publish version 4" }).click();
  await expect(page.getByText("Version 4 published").first()).toBeVisible();
  await expect(page.getByText("Live on version 4")).toBeVisible();
});
