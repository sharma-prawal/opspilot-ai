import { defineConfig, devices } from "@playwright/test";

// Synthetic saved-history responses only. This stack never starts an API or opens a database.
export default defineConfig({
  testDir: "./e2e-pass-a",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"], ["json", { outputFile: process.env.OPSPILOT_PASS_A_REPORT ?? "../../docs/audits/pass-a-playwright.json" }]],
  use: { baseURL: "http://127.0.0.1:3185", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "uv run python -m opspilot_shared.web_env --exec node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3185",
    url: "http://127.0.0.1:3185", reuseExistingServer: false, timeout: 30_000,
    env: { OPSPILOT_WEB_ORIGIN: "http://127.0.0.1:3185" },
  },
});
