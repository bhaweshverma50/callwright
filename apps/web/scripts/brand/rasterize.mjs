// Rasterise brand SVGs to PNG with Playwright's Chromium and pack favicon.ico.
// Usage: node scripts/brand/rasterize.mjs jobs.json
// jobs.json: { "png": [{ "svg": "a.svg", "out": "a.png", "w": 180, "h": 180, "transparent": true }],
//              "ico": { "pngs": ["16.png", "32.png", "48.png"], "out": "favicon.ico" } }
// Set CW_PLAYWRIGHT to a @playwright/test path when node_modules is not installed here.
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.CW_PLAYWRIGHT || "@playwright/test");

const jobs = JSON.parse(readFileSync(process.argv[2], "utf8"));
const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });

for (const job of jobs.png ?? []) {
  const svg = readFileSync(job.svg).toString("base64");
  await page.setViewportSize({ width: job.w, height: job.h });
  await page.setContent(
    `<html><body style="margin:0;background:transparent"><img src="data:image/svg+xml;base64,${svg}" width="${job.w}" height="${job.h}" style="display:block"></body></html>`,
  );
  await page.waitForFunction(() => document.images[0]?.complete);
  await page.screenshot({ path: job.out, omitBackground: job.transparent !== false, clip: { x: 0, y: 0, width: job.w, height: job.h } });
}
await browser.close();

if (jobs.ico) {
  // ICO with embedded PNGs: 6 byte header, 16 byte directory entry per image, then the PNG data.
  const images = jobs.ico.pngs.map((p) => readFileSync(p));
  const header = Buffer.alloc(6 + 16 * images.length);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(images.length, 4);
  let offset = header.length;
  images.forEach((png, i) => {
    const w = png.readUInt32BE(16);
    const h = png.readUInt32BE(20);
    const e = 6 + 16 * i;
    header.writeUInt8(w >= 256 ? 0 : w, e);
    header.writeUInt8(h >= 256 ? 0 : h, e + 1);
    header.writeUInt8(0, e + 2);
    header.writeUInt8(0, e + 3);
    header.writeUInt16LE(1, e + 4);
    header.writeUInt16LE(32, e + 6);
    header.writeUInt32LE(png.length, e + 8);
    header.writeUInt32LE(offset, e + 12);
    offset += png.length;
  });
  writeFileSync(jobs.ico.out, Buffer.concat([header, ...images]));
}
