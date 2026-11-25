import { defineConfig, devices } from "@playwright/test";

// Intercepted saved cases only: no API, database, cloud or remediation process.
export default defineConfig({
  testDir: "./e2e-pass-b", workers: 1, fullyParallel: false, timeout: 60_000,
  reporter: [["list"], ["json", { outputFile: "../../docs/audits/pass-b-playwright.json" }]],
  use: { baseURL: "http://127.0.0.1:3100", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "uv run python -m opspilot_shared.web_env --exec node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3100",
    url: "http://127.0.0.1:3100", reuseExistingServer: false, timeout: 30_000,
    env: { OPSPILOT_WEB_ORIGIN: "http://127.0.0.1:3100", OPSPILOT_API_URL: "http://127.0.0.1:8100" },
  },
});
