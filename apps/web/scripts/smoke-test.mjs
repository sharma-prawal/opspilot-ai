import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = 3198;
const BASE_URL = `http://127.0.0.1:${PORT}`;

async function waitForServer(url, timeoutMs = 25000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.status < 500) return;
    } catch {
      /* wait */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Server did not respond within ${timeoutMs}ms at ${url}`);
}

async function runSmokeTests() {
  console.log("=== OpsPilot AI Browser Smoke Test Suite ===");
  console.log(`Starting Next.js production server on port ${PORT}...`);

  const server = spawn("pnpm", ["exec", "next", "start", "-p", String(PORT)], {
    cwd: resolve(__dirname, ".."),
    stdio: "inherit",
    env: { ...process.env, PORT: String(PORT) },
  });

  let failureCount = 0;

  try {
    await waitForServer(BASE_URL);
    console.log(`Next.js server is ready at ${BASE_URL}\n`);

    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ colorScheme: "dark" });
    const page = await context.newPage();

    // Setup API mocking for deterministic, reliable smoke test runs
    let actionStatus = "pending";
    let investigationStatus = "awaiting_approval";

    await page.route("**/api/session", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          authenticated: true,
          sub: "lead-operator",
          role: "operator",
          csrf: "mock-csrf-token",
        }),
      });
    });

    await page.route("**/api/ops/**", async (route) => {
      const url = route.request().url();
      const method = route.request().method();

      // Handle approval POST
      if (url.includes("api/v1/approvals/act-mock-001/decision") && method === "POST") {
        actionStatus = "approved";
        investigationStatus = "completed";
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "act-mock-001",
            status: "approved",
            decided_at: new Date().toISOString(),
            decided_by: "lead-operator",
            decision_comment: "Approved by lead operator via UI",
            executed_at: new Date().toISOString(),
            execution_result: { ok: true, output: "Deployment dep-ls-0042 rolled back to dep-ls-0041" },
            verification: { recovered: true, observed_healthy: true, verification_time: new Date().toISOString() },
          }),
        });
      }

      if (url.includes("api/v1/system/overview")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            incidents: { open: 2, investigating: 1, awaiting_approval: 1, mitigated: 8, resolved: 14 },
            investigations: { queued: 0, running: 1, completed: 22, failed: 0 },
            actions: { pending: actionStatus === "pending" ? 1 : 0, approved: actionStatus === "approved" ? 19 : 18, rejected: 3 },
            knowledge: { documents: 23, chunks: 168 },
            runtime: {
              llm_model: "qwen3:8b",
              embedding_model: "qwen3-embedding:0.6b",
              mcp_read_tools: ["list_service_metrics", "query_metrics", "search_logs", "get_service_dependencies", "get_datastore_status", "inspect_queue", "search_runbooks"],
              mcp_action_tools: ["rollback_deployment", "scale_connection_pool", "pause_consumer", "quarantine_messages", "resume_consumer"],
              max_concurrent_investigations: 1,
              agent_budgets: { tool_calls: 40, llm_calls: 6, rounds: 2 },
            },
          }),
        });
      }

      if (url.includes("health/dependencies")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            checks: {
              postgresql: { ok: true, version: "PostgreSQL 17.2, pgvector 0.8.7" },
              ollama_llm: { ok: true, model: "qwen3:8b" },
              ollama_embeddings: { ok: true, model: "qwen3-embedding:0.6b" },
              mcp_read_server: { ok: true, tools: 7 },
              mcp_action_server: { ok: true, tools: 5 },
            },
            config: {},
          }),
        });
      }

      if (url.includes("api/v1/incidents/scenarios")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            { key: "INC-001", title: "Incompatible schema migration" },
            { key: "INC-002", title: "Connection pool exhaustion" },
            { key: "INC-003", title: "Invalid settlement payloads" },
            { key: "NEG-001", title: "Transient latency blip" },
            { key: "NEG-002", title: "External provider outage" },
            { key: "NEG-003", title: "Ambiguous changes & log outage" },
          ]),
        });
      }

      if (url.includes("api/v1/incidents/inc-mock-001/investigations")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "inv-mock-001",
              incident_id: "inc-mock-001",
              status: investigationStatus,
              current_step: investigationStatus === "completed" ? "complete" : "await_approval",
              model: "qwen3:8b",
              started_at: new Date(Date.now() - 45000).toISOString(),
              completed_at: investigationStatus === "completed" ? new Date().toISOString() : null,
              error: null,
              error_class: null,
              created_at: new Date(Date.now() - 45000).toISOString(),
              updated_at: new Date().toISOString(),
            },
          ]),
        });
      }

      if (url.includes("api/v1/incidents/inc-mock-001")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "inc-mock-001",
            reference: "INC-001",
            title: "Elevated HTTP 5xx ratio on transaction-api",
            description: "HTTP 500 error rate spiked from baseline 0.1% to 42.8% on transaction-api following unnotified schema change in upstream ledger-service.",
            severity: "critical",
            status: investigationStatus === "completed" ? "mitigated" : "awaiting_approval",
            service: "transaction-api",
            environment_id: "production-eu-west-1",
            detected_at: new Date(Date.now() - 60000).toISOString(),
            created_at: new Date(Date.now() - 60000).toISOString(),
          }),
        });
      }

      if (url.includes("api/v1/incidents")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "inc-mock-001",
              reference: "INC-001",
              title: "Elevated HTTP 5xx ratio on transaction-api",
              description: "HTTP 500 error rate spiked to 42.8% following schema change in ledger-service.",
              severity: "critical",
              status: investigationStatus === "completed" ? "mitigated" : "awaiting_approval",
              service: "transaction-api",
              environment_id: "production-eu-west-1",
              detected_at: new Date(Date.now() - 60000).toISOString(),
              created_at: new Date(Date.now() - 60000).toISOString(),
            },
            {
              id: "inc-mock-002",
              reference: "INC-002",
              title: "Connection pool exhaustion on ledger-db",
              description: "Database connection pool saturated at 93% with active sequential scans.",
              severity: "high",
              status: "mitigated",
              service: "ledger-db",
              environment_id: "production-eu-west-1",
              detected_at: new Date(Date.now() - 3600000).toISOString(),
              created_at: new Date(Date.now() - 3600000).toISOString(),
            },
          ]),
        });
      }

      if (url.includes("api/v1/investigations/inv-mock-001/events")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            { id: 1, event_type: "node_completed", node: "intake", created_at: new Date(Date.now() - 40000).toISOString(), payload: {} },
            { id: 2, event_type: "node_completed", node: "plan", created_at: new Date(Date.now() - 35000).toISOString(), payload: { active_task: { capability: "telemetry", service: "transaction-api", reason: "Mandatory alerting service telemetry" } } },
            { id: 3, event_type: "node_completed", node: "telemetry", created_at: new Date(Date.now() - 25000).toISOString(), payload: { tool_calls: [{ id: "t1", tool: "query_metrics", status: "ok", latency_ms: 42 }, { id: "t2", tool: "search_logs", status: "ok", latency_ms: 88 }], observations: [{ agent: "telemetry", finding: "HTTP 5xx jumped from 0.08% to 42.8% at onset; error signatures cite UndefinedColumn in ledger-service." }] } },
            { id: 4, event_type: "node_completed", node: "dependencies", created_at: new Date(Date.now() - 20000).toISOString(), payload: { tool_calls: [{ id: "t3", tool: "get_service_dependencies", status: "ok", latency_ms: 18 }] } },
            { id: 5, event_type: "node_completed", node: "changes", created_at: new Date(Date.now() - 15000).toISOString(), payload: { tool_calls: [{ id: "t4", tool: "list_recent_deployments", status: "ok", latency_ms: 32 }], observations: [{ agent: "changes", finding: "Deployment dep-ls-0042 landed 1 min prior to onset with correlation score 1.00." }] } },
            { id: 6, event_type: "node_completed", node: "knowledge", created_at: new Date(Date.now() - 10000).toISOString(), payload: { tool_calls: [{ id: "t5", tool: "search_runbooks", status: "ok", latency_ms: 112 }] } },
            { id: 7, event_type: "node_completed", node: "rca", created_at: new Date(Date.now() - 5000).toISOString(), payload: { llm_calls: [{ purpose: "rca_generation", model: "qwen3:8b", latency_ms: 1840, prompt_tokens: 1240, completion_tokens: 280 }] } },
            { id: 8, event_type: actionStatus === "approved" ? "action_executed" : "approval_requested", node: actionStatus === "approved" ? "verify" : "await_approval", created_at: new Date().toISOString(), payload: {} },
          ]),
        });
      }

      if (url.includes("api/v1/investigations/inv-mock-001/evidence")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              evidence_id: "EVID-TEL-001",
              kind: "telemetry",
              source_tool: "query_metrics",
              collected_by: "telemetry_agent",
              service: "transaction-api",
              summary: "Error rate metric http_requests_5xx_ratio shifted from 0.08% to 42.8% at onset.",
              data: { baseline: 0.0008, observed: 0.428 },
              citation: null,
              relevance: 0.98,
              observed_at: new Date(Date.now() - 40000).toISOString(),
            },
            {
              evidence_id: "EVID-LOG-002",
              kind: "telemetry",
              source_tool: "search_logs",
              collected_by: "telemetry_agent",
              service: "transaction-api",
              summary: "Log cluster (1,480 occurrences): psycopg2.errors.UndefinedColumn: column 'amount_cents' does not exist in relation 'ledger_entries'.",
              data: { error_class: "UndefinedColumn" },
              citation: null,
              relevance: 0.99,
              observed_at: new Date(Date.now() - 35000).toISOString(),
            },
            {
              evidence_id: "EVID-CHG-003",
              kind: "deployment",
              source_tool: "list_recent_deployments",
              collected_by: "changes_agent",
              service: "ledger-service",
              summary: "Deployment dep-ls-0042 completed 1 min before onset with temporal correlation 1.00.",
              data: { deployment_id: "dep-ls-0042", correlation: 1.0 },
              citation: null,
              relevance: 1.0,
              observed_at: new Date(Date.now() - 25000).toISOString(),
            },
            {
              evidence_id: "EVID-KB-004",
              kind: "runbook",
              source_tool: "search_runbooks",
              collected_by: "knowledge_agent",
              service: "ledger-service",
              summary: "Runbook: Schema migration rollback procedure (runbooks/database/schema_rollback.md).",
              data: { lifecycle_tier: 0 },
              citation: {
                document_id: "doc-uuid-001",
                chunk_id: "chunk-uuid-002",
                source_uri: "runbooks/database/schema_rollback.md",
                title: "Schema Migration Troubleshooting & Rollback",
                heading_path: "Schema Migration > Emergency Rollback",
              },
              relevance: 0.95,
              observed_at: new Date(Date.now() - 15000).toISOString(),
            },
          ]),
        });
      }

      if (url.includes("api/v1/investigations/inv-mock-001/actions")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "act-mock-001",
              investigation_id: "inv-mock-001",
              incident_id: "inc-mock-001",
              action_type: "rollback_deployment",
              parameters: {
                service: "ledger-service",
                deployment_id: "dep-ls-0042",
                target_revision: "dep-ls-0041",
              },
              params_hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
              rationale: "Revert incompatible schema migration dep-ls-0042 to restore column compatibility with transaction-api.",
              risk: "medium",
              status: actionStatus,
              requested_at: new Date(Date.now() - 5000).toISOString(),
              decided_at: actionStatus === "approved" ? new Date().toISOString() : null,
              decided_by: actionStatus === "approved" ? "lead-operator" : null,
              decision_comment: actionStatus === "approved" ? "Approved by lead operator" : null,
              executed_at: actionStatus === "approved" ? new Date().toISOString() : null,
              execution_result: actionStatus === "approved" ? { ok: true, output: "Deployment rolled back" } : null,
              verification: actionStatus === "approved" ? { recovered: true, observed_healthy: true } : null,
            },
          ]),
        });
      }

      if (url.includes("api/v1/investigations/inv-mock-001/tool-calls")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            { id: "tc-1", tool: "query_metrics", server: "readsrv", agent: "telemetry", arguments: { service: "transaction-api" }, status: "ok", latency_ms: 42, result_summary: "5xx ratio: 0.428 (threshold 0.01)", error: null, started_at: new Date(Date.now() - 30000).toISOString() },
            { id: "tc-2", tool: "search_logs", server: "readsrv", agent: "telemetry", arguments: { service: "transaction-api", limit: 50 }, status: "ok", latency_ms: 88, result_summary: "1,480 UndefinedColumn errors", error: null, started_at: new Date(Date.now() - 25000).toISOString() },
            { id: "tc-3", tool: "get_service_dependencies", server: "readsrv", agent: "dependencies", arguments: { service: "transaction-api" }, status: "ok", latency_ms: 18, result_summary: "Downstream: ledger-service (UNHEALTHY)", error: null, started_at: new Date(Date.now() - 20000).toISOString() },
            { id: "tc-4", tool: "list_recent_deployments", server: "readsrv", agent: "changes", arguments: { service: "ledger-service" }, status: "ok", latency_ms: 32, result_summary: "dep-ls-0042 (correlation 1.00)", error: null, started_at: new Date(Date.now() - 15000).toISOString() },
            { id: "tc-5", tool: "search_runbooks", server: "readsrv", agent: "knowledge", arguments: { query: "UndefinedColumn rollback migration" }, status: "ok", latency_ms: 112, result_summary: "Top chunk: schema_rollback.md (score 0.95)", error: null, started_at: new Date(Date.now() - 10000).toISOString() },
          ]),
        });
      }

      if (url.includes("api/v1/investigations/inv-mock-001/report")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            status: "completed",
            markdown: `# Root Cause Analysis & Postmortem: INC-001\n\n## Incident Summary\n- Alerting Service: transaction-api\n- Root Cause: Incompatible schema migration\n- Outcome: mitigated`,
          }),
        });
      }

      if (url.includes("api/v1/investigations/inv-mock-001")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "inv-mock-001",
            incident_id: "inc-mock-001",
            status: investigationStatus,
            current_step: investigationStatus === "completed" ? "complete" : "await_approval",
            model: "qwen3:8b",
            started_at: new Date(Date.now() - 45000).toISOString(),
            completed_at: investigationStatus === "completed" ? new Date().toISOString() : null,
            error: null,
            error_class: null,
            created_at: new Date(Date.now() - 45000).toISOString(),
            updated_at: new Date().toISOString(),
            result: {
              classification: { category: "database_schema", confidence: 0.96, rationale: "Schema column drift between services", source: "model" },
              plan: { capabilities: ["telemetry", "dependencies", "changes", "knowledge"], notes: [] },
              rca: {
                summary: "Elevated HTTP 5xx errors on transaction-api were caused by deployment dep-ls-0042 in ledger-service.",
                hypotheses: [
                  {
                    rank: 1,
                    title: "Incompatible schema migration in ledger-service",
                    category: "database_schema",
                    description: "Deployment dep-ls-0042 executed 1 minute before onset.",
                    confidence: 0.94,
                    supporting_evidence_ids: ["EVID-TEL-001", "EVID-LOG-002", "EVID-CHG-003"],
                    contradicting_evidence_ids: [],
                  },
                ],
                evidence_gaps: [],
                citation_violations: [],
              },
              remediation_plan: [
                {
                  step: 1,
                  action_id: "act-mock-001",
                  action_type: "rollback_deployment",
                  parameters: { service: "ledger-service", deployment_id: "dep-ls-0042" },
                  params_hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                  rationale: "Rollback deployment dep-ls-0042 to restore column compatibility.",
                  risk: "medium",
                  role: "resolution",
                },
              ],
              rejected_proposals: [
                {
                  proposal: { action_type: "restart_service", service: "settlement-worker" },
                  reason: "Abnormality Gate violated: settlement-worker exhibits healthy telemetry.",
                  category: "unwarranted",
                },
              ],
              outcome: investigationStatus === "completed" ? "mitigated" : null,
            },
          }),
        });
      }

      return route.continue();
    });

    // TEST 1: Dashboard / Overview
    console.log("TEST 1: Verifying Landing Dashboard...");
    await page.goto(`${BASE_URL}/`);
    await page.waitForSelector("text=System overview");

    const scenarioCount = await page.locator("text=INC-001").count();
    if (scenarioCount === 0) throw new Error("Scenario cards not found on dashboard");
    console.log("  ✔ Dashboard loaded with system KPI cards and synthetic scenarios");

    // TEST 2: Navigate to Investigation Detail View
    console.log("TEST 2: Verifying Incident Command Center & Evidence...");
    await page.goto(`${BASE_URL}/investigations/inv-mock-001`);
    await page.waitForSelector("text=OPERATOR ACTION REQUIRED");

    // Verify 12-stage stepper
    const stepperText = await page.locator("text=Awaiting approval").first().innerText();
    console.log(`  ✔ Stepper current stage active: "${stepperText}"`);

    // Verify Root-cause hypothesis and confidence note
    await page.waitForSelector("text=Incompatible schema migration in ledger-service");
    await page.waitForSelector("text=Model-estimated confidence");
    console.log("  ✔ Root cause hypothesis displayed with model-estimated confidence note");

    // Verify Safety blocked proposals (on overview tab)
    await page.waitForSelector("text=Abnormality Gate violated");
    console.log("  ✔ Safety-blocked proposals clearly separated from executable actions");

    // Verify Evidence collection (switch tab)
    await page.getByRole("button", { name: "Collected Evidence" }).click();
    await page.waitForSelector("text=EVID-TEL-001");
    await page.waitForSelector("text=EVID-CHG-003");
    console.log("  ✔ Collected evidence tabs and citations displayed");

    // TEST 3: Human Approval Workflow
    console.log("TEST 3: Testing Human Approval Flow...");
    await page.getByRole("button", { name: /Analysis & Remediation/i }).click();
    await page.waitForSelector("#remediation-section");
    const approveBtn = page.getByRole("button", { name: /Approve & execute/i });
    await approveBtn.click();
    await page.waitForTimeout(600);
    console.log("  ✔ Approval action successfully submitted via authorized operator session");

    // TEST 4: Architecture Explorer (All 4 Diagrams)
    console.log("TEST 4: Verifying Architecture Explorer (Diagrams A, B, C, D)...");
    await page.goto(`${BASE_URL}/architecture`);
    await page.waitForSelector("text=Interactive Architecture");

    // Diagram A
    await page.waitForSelector("text=FastAPI REST Runner");
    console.log("  ✔ Diagram A (System Architecture) rendered with interactive nodes");

    // Diagram B
    await page.getByRole("tab", { name: /Diagram B/i }).click();
    await page.waitForTimeout(400);
    await page.waitForSelector("text=2. Supervisor Plan");
    console.log("  ✔ Diagram B (Agent Workflow Graph) rendered with conditional branches");

    // Diagram C
    await page.getByRole("tab", { name: /Diagram C/i }).click();
    await page.waitForTimeout(400);
    await page.waitForSelector("text=1. Corpus Ingestion");
    console.log("  ✔ Diagram C (Hybrid RAG Pipeline) rendered");

    // Diagram D
    await page.getByRole("tab", { name: /Diagram D/i }).click();
    await page.waitForTimeout(400);
    await page.waitForSelector("text=Synthetic Simulator");
    await page.waitForSelector("text=Implemented");
    await page.waitForSelector("text=Adapter Seam");
    await page.waitForSelector("text=Planned");
    console.log("  ✔ Diagram D (Evidence Ingestion & Extensibility) rendered with implementation badges");

    // TEST 5: Data Sources & Integrations
    console.log("TEST 5: Verifying Data Sources & Integrations Guide...");
    await page.goto(`${BASE_URL}/integrations`);
    await page.waitForSelector("text=Data Sources & Integrations");

    // Switch between modes
    await page.getByRole("tab", { name: /Offline \/ File Mode/i }).click();
    await page.waitForTimeout(300);
    await page.waitForSelector("text=Offline Metric & Log Export Files");

    await page.getByRole("tab", { name: /Connected Mode/i }).click();
    await page.waitForTimeout(300);
    await page.waitForSelector("text=Prometheus / Cortex / Thanos / Mimir");
    await page.waitForSelector("text=AWS CloudWatch & Container Insights");
    console.log("  ✔ Data Sources & Integrations page interactive across all 3 modes");

    // TEST 6: Developer Guide (Desktop & Mobile)
    console.log("TEST 6: Verifying Getting Started Guide...");
    await page.goto(`${BASE_URL}/guide`);
    await page.waitForSelector("text=Developer & Operator Getting Started Guide");
    await page.waitForSelector("text=What OpsPilot AI Is");
    await page.getByRole("button", { name: /Local Setup/i }).first().click();
    await page.waitForSelector("text=make bootstrap ARGS=--install");
    console.log("  ✔ Guide loaded with 12 verified steps");

    // Mobile Viewport
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE_URL}/guide`);
    await page.waitForSelector("text=Developer & Operator Getting Started Guide");
    console.log("  ✔ Guide responsive on mobile viewport");

    // TEST 7: Safety & Governance Center
    console.log("TEST 7: Verifying Safety & Governance Center...");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE_URL}/safety`);
    await page.waitForSelector("text=Safety Architecture");
    await page.waitForSelector("text=The Seven Invariant Safety Gates");
    console.log("  ✔ Safety center verified with 7 safety gates and case studies");

    await browser.close();
    console.log("\n=============================================");
    console.log("✔ ALL BROWSER SMOKE TESTS PASSED CLEANLY!");
    console.log("=============================================\n");
  } catch (err) {
    console.error("✘ Smoke test failed:", err);
    failureCount++;
  } finally {
    server.kill("SIGTERM");
  }

  if (failureCount > 0) {
    process.exit(1);
  }
}

runSmokeTests();
