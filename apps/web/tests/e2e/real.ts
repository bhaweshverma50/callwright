import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** Helpers for journeys against the real API (project `real`, see playwright.config.ts). */
export const API = (process.env.E2E_REAL_API_URL ?? "http://localhost:8100/v1").replace(/\/$/, "");
export const PASSWORD = "correct-horse-battery-9";

export function freshEmail(tag: string) {
  return `e2e+${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

interface MailItem {
  to: string;
  kind: string;
  link: string;
}

/** The newest link of a kind sent to an address, from the local identity provider's outbox. */
export async function mailLink(request: APIRequestContext, to: string, kind: "verify_email" | "recovery" | string): Promise<string> {
  let found: MailItem | undefined;
  await expect
    .poll(
      async () => {
        const res = await request.get(`${API}/dev/mail`);
        const body = (await res.json()) as { items: MailItem[] };
        found = body.items.find((m) => m.to === to.toLowerCase() && (m.kind === kind || m.link.includes(kind)));
        return Boolean(found);
      },
      { timeout: 10_000, message: `no ${kind} mail for ${to}` },
    )
    .toBe(true);
  return found!.link;
}

/** Registers through the UI, opens the verification link from the mail catcher, lands on the dashboard. */
export async function signUp(page: Page, request: APIRequestContext, email = freshEmail("user")) {
  await page.goto("/register");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  const link = await mailLink(request, email, "verify-email");
  await page.goto(link);
  await page.waitForURL("**/dashboard");
  return email;
}

export async function signIn(page: Page, email: string, password = PASSWORD, next = "/dashboard") {
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(`**${next}`);
}

export const balanceChip = (page: Page) => page.getByRole("link", { name: /^Balance .* Open billing$/ });
