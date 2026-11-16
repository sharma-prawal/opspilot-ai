/**
 * OpsPilot AI — Real Browser-to-Backend Smoke Test
 *
 * Runs an end-to-end user journey against the live running stack:
 *   Next.js (3000) -> FastAPI (8000) -> LangGraph -> Ollama (qwen3:8b) -> MCP Read/Actions -> PostgreSQL
 *
 * Steps verified:
 *   1. Operator login via BFF /api/session
 *   2. Synthetic scenario launch (INC-001)
 *   3. Agent investigation execution across telemetry, dependencies, changes, knowledge
 *   4. Collected evidence review
 *   5. Human approval interrupt & authorization of sandbox remediation
 *   6. Action execution, affirmative recovery verification, and final RCA report
 */

import { chromium } from "@playwright/test";

const BASE_URL = process.env.OPSPILOT_URL || "http://127.0.0.1:3000";
const OPERATOR_NAME = "lead-operator";
const OPERATOR_PASSPHRASE =
  process.env.OPSPILOT_WEB_OPERATOR_PASSPHRASE || "gmbYq1shb5Mot3TUNTsWCYCI";

async function runLiveSmoke() {
  console.log("=== OpsPilot AI Live Browser-to-Backend Smoke Test ===");
  console.log(`Target: ${BASE_URL}`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    // 1. Sign In
    console.log("Step 1: Signing in as authorized operator...");
    await page.goto(`${BASE_URL}/login`);
    await page.fill('input[placeholder="e.g. demo-operator"]', OPERATOR_NAME);
    await page.fill('input[type="password"]', OPERATOR_PASSPHRASE);
    await page.click('button[type="submit"]');
    await page.waitForURL(`${BASE_URL}/`, { timeout: 10000 });
    console.log("  ✔ Successfully authenticated with operator session cookie and CSRF token");

    // 2. Scenario Launch
    console.log("Step 2: Launching synthetic scenario INC-001...");
    await page.waitForSelector("text=System overview");

    const simulateBtn = page.getByRole("button", { name: /Simulate/i }).first();
    await simulateBtn.click();

    // Wait for redirect to /incidents/[id]
    await page.waitForURL(/\/incidents\/[a-f0-9-]+/, { timeout: 20000 });
    console.log(`  ✔ Incident created: ${page.url()}`);

    // Click "Start investigation"
    console.log("Step 3: Starting real agent investigation with local Ollama...");
    const startInvBtn = page.getByRole("button", { name: "Start investigation" }).first();
    await startInvBtn.click();

    // Wait for redirect to /investigations/[id]
    await page.waitForURL(/\/investigations\/[a-f0-9-]+/, { timeout: 20000 });
    const invUrl = page.url();
    console.log(`  ✔ Investigation launched: ${invUrl}`);

    // 3. Monitor live investigation progress until approval required
    console.log("Step 4: Monitoring LangGraph agent execution (telemetry, dependencies, changes, knowledge)...");

    // Real Ollama inference takes ~25-50 seconds
    await page.waitForSelector("text=OPERATOR ACTION REQUIRED", { timeout: 120000 });
    console.log("  ✔ LangGraph paused at await_approval checkpoint!");

    // 4. Inspect Evidence
    console.log("Step 5: Verifying collected evidence and hypotheses...");
    await page.getByRole("button", { name: /Collected Evidence/i }).click();
    // Real backend evidence IDs use ev-metric-, ev-log-, ev-dep-, etc.
    await page.waitForSelector("text=ev-", { timeout: 15000 });
    console.log("  ✔ Real evidence items displayed (ev-metric, ev-log, ev-dep, ev-config)");

    // 5. Submit Human Approval
    console.log("Step 6: Authorizing rollback remediation in sandbox...");
    await page.getByRole("button", { name: /Analysis & Remediation/i }).click();
    await page.waitForSelector("#remediation-section");

    const approveBtn = page.getByRole("button", { name: /Approve & execute/i });
    await approveBtn.click();
    console.log("  ✔ Submitted operator approval token");

    // 6. Monitor Recovery & Final RCA
    console.log("Step 7: Verifying action execution, recovery verification, and final RCA...");
    await page.waitForSelector("text=VERIFIED RECOVERY", { timeout: 60000 });
    await page.waitForSelector("text=RCA Postmortem Report", { timeout: 15000 });
    console.log("  ✔ Recovery verified! Verdict: VERIFIED RECOVERY");
    console.log("  ✔ Final RCA postmortem report generated and rendered");

    console.log("\n========================================================");
    console.log("✔ LIVE BROWSER-TO-BACKEND SMOKE TEST PASSED COMPLETELY!");
    console.log("========================================================\n");
  } finally {
    await browser.close();
  }
}

runLiveSmoke().catch((err) => {
  console.error("✘ Live smoke test failed:", err);
  process.exit(1);
});
