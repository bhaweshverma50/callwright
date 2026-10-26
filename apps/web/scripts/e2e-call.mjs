// Places one real browser test call against a local stack (API :8100, web :5180, LiveKit dev,
// voice worker) with a fake microphone, and prints the panel's state over time.
//   node scripts/e2e-call.mjs <caller.wav> <out-dir> [template-id]
import { chromium } from "@playwright/test";

const [wav, outDir, template = "banking-collections"] = process.argv.slice(2);
const API = process.env.API ?? "http://localhost:8100/v1";
const WEB = process.env.WEB ?? "http://localhost:5180";

const email = `e2e-${Date.now()}@example.com`;
const password = "e2e-password-123";
const post = async (path, body, token) => {
  const r = await fetch(API + path, {
    method: "POST",
    headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}), "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} ${r.status} ${await r.text()}`);
  return r.json();
};
const reg = await post("/auth/register", { email, password });
const token = reg.access_token ?? reg.session?.access_token;
const agent = await post("/agents", { name: "E2E agent", type: "single_prompt", template_id: template }, token);

const browser = await chromium.launch({
  args: [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    `--use-file-for-fake-audio-capture=${wav}`,
    "--autoplay-policy=no-user-gesture-required",
  ],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on("console", (m) => ["error", "warning"].includes(m.type()) && console.log(`console.${m.type()}:`, m.text().slice(0, 240)));
page.on("response", (r) => r.status() >= 400 && console.log("http", r.status(), r.url()));
await page.goto(`${WEB}/login`);
await page.fill('input[type="email"]', email);
await page.fill('input[type="password"]', password);
await page.getByRole("button", { name: "Sign in" }).click();
await page.waitForURL((u) => !u.pathname.startsWith("/login"));
await page.goto(`${WEB}/agents/${agent.id}/testing`);
await page.getByRole("button", { name: "Start test call" }).click();
const t0 = Date.now();
let last = "";
for (let i = 0; i < Number(process.env.TICKS ?? 70); i++) {
  await page.waitForTimeout(500);
  const panel = (await page.getByLabel("Test call").innerText()).replace(/\s+/g, " ").slice(0, 260);
  if (panel !== last) console.log(`${((Date.now() - t0) / 1000).toFixed(1)}s`, panel);
  last = panel;
  if (/Call again|Try again/.test(panel)) break;
}
await page.screenshot({ path: `${outDir}/panel.png` });
if (process.env.AFTER) {
  // Hang up, give post-call processing a moment, then capture the pages that show the call.
  await page.getByRole("button", { name: "End call" }).click().catch(() => {});
  await page.waitForTimeout(12_000);
  for (const path of process.env.AFTER.split(",")) {
    await page.goto(`${WEB}${path}`);
    await page.waitForTimeout(4_000);
    await page.screenshot({ path: `${outDir}/${path.replace(/\W+/g, "_")}.png`, fullPage: true });
  }
}
console.log("agent", agent.id);
await browser.close();
