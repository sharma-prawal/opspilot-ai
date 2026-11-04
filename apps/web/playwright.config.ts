import { defineConfig, devices } from "@playwright/test";

// Runs against an already-running local stack (`make dev`). Uses the real local model, so
// timeouts are generous. Not part of `make test`; run with `make e2e`.
export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: process.env.OPSPILOT_WEB_URL ?? "http://127.0.0.1:3000", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
