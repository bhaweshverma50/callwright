import { defineConfig, devices } from "@playwright/test";

/**
 * Browser journeys. By default they run against the mock API (`vite --mode mock`), so they need
 * no backend. Set E2E_BASE_URL to run them against a real stack instead.
 */
const external = process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: external ?? "http://localhost:5180",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: external
    ? undefined
    : { command: "pnpm dev:mock", url: "http://localhost:5180", reuseExistingServer: true, timeout: 60_000 },
});
