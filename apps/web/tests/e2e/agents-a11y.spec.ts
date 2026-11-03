import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./helpers";

// 002 T085: keyboard paths through the agent editor that unit tests cannot see (real focus,
// real animations, the whole page).
async function openFrontDesk(page: Page) {
  await signIn(page, "/agents");
  await page.getByRole("link", { name: "Front desk agent" }).click();
  await expect(page.getByLabel("Agent name")).toHaveValue("Front desk agent");
}

test("sliders are named by their row, and dialogs return focus to their opener", async ({ page }) => {
  await openFrontDesk(page);
  await page.getByRole("tab", { name: "Voice" }).click();
  await expect(page.getByRole("slider", { name: "Speed" })).toBeVisible();

  await page.getByRole("tab", { name: "Basics" }).click();
  const history = page.getByRole("button", { name: "History" });
  await history.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: "Version history" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(history).toBeFocused();
});

test("saving from the keyboard keeps focus on the page", async ({ page }) => {
  await openFrontDesk(page);
  await page.getByLabel("Agent name").fill("Front desk agent, renamed");
  const save = page.getByRole("button", { name: "Save", exact: true });
  await save.focus();
  await page.keyboard.press("Enter");
  // The Save button leaves the bar once the form is clean; focus lands on the saved status.
  await expect(page.locator("[aria-live=polite]", { hasText: "All changes saved" })).toBeFocused();
});
