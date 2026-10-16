#!/usr/bin/env node
// Screenshots of every page in light and dark themes, at desktop (1440) and mobile (390) widths,
// against a running mock-mode dev server.
//
//   pnpm dev:mock            (in another terminal; serves http://localhost:5180)
//   pnpm screens             writes docs/screens/<page>-<theme>[-mobile].png
//
// SCREENS_BASE overrides the server URL; SCREENS_ONLY=billing,login limits the pages;
// SCREENS_VIEWPORTS=desktop or mobile limits the widths.
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, "../docs/screens");
mkdirSync(out, { recursive: true });
const BASE = process.env.SCREENS_BASE ?? "http://localhost:5180";
const ONLY = process.env.SCREENS_ONLY?.split(",").filter(Boolean);
const VIEWPORTS = (process.env.SCREENS_VIEWPORTS ?? "desktop,mobile").split(",");

const DEMO = { email: "ops@halcyon-dental.com", password: "correct-horse-9" };

/** name, path, needs sign-in, full page, optional action before the shot (gets page and isMobile) */
const PAGES = [
  // The hero call plays for 16 s; shoot it mid-call.
  { name: "home", path: "/", full: true, before: async (p) => p.waitForTimeout(12_500) },
  { name: "pricing", path: "/pricing", full: true },
  {
    name: "pricing-choose-model",
    path: "/pricing",
    before: async (p) => {
      await p.getByRole("button", { name: /^Model: .* Change$/ }).click();
      await p.waitForTimeout(400);
    },
  },
  { name: "enterprise", path: "/enterprise", full: true },
  { name: "privacy", path: "/privacy", full: true },
  { name: "terms", path: "/terms", full: true },
  { name: "login", path: "/login" },
  { name: "register", path: "/register" },
  { name: "forgot-password", path: "/forgot-password" },
  { name: "verify-email-expired", path: "/verify-email" },
  { name: "reset-password", path: "/reset-password?token_hash=reset-ops%40halcyon-dental.com" },
  { name: "dashboard", path: "/dashboard", auth: true, full: true },
  {
    name: "dashboard-collapsed",
    path: "/dashboard",
    auth: true,
    desktopOnly: true,
    before: async (p) => {
      await p.keyboard.press("[");
      await p.waitForTimeout(800);
    },
    after: async (p) => p.keyboard.press("["),
  },
  {
    name: "dashboard-nav-open",
    path: "/dashboard",
    auth: true,
    mobileOnly: true,
    before: async (p) => {
      await p.getByRole("button", { name: "Open navigation" }).click();
      await p.waitForTimeout(400);
    },
  },
  { name: "billing", path: "/billing", auth: true, full: true, before: async (p) => p.waitForTimeout(900) },
  {
    name: "billing-breakdown",
    path: "/billing",
    auth: true,
    before: async (p) => {
      await p
        .getByRole("button", { name: /Show cost breakdown$/ })
        .first()
        .click();
      await p.waitForTimeout(500);
    },
  },
  {
    name: "billing-topup-invalid",
    path: "/billing",
    auth: true,
    before: async (p) => {
      const amount = p.getByLabel("Amount", { exact: true });
      await amount.fill("4");
      await amount.blur();
      await amount.scrollIntoViewIfNeeded();
      await p.waitForTimeout(300);
    },
  },
  { name: "billing-usage", path: "/billing?tab=usage", auth: true, full: true },
  { name: "settings", path: "/settings", auth: true },
  { name: "placeholder-agents", path: "/agents", auth: true, full: true },
  { name: "not-found", path: "/no-such-page", auth: true },
  { name: "components", path: "/dev/components", full: true },
];

async function signIn(page) {
  await page.goto(`${BASE}/login`);
  await page.getByLabel("Work email").fill(DEMO.email);
  await page.getByLabel("Password", { exact: true }).fill(DEMO.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/dashboard");
}

const SIZES = {
  desktop: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
  mobile: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
};

const browser = await chromium.launch();
try {
  for (const size of VIEWPORTS) {
    for (const theme of ["light", "dark"]) {
      const ctx = await browser.newContext({ ...SIZES[size], colorScheme: theme });
      await ctx.addInitScript((t) => {
        try {
          localStorage.setItem("cw.theme", t);
        } catch {
          /* ignore */
        }
      }, theme);
      const page = await ctx.newPage();
      let signedIn = false;
      for (const s of PAGES) {
        if (ONLY && !ONLY.includes(s.name)) continue;
        if (s.desktopOnly && size !== "desktop") continue;
        if (s.mobileOnly && size !== "mobile") continue;
        if (s.auth && !signedIn) {
          await signIn(page);
          signedIn = true;
        }
        await page.goto(`${BASE}${s.path}`);
        await page.waitForLoadState("networkidle");
        await page.evaluate(() => document.fonts.ready);
        await page.waitForTimeout(500);
        if (s.before) await s.before(page);
        await page.waitForTimeout(300);
        const file = join(out, `${s.name}-${theme}${size === "mobile" ? "-mobile" : ""}.png`);
        await page.screenshot({ path: file, fullPage: Boolean(s.full) });
        if (s.after) await s.after(page);
        console.log(file);
      }
      await ctx.close();
    }
  }
} finally {
  await browser.close();
}
