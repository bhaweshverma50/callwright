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
const out = process.env.SCREENS_OUT ? resolve(process.env.SCREENS_OUT) : resolve(here, "../docs/screens");
mkdirSync(out, { recursive: true });
const BASE = process.env.SCREENS_BASE ?? "http://localhost:5180";
const ONLY = process.env.SCREENS_ONLY?.split(",").filter(Boolean);
const VIEWPORTS = (process.env.SCREENS_VIEWPORTS ?? "desktop,mobile").split(",");

const DEMO = { email: "ops@halcyon-dental.com", password: "correct-horse-9" };

async function openAgent(p, name = "Front desk agent", tab) {
  await p.getByRole("link", { name }).first().click();
  await p.waitForURL("**/edit");
  await p.waitForLoadState("networkidle");
  if (tab) await p.getByRole("tab", { name: tab }).click();
  await p.waitForTimeout(700);
}

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
  { name: "agents", path: "/agents", auth: true, full: true, before: async (p) => p.waitForTimeout(600) },
  {
    name: "agents-search-empty",
    path: "/agents",
    auth: true,
    before: async (p) => {
      await p.getByLabel("Search agents by name or agent ID").fill("zzz");
      await p.waitForTimeout(700);
    },
  },
  {
    name: "agents-empty",
    path: "/agents",
    auth: true,
    before: async (p) => {
      // Empty the demo workspace for one shot, then put it back.
      await p.evaluate(() => {
        const raw = localStorage.getItem("cw.mockdb.v2");
        window.__mockBackup = raw;
        const db = JSON.parse(raw);
        db.agentsStore.agents.forEach((a) => (a.deleted_at = new Date().toISOString()));
        localStorage.setItem("cw.mockdb.v2", JSON.stringify(db));
      });
      const backup = await p.evaluate(() => window.__mockBackup);
      await p.reload();
      await p.waitForLoadState("networkidle");
      await p.evaluate((b) => localStorage.setItem("cw.mockdb.v2", b), backup);
      await p.waitForTimeout(500);
    },
    after: async (p) => {
      await p.reload();
      await p.waitForLoadState("networkidle");
    },
  },
  { name: "agents-new", path: "/agents/new", auth: true, full: true, before: async (p) => p.waitForTimeout(400) },
  { name: "agents-templates", path: "/agents/templates", auth: true, full: true, before: async (p) => p.waitForTimeout(500) },
  {
    name: "agents-template-preview",
    path: "/agents/templates",
    auth: true,
    before: async (p) => {
      await p.getByRole("button", { name: /Symptom triage and booking/ }).click();
      await p.waitForTimeout(700);
    },
  },
  { name: "agent-create", tall: true, path: "/agents/new/single", auth: true, full: true, before: async (p) => p.waitForTimeout(900) },
  {
    name: "agent-create-errors",
    path: "/agents/new/single",
    auth: true,
    before: async (p) => {
      await p.waitForTimeout(600);
      await p.getByRole("button", { name: "Create agent" }).click();
      await p.waitForTimeout(800);
    },
  },
  { name: "agent-editor", tall: true, path: "/agents", auth: true, full: true, before: async (p) => openAgent(p) },
  {
    name: "agent-editor-voice",
    tall: true,
    path: "/agents",
    auth: true,
    full: true,
    before: async (p) => openAgent(p, "Front desk agent", "Voice and speech"),
  },
  {
    name: "agent-editor-behaviour",
    tall: true,
    path: "/agents",
    auth: true,
    full: true,
    before: async (p) => openAgent(p, "Front desk agent", "Call behaviour"),
  },
  {
    name: "agent-editor-advanced",
    tall: true,
    path: "/agents",
    auth: true,
    full: true,
    before: async (p) => {
      await openAgent(p, "Front desk agent", "Advanced");
      for (const name of ["Detect voicemail", "Listen for keypad input", "Background audio"]) await p.getByRole("switch", { name }).click();
      await p.getByRole("radio", { name: "Leave a message" }).click();
      await p.waitForTimeout(500);
    },
  },
  {
    name: "agent-voice-picker",
    path: "/agents",
    auth: true,
    before: async (p) => {
      await openAgent(p, "Front desk agent", "Voice and speech");
      await p.getByRole("button", { name: "Change voice" }).click();
      await p.waitForTimeout(800);
    },
  },
  {
    name: "agent-history",
    path: "/agents",
    auth: true,
    before: async (p) => {
      await openAgent(p);
      await p.getByRole("button", { name: "History" }).click();
      await p.waitForTimeout(900);
    },
  },
  {
    name: "agent-compare",
    path: "/agents",
    auth: true,
    before: async (p) => {
      await openAgent(p);
      await p.getByRole("button", { name: "History" }).click();
      await p.waitForTimeout(600);
      await p.getByRole("button", { name: "Compare" }).last().click();
      await p
        .getByRole("menuitem", { name: /With version|With the live/ })
        .first()
        .click();
      await p.waitForTimeout(900);
    },
  },
  {
    name: "agent-assistant",
    path: "/agents",
    auth: true,
    before: async (p) => {
      await openAgent(p);
      await p.getByRole("button", { name: "Write with AI" }).click();
      await p.getByRole("button", { name: "Make the tone warmer" }).click();
      await p.waitForTimeout(2200);
    },
  },
  // Issues and auto-fix (spec 009).
  { name: "issues", path: "/issues", auth: true, full: true },
  {
    name: "issues-agent",
    path: "/issues",
    auth: true,
    full: true,
    before: async (p) => {
      await p.getByRole("combobox", { name: "Agent" }).click();
      await p.getByRole("option", { name: "Front desk agent" }).click();
      await p.getByRole("button", { name: "Detect issues" }).click();
      await p.waitForTimeout(6000);
    },
  },
  ...[
    ["issue-validated", "Agent quotes prices"],
    ["issue-flow", "Agent skips the confirm step"],
    ["issue-applied", "Agent transfers billing"],
    ["issue-open", "Agent books appointments"],
  ].map(([name, title]) => ({
    name,
    path: "/issues",
    auth: true,
    full: true,
    before: async (p) => {
      await p.getByRole("link", { name: new RegExp(title) }).click();
      await p.waitForLoadState("networkidle");
      await p.waitForTimeout(600);
    },
  })),
  ...[
    ["issue-validate-dialog", "Agent skips the confirm step", "Validate"],
    ["issue-apply-dialog", "Agent quotes prices", "Apply fix"],
    ["issue-dismiss-dialog", "Agent books appointments", "Dismiss"],
  ].map(([name, title, button]) => ({
    name,
    path: "/issues",
    auth: true,
    before: async (p) => {
      await p.getByRole("link", { name: new RegExp(title) }).click();
      await p.waitForLoadState("networkidle");
      await p.getByRole("main").getByRole("button", { name: button, exact: true }).click();
      await p.waitForTimeout(900);
      if (button === "Dismiss") await p.getByRole("radio", { name: /Duplicate/ }).click();
      if (button === "Validate") await p.getByRole("button", { name: "Change keep rule" }).click();
      await p.waitForTimeout(500);
    },
  })),
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
  tablet: { viewport: { width: 1024, height: 800 }, deviceScaleFactor: 1 },
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
        if (s.full) await page.evaluate(() => window.scrollTo(0, 0));
        const file = join(out, `${s.name}-${theme}${size === "desktop" ? "" : `-${size}`}.png`);
        // Pages with a sticky bottom bar are shot in a viewport as tall as the page, so the bar sits at the end.
        const vp = page.viewportSize();
        if (s.tall) await page.setViewportSize({ width: vp.width, height: await page.evaluate(() => document.documentElement.scrollHeight) });
        await page.screenshot({ path: file, fullPage: Boolean(s.full) });
        if (s.tall) await page.setViewportSize(vp);
        if (s.after) await s.after(page);
        console.log(file);
      }
      await ctx.close();
    }
  }
} finally {
  await browser.close();
}
