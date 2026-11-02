#!/usr/bin/env node
// Records the home page tour (public/media/tour.*) from the mock app.
//   VITE_API_MOCKS=true pnpm dev            (web on 5180)
//   node scripts/record-tour.mjs /tmp/rec   (writes a raw .webm into the folder)
// Then encode (trim the login, speed up 1.25x):
//   F="trim=start=<start mark>:end=<end mark>,setpts=(PTS-STARTPTS)/1.25,scale=1280:800:flags=lanczos,fps=30"
//   ffmpeg -i raw.webm -vf "$F" -an -c:v libx264 -preset slow -crf 24 -pix_fmt yuv420p -movflags +faststart public/media/tour.mp4
//   ffmpeg -i raw.webm -vf "$F" -an -c:v libvpx-vp9 -crf 38 -b:v 0 -row-mt 1 public/media/tour.webm
//   ffmpeg -ss 18 -i public/media/tour.mp4 -frames:v 1 -q:v 4 public/media/tour-poster.jpg
// The mock data resets on every full page load, so the tour moves by clicking, never page.goto.
import { chromium } from "@playwright/test";
const out = process.argv[2];
const b = await chromium.launch({ args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] });
const ctx = await b.newContext({
  viewport: { width: 1440, height: 900 },
  permissions: ["microphone"],
  recordVideo: { dir: out, size: { width: 1440, height: 900 } },
});
const t = Date.now();
const p = await ctx.newPage();
const mark = (m) => console.log(m, ((Date.now() - t) / 1000).toFixed(1));
await p.goto("http://localhost:5180/login?seed");
await p.waitForTimeout(800);
await p.getByLabel("Work email").fill("ops@halcyon-dental.com");
await p.getByLabel("Password").fill("correct-horse-9");
await p.getByRole("button", { name: "Sign in" }).click();
await p.waitForURL(/dashboard/);
await p.waitForTimeout(2500);
mark("start");
await p.getByRole("link", { name: "Agents" }).first().click();
await p.waitForTimeout(2200);
await p.getByRole("link", { name: "Front desk agent" }).hover();
await p.waitForTimeout(400);
await p.getByRole("link", { name: "Front desk agent" }).click();
await p.waitForTimeout(2500);
await p.mouse.move(800, 500);
for (let i = 0; i < 8; i++) {
  await p.mouse.wheel(0, 70);
  await p.waitForTimeout(90);
}
await p.waitForTimeout(1200);
for (let i = 0; i < 8; i++) {
  await p.mouse.wheel(0, -70);
  await p.waitForTimeout(60);
}
await p.waitForTimeout(500);
await p
  .getByRole("link", { name: "Test agent" })
  .or(p.getByRole("button", { name: "Test agent" }))
  .first()
  .click();
await p.waitForTimeout(1500);
mark("call");
await p.getByRole("button", { name: "Start test call" }).click();
await p.waitForTimeout(13000);
const hang = p.getByRole("button", { name: /Hang up|End call/ });
if (await hang.count()) {
  await hang.first().click();
}
mark("hung");
await p.waitForTimeout(2500);
await p.getByRole("link", { name: "Calls" }).first().click();
await p.waitForTimeout(2500);
const row = p.locator("main tbody tr").first();
await row.click().catch(async () => {
  console.log("row click failed", await p.evaluate(() => document.querySelector("main")?.innerText.slice(0, 300)));
});
mark("drawer");
await p.waitForTimeout(3500);
for (const tab of ["Latency", "Cost", "Quality"]) {
  await p
    .getByRole("tab", { name: tab })
    .click()
    .catch(() => console.log("no tab", tab));
  await p.waitForTimeout(2600);
}
mark("end");
await p.screenshot({ path: `${out}/last.png` });
await ctx.close();
await b.close();
