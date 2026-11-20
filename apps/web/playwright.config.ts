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
    // v0.9: E2E_DATADOG=1 serves the synthetic Datadog API fixture on loopback for the E2E API (never a real site).
    ...(process.env.E2E_DATADOG
      ? [{
          command: `uv run python ../../scripts/datadog_fixture.py --port ${process.env.E2E_DATADOG_PORT ?? 8127}`,
          url: `http://127.0.0.1:${process.env.E2E_DATADOG_PORT ?? 8127}/api/v1/validate`, // 403 without keys = up
          reuseExistingServer: false,
          timeout: 60_000,
        }]
      : []),
    // v0.10: E2E_AZURE=1 serves the synthetic Azure Monitor Logs API fixture on loopback (never a real workspace).
    ...(process.env.E2E_AZURE
      ? [{
          command: `uv run python ../../scripts/azure_monitor_fixture.py --port ${process.env.E2E_AZURE_PORT ?? 8129}`,
          // 401 without a token = up
          url: `http://127.0.0.1:${process.env.E2E_AZURE_PORT ?? 8129}/v1/workspaces/6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1001/query`,
          reuseExistingServer: false,
          timeout: 60_000,
        }]
      : []),
    {
      command: "../../scripts/e2e-api.sh",
      url: `${E2E_API_URL}/health/live`,
      reuseExistingServer: false,
      timeout: 180_000,
      env: { E2E_API_PORT: String(E2E_API_PORT) },
    },
    {
      // v0.10: started through the web-process allowlist (opspilot_shared.web_env), so the backend credentials the
      // E2E API needs (database, MCP roles, signing key) never reach the Next.js process.
      command: `uv run python -m opspilot_shared.web_env --exec pnpm exec next dev --hostname 127.0.0.1 --port ${E2E_WEB_PORT}`,
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
