import { defineConfig, devices } from "@playwright/test";
import { E2E_API_PORT, E2E_API_URL, E2E_WEB_PORT, E2E_WEB_URL } from "./e2e/isolation";

// Isolated E2E stack (audit finding 10): Playwright starts its own API (opspilot_test, port 8100) and web
// server (port 3100, own build directory), never reuses a running server, and global-setup refuses to run
// unless the whole chain reports the test database. Uses the real local model; run with `make e2e`.
export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: { baseURL: E2E_WEB_URL, trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "../../scripts/e2e-api.sh",
      url: `${E2E_API_URL}/health/live`,
      reuseExistingServer: false,
      timeout: 180_000,
      env: { E2E_API_PORT: String(E2E_API_PORT) },
    },
    {
      command: `pnpm exec next dev --hostname 127.0.0.1 --port ${E2E_WEB_PORT}`,
      url: E2E_WEB_URL,
      reuseExistingServer: false,
      timeout: 180_000,
      env: {
        OPSPILOT_API_URL: E2E_API_URL,
        OPSPILOT_WEB_DIST_DIR: ".next-e2e",
        OPSPILOT_WEB_ORIGIN: E2E_WEB_URL,
        OPERATOR_TOKEN: process.env.OPERATOR_TOKEN ?? "",
        OPSPILOT_WEB_SESSION_SECRET: process.env.OPSPILOT_WEB_SESSION_SECRET ?? "",
        OPSPILOT_WEB_OPERATOR_PASSPHRASE: process.env.OPSPILOT_WEB_OPERATOR_PASSPHRASE ?? "",
        OPSPILOT_WEB_VIEWER_PASSPHRASE: process.env.OPSPILOT_WEB_VIEWER_PASSPHRASE ?? "",
      },
    },
  ],
});
