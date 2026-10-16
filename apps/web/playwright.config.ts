import { defineConfig, devices } from "@playwright/test";

/**
 * Browser journeys in two projects.
 *
 * - `mock`: shell and leave-guard journeys against the in-browser mock API (`vite --mode mock`),
 *   started here on E2E_PORT (default 5180). E2E_BASE_URL points them at a server you run yourself.
 * - `real`: journeys that need the real API (sign-up with the mail catcher, fake checkout, the
 *   quickstart steps): T034, T051 and T087. They run only when E2E_REAL_BASE_URL is set to a web
 *   dev server built with VITE_API_BASE_URL pointing at that API; E2E_REAL_API_URL (default
 *   http://localhost:8100/v1) is used for the dev mail catcher at GET /v1/dev/mail.
 *
 *   E2E_REAL_BASE_URL=http://localhost:5182 E2E_REAL_API_URL=http://localhost:8101/v1 pnpm e2e --project real
 */
const external = process.env.E2E_BASE_URL;
const port = Number(process.env.E2E_PORT ?? 5180);
const realBase = process.env.E2E_REAL_BASE_URL;
const REAL_SPECS = /(signup|topup|quickstart)\.spec\.ts$/;

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { trace: "retain-on-failure" },
  projects: [
    {
      name: "mock",
      testIgnore: REAL_SPECS,
      use: { ...devices["Desktop Chrome"], baseURL: external ?? `http://localhost:${port}` },
    },
    ...(realBase
      ? [
          {
            name: "real",
            testMatch: REAL_SPECS,
            timeout: 90_000,
            use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, baseURL: realBase },
          },
        ]
      : []),
  ],
  webServer: external
    ? undefined
    : {
        command: `pnpm exec vite --mode mock --port ${port} --strictPort`,
        url: `http://localhost:${port}`,
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
});
