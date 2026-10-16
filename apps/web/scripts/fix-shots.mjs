#!/usr/bin/env node
// Before/after shots for targeted visual fixes: settings cards and switch, collapsed sidebar.
//   node scripts/fix-shots.mjs before|after   (SCREENS_BASE defaults to http://localhost:5180)
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const tag = process.argv[2] ?? "after";
const here = dirname(fileURLToPath(import.meta.url));
const out = resolve(here, "../docs/screens/fixes");
mkdirSync(out, { recursive: true });
const BASE = process.env.SCREENS_BASE ?? "http://localhost:5180";

const browser = await chromium.launch();
try {
  for (const theme of ["light", "dark"]) {
    for (const width of [1440, 1024, 390]) {
      const ctx = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 2, colorScheme: theme });
      await ctx.addInitScript((t) => localStorage.setItem("cw.theme", t), theme);
      const page = await ctx.newPage();
      await page.goto(`${BASE}/login`);
      await page.getByLabel("Work email").fill("ops@halcyon-dental.com");
      await page.getByLabel("Password", { exact: true }).fill("correct-horse-9");
      await page.getByRole("button", { name: "Sign in" }).click();
      await page.waitForURL("**/dashboard");

      if (width !== 1024) {
        await page.goto(`${BASE}/dashboard`);
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(1200);
        await page.screenshot({ path: join(out, `${tag}-stepper-${width}-${theme}.png`) });
      }

      await page.goto(`${BASE}/settings`);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(500);
      await page.screenshot({ path: join(out, `${tag}-settings-${width}-${theme}.png`) });
      const sw = page.getByRole("switch", { name: "Record calls by default" });
      const box = await sw.boundingBox();
      if (box) {
        const clip = { x: Math.max(0, box.x - 24), y: Math.max(0, box.y - 16), width: box.width + 48, height: box.height + 32 };
        await page.screenshot({ path: join(out, `${tag}-switch-on-${width}-${theme}.png`), clip });
        await sw.focus();
        await page.keyboard.press("Space");
        await page.waitForTimeout(400);
        await page.screenshot({ path: join(out, `${tag}-switch-off-focus-${width}-${theme}.png`), clip });
      }

      if (width >= 1024) {
        await page.goto(`${BASE}/billing`);
        await page.waitForLoadState("networkidle");
        const collapse = page.getByRole("button", { name: "Collapse navigation" });
        if (await collapse.count()) await collapse.click();
        await page.waitForTimeout(900);
        await page.screenshot({ path: join(out, `${tag}-sidebar-collapsed-${width}-${theme}.png`), clip: { x: 0, y: 0, width: 360, height: 900 } });
        await page.getByRole("link", { name: "Datasets" }).hover();
        await page.waitForTimeout(600);
        await page.screenshot({
          path: join(out, `${tag}-sidebar-collapsed-hover-${width}-${theme}.png`),
          clip: { x: 0, y: 0, width: 360, height: 900 },
        });
        await page.getByRole("button", { name: "Expand navigation" }).click();
        await page.waitForTimeout(600);
      }
      await ctx.close();
    }
  }
} finally {
  await browser.close();
}
