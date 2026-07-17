import { defineConfig } from "@playwright/test";

// Comprehensive E2E suite - NOT run in CI. Run manually before major
// releases: `doppler run --project taxflow --config prd -- npx playwright test`
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "https://taxflow.crewcircle.com.au",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
