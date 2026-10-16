import { expect, test } from "@playwright/test";
import { PASSWORD, balanceChip, freshEmail, mailLink, signIn, signUp } from "./real";

// T087: the browser steps of specs/001-platform-foundation/quickstart.md, against the real API.
// Sections 2 (sign-up, shell, throttling, sign-out everywhere, reset, settings, not found, leave
// guard), 3 (amount rules, abandoned checkout), 4 (public calculator) and 6 (empty usage window).
// The $25 top-up itself is covered by topup.spec.ts (T051).

test.describe.configure({ mode: "serial" });

test("section 2: workspace shell, first-load requests, navigation and settings", async ({ page, request }) => {
  await signUp(page, request);
  await expect(balanceChip(page)).toHaveText("$5.000");

  // FR-020: a fresh load reads only identity and balance.
  const apiCalls = new Set<string>();
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith("/v1/")) apiCalls.add(`${r.method()} ${u.pathname}`);
  });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect([...apiCalls].sort()).toEqual(["GET /v1/billing/balance", "GET /v1/me"]);

  // FR-005: grouped navigation, collapsible to icons with label tooltips.
  const nav = page.getByRole("navigation", { name: "Main" });
  for (const g of ["Build", "Observe", "Quality", "Feedback loop"]) await expect(nav.getByText(g, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Collapse navigation" }).click();
  await nav.getByRole("link", { name: "Datasets" }).hover();
  await expect(page.getByRole("tooltip")).toHaveText("Quality: Datasets");
  await page.getByRole("button", { name: "Expand navigation" }).click();

  // US1.5, FR-017: settings rename and recording default persist; an empty name saves nothing.
  await page.goto("/settings");
  const name = page.getByLabel("Workspace name");
  await name.fill("Quickstart Dental");
  await page.getByRole("switch", { name: "Record calls by default" }).click();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Settings saved", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Workspace name")).toHaveValue("Quickstart Dental");
  await expect(page.getByRole("switch", { name: "Record calls by default" })).toHaveAttribute("aria-checked", "false");
  await page.getByLabel("Workspace name").fill("");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Enter a workspace name.")).toBeVisible();
  await page.getByRole("button", { name: "Discard" }).click();

  // US1.9, FR-021: an edited form asks before reload.
  await page.getByLabel("Workspace name").fill("Unsaved name");
  let prompted = false;
  page.once("dialog", async (d) => {
    prompted = d.type() === "beforeunload";
    await d.dismiss();
  });
  await page.reload({ timeout: 3_000 }).catch(() => undefined);
  expect(prompted).toBe(true);

  // US1.6, US1.7: not-found views inside the shell, no status codes.
  await page.goto("/no-such-page");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to dashboard" })).toHaveAttribute("href", "/dashboard");
  await page.goto("/agents/not-an-id");
  await expect(page.getByRole("heading", { name: "Agent not found" })).toBeVisible();
  await expect(page.getByText(/\b(404|500)\b/)).toHaveCount(0);
});

test("section 2: throttled sign-in says when to retry", async ({ page }) => {
  const email = freshEmail("throttle");
  await page.goto("/login");
  await page.getByLabel("Work email").fill(email);
  for (let i = 0; i < 5; i++) {
    await page.getByLabel("Password", { exact: true }).fill(`wrong-password-${i}`);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
  }
  await page.getByLabel("Password", { exact: true }).fill("wrong-password-6");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("Too many sign-in attempts for this account. You can try again in");
});

test("section 2: signing out in one tab signs out every tab", async ({ page, context, request }) => {
  await signUp(page, request);
  await page.goto("/billing");
  const other = await context.newPage();
  await other.goto("/billing");
  await expect(other.getByRole("heading", { name: "Billing" })).toBeVisible();

  await page.getByRole("button", { name: /^Account menu/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(other).toHaveURL(/\/login\?next=%2Fbilling$/, { timeout: 5_000 });
});

test("section 2: password reset works once", async ({ page, request }) => {
  const email = await signUp(page, request);
  await page.getByRole("button", { name: /^Account menu/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();

  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  const link = await mailLink(request, email, "reset-password");

  await page.goto(link);
  const fresh = `${PASSWORD}-new`;
  await page.getByLabel("New password").fill(fresh);
  await page.getByLabel("Repeat it").fill(fresh);
  await page.getByRole("button", { name: "Save new password" }).click();
  await page.waitForURL(/\/login\?reset=1/);
  await expect(page.getByRole("status")).toContainText("Your password was changed.");
  await signIn(page, email, fresh);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  await page.goto(link);
  await page.getByLabel("New password").fill(`${fresh}-again`);
  await page.getByLabel("Repeat it").fill(`${fresh}-again`);
  await page.getByRole("button", { name: "Save new password" }).click();
  await expect(page.getByRole("heading", { name: "This link has expired" })).toBeVisible();
});

test("section 3: amount rules and an abandoned checkout", async ({ page, request }) => {
  await signUp(page, request);
  await page.goto("/billing");
  const amount = page.getByLabel("Amount", { exact: true });
  for (const [value, reason] of [
    ["4", "The minimum top-up is $5."],
    ["10001", "The maximum top-up is $10,000. Contact sales for larger amounts."],
    ["5.555", "Use whole cents: at most two digits after the point."],
  ]) {
    await amount.fill(value);
    await amount.blur();
    await expect(page.getByRole("alert").filter({ hasText: reason })).toBeVisible();
  }

  await page.getByRole("button", { name: "$100", exact: true }).click();
  await expect(amount).toHaveValue("100.00");
  await expect(page).toHaveURL(/\/billing$/);
  await page.getByRole("button", { name: "Add funds $100.00" }).click();
  await page.waitForURL(/\/dev\/fake-checkout\//);
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.waitForURL(/\/billing\?checkout=cancel+ed/);
  await expect(page.getByText("Checkout was cancelled. Nothing was charged.")).toBeVisible();
  await expect(balanceChip(page)).toHaveText("$5.000");
  const timeline = page.getByRole("region", { name: "Credit transactions, newest first" });
  await expect(timeline.getByRole("listitem")).toHaveCount(1);
  await expect(timeline.getByRole("listitem").first()).toContainText("Trial credit");

  // Section 6: an empty usage window says so, and a window that ends before it starts is refused.
  await page.getByRole("tab", { name: "Usage" }).click();
  await expect(page.getByText("No usage charges yet in this window")).toBeVisible();
  await page.getByLabel("To", { exact: true }).fill("2020-01-01");
  await expect(page.getByText("The end date must be on or after the start date.")).toBeVisible();
});

test("section 4: the public calculator prices the chain as it changes", async ({ page }) => {
  await page.goto("/pricing");
  const perMinute = page.getByTestId("per-minute");
  await expect(perMinute).toHaveText("$0.1050");
  await expect(page.getByTestId("monthly")).toHaveText("$1,050.00");

  await page.getByRole("button", { name: /^Model: .* Change$/ }).click();
  await page
    .getByRole("radio", { name: /GPT-5\.1/ })
    .first()
    .click();
  // Nova-3 0.0085 + GPT-5.1 0.0165 + Flash v2.5 0.0450 + platform 0.0500 (launch catalog).
  await expect(perMinute).toHaveText("$0.1200");

  await page.getByRole("textbox", { name: "Minutes per month" }).fill("20000");
  await expect(page.getByTestId("monthly")).toHaveText("$2,400.00");

  await page.getByRole("button", { name: /^Noise cancellation: .* Change$/ }).click();
  await page.getByRole("radio").nth(1).click();
  await expect(page.getByRole("button", { name: /^Noise cancellation: .* Change$/ })).not.toHaveAccessibleName(/Off\. Change$/);
});
