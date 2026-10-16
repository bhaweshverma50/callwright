import type { Page } from "@playwright/test";

export const DEMO = { email: "ops@halcyon-dental.com", password: "correct-horse-9" };

export async function signIn(page: Page, next = "/dashboard") {
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("Work email").fill(DEMO.email);
  await page.getByLabel("Password", { exact: true }).fill(DEMO.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(`**${next}`);
}
