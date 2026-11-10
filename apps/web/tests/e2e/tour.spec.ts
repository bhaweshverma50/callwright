import { expect, test, type Page } from "@playwright/test";

// Spec 013: the guided setup tour, against the mock API. A fresh account gets the welcome card.
async function signUpFresh(page: Page) {
  const email = `tour.${Date.now()}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("correct-horse-9");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText(/check your email|we sent/i).first()).toBeVisible();
  await page.goto(`/verify-email?token_hash=verify-${email}`);
  await page.waitForURL("**/dashboard");
}

const title = (page: Page) => page.locator("#tour-title");
const next = (page: Page) => page.getByRole("button", { name: "Next", exact: true }).click();

test("a new user follows the tour from the welcome card to the recap", async ({ page }) => {
  test.setTimeout(90_000);
  await page.context().grantPermissions(["microphone"]);
  await signUpFresh(page);
  await page.getByRole("dialog", { name: "Set up your first agent" }).getByRole("button", { name: "Start tour" }).click();

  await expect(title(page)).toHaveText("Start with an agent");
  await expect(page).toHaveURL(/\/agents$/);
  // The real action: the page's own link moves the tour on.
  await page.getByRole("link", { name: "Start from a template" }).click();
  await expect(title(page)).toHaveText("Pick a template");

  await page.getByRole("button", { name: "Choose one for me" }).click();
  await expect(page).toHaveURL(/\/agents\/agt_[0-9A-Z]{26}\/edit$/);
  await expect(title(page)).toHaveText("Tell it what to do");
  await expect(page.locator("#f-prompt")).toBeVisible(); // the editor has loaded the step's target
  await next(page);

  await expect(title(page)).toHaveText("Choose how it sounds");
  await page.getByRole("button", { name: "Open the Voice tab" }).click();
  await expect(title(page)).toHaveText("See the price per minute");
  await next(page);

  await expect(title(page)).toHaveText("Talk to it");
  await expect(page).toHaveURL(/\/testing$/);
  await next(page);

  await expect(title(page)).toHaveText("Publish it");
  await page.getByRole("button", { name: "Publish for me" }).click();
  await expect(page.getByText("Live on version 1")).toBeVisible();
  await expect(title(page)).toHaveText("Put it on a number");
  await expect(page).toHaveURL(/\/phone-numbers$/);
  await next(page);
  await expect(title(page)).toHaveText("Find every call");
  await next(page);
  await expect(title(page)).toHaveText("Check the quality");
  await next(page);

  await expect(title(page)).toHaveText("Your agent is set up");
  await page.getByRole("button", { name: "Finish" }).click();
  await expect(title(page)).toHaveCount(0);

  // Completed is saved on the server: a reload offers nothing.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Review" })).toBeVisible();
  await page.waitForTimeout(800);
  await expect(page.getByRole("dialog", { name: "Set up your first agent" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Guided setup paused" })).toHaveCount(0);
});

test("a new user skips the tour, and can start it again from the account menu", async ({ page }) => {
  await signUpFresh(page);
  await page.getByRole("button", { name: "Start tour" }).click();
  await expect(title(page)).toHaveText("Start with an agent");
  await next(page);
  await expect(title(page)).toHaveText("Pick a template");
  await page.getByRole("button", { name: "Skip tour" }).click();
  await expect(title(page)).toHaveCount(0);

  await page.reload();
  await expect(page.getByRole("heading", { name: "Start a single-prompt agent" })).toBeVisible();
  await page.waitForTimeout(800);
  await expect(page.getByRole("dialog", { name: "Set up your first agent" })).toHaveCount(0);
  await expect(title(page)).toHaveCount(0);

  await page.getByRole("button", { name: /Account menu for/ }).click();
  await page.getByRole("menuitem", { name: "Guided setup" }).click();
  await expect(title(page)).toHaveText("Start with an agent");
  await expect(page).toHaveURL(/\/agents$/);
});
