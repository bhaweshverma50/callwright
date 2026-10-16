#!/usr/bin/env node
// Screenshots of key pages in light and dark themes, against a running mock-mode dev server.
//
//   pnpm dev:mock            (in another terminal; serves http://localhost:5180)
//   pnpm screens             writes docs/screens/<page>-<theme>.png
//
// SCREENS_BASE overrides the server URL; SCREENS_ONLY=billing,login limits the pages.
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, "../docs/screens");
mkdirSync(out, { recursive: true });
const BASE = process.env.SCREENS_BASE ?? "http://localhost:5180";
const ONLY = process.env.SCREENS_ONLY?.split(",").filter(Boolean);

const DEMO = { email: "ops@halcyon-dental.com", password: "correct-horse-9" };

/** name, path, needs sign-in, full page, optional action before the shot */
const PAGES = [
  { name: "home", path: "/", full: true },
  { name: "pricing", path: "/pricing", full: true },
  { name: "login", path: "/login" },
  { name: "register", path: "/register" },
  { name: "dashboard", path: "/dashboard", auth: true },
  { name: "dashboard-rail-expanded", path: "/dashboard", auth: true, before: async (p) => p.keyboard.press("[") },
  { name: "billing", path: "/billing", auth: true, full: true },
  {
    name: "billing-breakdown",
    path: "/billing",
    auth: true,
    before: async (p) => {
      await p.getByRole("button", { name: "Show cost breakdown" }).first().click();
      await p.waitForTimeout(250);
    },
  },
  {
    name: "billing-topup-invalid",
    path: "/billing",
    auth: true,
    before: async (p) => {
      await p.getByLabel("Amount", { exact: true }).fill("4");
      await p.getByLabel("Amount", { exact: true }).blur();
    },
  },
  { name: "billing-usage", path: "/billing?tab=usage", auth: true, full: true },
  { name: "settings", path: "/settings", auth: true },
  { name: "placeholder-agents", path: "/agents", auth: true },
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

const browser = await chromium.launch();
try {
  for (const theme of ["light", "dark"]) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, colorScheme: theme });
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
      if (s.auth && !signedIn) {
        await signIn(page);
        signedIn = true;
      }
      await page.goto(`${BASE}${s.path}`);
      await page.waitForLoadState("networkidle");
      await page.evaluate(() => document.fonts.ready);
      if (s.before) await s.before(page);
      await page.waitForTimeout(300);
      const file = join(out, `${s.name}-${theme}.png`);
      await page.screenshot({ path: file, fullPage: Boolean(s.full) });
      if (s.name === "dashboard-rail-expanded") await page.keyboard.press("[");
      console.log(file);
    }
    await ctx.close();
  }
} finally {
  await browser.close();
}
