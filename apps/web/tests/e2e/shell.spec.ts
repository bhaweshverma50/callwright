import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

// T097: shell journey (FR-005, FR-018, FR-019, FR-020).
test("first load reads only identity and balance; no feature credentials", async ({ page }) => {
  await signIn(page);
  const apiCalls: string[] = [];
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith("/v1/")) apiCalls.push(`${r.method()} ${u.pathname}`);
  });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(new Set(apiCalls)).toEqual(new Set(["GET /v1/me", "GET /v1/billing/balance"]));
});

test("unknown address shows not found inside the shell", async ({ page }) => {
  await signIn(page);
  await page.goto("/no-such-page");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
});

test("malformed record id names the record kind, with no status code", async ({ page }) => {
  await signIn(page);
  await page.goto("/agents/agt_bad");
  await expect(page.getByRole("heading", { name: "Agent not found" })).toBeVisible();
  await expect(page.getByText(/\b404\b/)).toHaveCount(0);
});

test("settings save persists after reload", async ({ page }) => {
  await signIn(page, "/settings");
  const name = page.getByLabel("Workspace name");
  await name.fill("Halcyon Dental East");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Settings saved")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Workspace name")).toHaveValue("Halcyon Dental East");
});

test("balance chip opens Billing", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: /^Balance .* Open billing$/ }).click();
  await expect(page).toHaveURL(/\/billing$/);
  await expect(page.getByRole("heading", { name: "Billing" })).toBeVisible();
});
