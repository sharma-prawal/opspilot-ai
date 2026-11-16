import { chromium } from "@playwright/test";
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = 3199;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const OUT_DIR = resolve(__dirname, "../../../docs/images/after");
mkdirSync(OUT_DIR, { recursive: true });

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

async function main() {
  console.log("Starting Next.js production server on port", PORT);
  const server = spawn("pnpm", ["exec", "next", "start", "-p", String(PORT)], {
    cwd: resolve(__dirname, ".."),
    stdio: "inherit",
    env: { ...process.env, PORT: String(PORT) },
  });

  try {
    await waitForServer(BASE_URL);
    console.log("Next.js server is ready at", BASE_URL);

    const browser = await chromium.launch();
    const context = await browser.newContext({
      colorScheme: "dark",
    });

    const page = await context.newPage();

    // Mock session and API responses
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

      if (url.includes("api/v1/system/overview")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            incidents: { open: 2, investigating: 1, awaiting_approval: 1, mitigated: 8, resolved: 14 },
            investigations: { queued: 0, running: 1, completed: 22, failed: 0 },
            actions: { pending: 1, approved: 18, rejected: 3 },
            knowledge: { documents: 19, chunks: 142 },
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
              status: "awaiting_approval",
              current_step: "await_approval",
              model: "qwen3:8b",
              started_at: new Date(Date.now() - 45000).toISOString(),
              completed_at: null,
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
            status: "awaiting_approval",
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
              status: "awaiting_approval",
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
            {
              id: "inc-mock-003",
              reference: "INC-003",
              title: "Dead-letter queue spike on settlement-worker",
              description: "Poison message flood due to unvalidated schema version v4-draft.",
              severity: "high",
              status: "mitigated",
              service: "settlement-worker",
              environment_id: "production-eu-west-1",
              detected_at: new Date(Date.now() - 7200000).toISOString(),
              created_at: new Date(Date.now() - 7200000).toISOString(),
            },
            {
              id: "inc-mock-004",
              reference: "NEG-002",
              title: "External forex provider latency degradation",
              description: "Third-party FX rate provider timing out; internal deployment unrelated.",
              severity: "medium",
              status: "resolved",
              service: "forex-gateway",
              environment_id: "production-eu-west-1",
              detected_at: new Date(Date.now() - 14400000).toISOString(),
              created_at: new Date(Date.now() - 14400000).toISOString(),
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
            { id: 8, event_type: "approval_requested", node: "await_approval", created_at: new Date().toISOString(), payload: {} },
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
              summary: "Error rate metric http_requests_5xx_ratio shifted from 0.08% to 42.8% at onset 2026-11-03T14:00:00Z.",
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
              summary: "Deployment dep-ls-0042 (schema migration v24: rename column amount to amount_cents) completed 1 min before onset with temporal correlation 1.00.",
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
              summary: "Runbook: Schema migration rollback procedure (runbooks/database/schema_rollback.md > Execute Rollback).",
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
              status: "pending",
              requested_at: new Date(Date.now() - 5000).toISOString(),
              decided_at: null,
              decided_by: null,
              decision_comment: null,
              executed_at: null,
              execution_result: null,
              verification: null,
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
            markdown: `# Root Cause Analysis & Postmortem: INC-001

## Incident Summary
- **Alerting Service:** \`transaction-api\`
- **Onset Timestamp:** \`2026-11-03T14:00:00Z\`
- **Root Cause:** Column rename migration \`dep-ls-0042\` in \`ledger-service\` broke database schema contract.
- **Remediation Action:** \`rollback_deployment dep-ls-0042\`
- **Outcome:** \`mitigated\` (verified recovery)

## Ranked hypotheses
1. **Incompatible Database Schema Migration** (Confidence: 94%)
   - Supporting evidence: \`EVID-TEL-001\`, \`EVID-LOG-002\`, \`EVID-CHG-003\`
   - The deployment modified table \`ledger_entries\` without backwards-compatible view.

## Verification Details
- **Condition 1:** 5xx error ratio dropped from 42.8% to 0.08% (baseline: 0.10%).
- **Condition 2:** \`transaction-api\` and \`ledger-service\` health observed HEALTHY.`,
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
            status: "awaiting_approval",
            current_step: "await_approval",
            model: "qwen3:8b",
            started_at: new Date(Date.now() - 45000).toISOString(),
            completed_at: null,
            error: null,
            error_class: null,
            created_at: new Date(Date.now() - 45000).toISOString(),
            updated_at: new Date().toISOString(),
            result: {
              classification: { category: "database_schema", confidence: 0.96, rationale: "Schema column drift between services", source: "model" },
              plan: { capabilities: ["telemetry", "dependencies", "changes", "knowledge"], notes: [] },
              rca: {
                summary: "Elevated HTTP 5xx errors on transaction-api were caused by deployment dep-ls-0042 in ledger-service which renamed column 'amount' to 'amount_cents' without a compatible view.",
                hypotheses: [
                  {
                    rank: 1,
                    title: "Incompatible schema migration in ledger-service",
                    category: "database_schema",
                    description: "Deployment dep-ls-0042 executed 1 minute before onset, altering column definitions expected by transaction-api.",
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
                  reason: "Restart target settlement-worker exhibits normal healthy telemetry with 0 errors (Abnormality Gate violated). Prompt injection attempt in error logs detected and quarantined.",
                  category: "unwarranted",
                },
              ],
              outcome: null,
            },
          }),
        });
      }

      if (url.includes("api/v1/approvals")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "act-mock-001",
              investigation_id: "inv-mock-001",
              incident_id: "inc-mock-001",
              action_type: "rollback_deployment",
              parameters: { service: "ledger-service", deployment_id: "dep-ls-0042" },
              params_hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
              rationale: "Revert incompatible schema migration dep-ls-0042 to restore column compatibility.",
              risk: "medium",
              status: "pending",
              requested_at: new Date(Date.now() - 5000).toISOString(),
              decided_at: null,
              decided_by: null,
              decision_comment: null,
              executed_at: null,
              execution_result: null,
              verification: null,
            },
          ]),
        });
      }

      if (url.includes("api/v1/knowledge/documents")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            { id: "doc-1", source_uri: "runbooks/database/schema_rollback.md", title: "Schema Migration Troubleshooting & Rollback", doc_type: "runbook", services: ["ledger-service"], version: 2, status: "active", duplicate_of: null, chunk_count: 8, updated_at: new Date().toISOString() },
            { id: "doc-2", source_uri: "runbooks/database/connection_pool.md", title: "Connection Pool Sizing & PostgreSQL Limits", doc_type: "runbook", services: ["ledger-db"], version: 3, status: "active", duplicate_of: null, chunk_count: 12, updated_at: new Date().toISOString() },
            { id: "doc-3", source_uri: "runbooks/queues/dlq_quarantine.md", title: "Dead-Letter Queue Poison Message Quarantine", doc_type: "runbook", services: ["settlement-worker"], version: 1, status: "active", duplicate_of: null, chunk_count: 6, updated_at: new Date().toISOString() },
          ]),
        });
      }

      return route.continue();
    });

    console.log("Capturing screenshots across Desktop (1440x900) and Mobile (390x844)...");

    // 1. Overview Page (Desktop)
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE_URL}/`);
    await page.waitForSelector("text=System overview");
    await page.screenshot({ path: `${OUT_DIR}/overview-desktop.png`, fullPage: true });
    console.log("✓ Captured overview-desktop.png");

    // 2. Overview Page (Mobile)
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE_URL}/`);
    await page.waitForSelector("text=System overview");
    await page.screenshot({ path: `${OUT_DIR}/overview-mobile.png`, fullPage: true });
    console.log("✓ Captured overview-mobile.png");

    // 3. Architecture Explorer (Desktop: System Diagram)
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE_URL}/architecture`);
    await page.waitForSelector("text=Interactive Architecture");
    await page.screenshot({ path: `${OUT_DIR}/architecture-system-desktop.png`, fullPage: true });
    console.log("✓ Captured architecture-system-desktop.png");

    // 4. Architecture Explorer (Desktop: Workflow Diagram)
    await page.getByRole("tab", { name: "Diagram B: Agent Workflow Graph" }).click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT_DIR}/architecture-workflow-desktop.png`, fullPage: true });
    console.log("✓ Captured architecture-workflow-desktop.png");

    // 5. Architecture Explorer (Desktop: RAG Pipeline)
    await page.getByRole("tab", { name: "Diagram C: RAG Pipeline" }).click();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT_DIR}/architecture-rag-desktop.png`, fullPage: true });
    console.log("✓ Captured architecture-rag-desktop.png");

    // 6. Architecture Explorer (Mobile)
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE_URL}/architecture`);
    await page.waitForSelector("text=Interactive Architecture");
    await page.screenshot({ path: `${OUT_DIR}/architecture-mobile.png`, fullPage: true });
    console.log("✓ Captured architecture-mobile.png");

    // 7. Developer Guide (Desktop)
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE_URL}/guide`);
    await page.waitForSelector("text=Developer & Operator Getting Started Guide");
    await page.screenshot({ path: `${OUT_DIR}/guide-desktop.png`, fullPage: true });
    console.log("✓ Captured guide-desktop.png");

    // 8. Developer Guide (Mobile)
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE_URL}/guide`);
    await page.waitForSelector("text=Developer & Operator Getting Started Guide");
    await page.screenshot({ path: `${OUT_DIR}/guide-mobile.png`, fullPage: true });
    console.log("✓ Captured guide-mobile.png");

    // 9. Safety Center (Desktop)
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE_URL}/safety`);
    await page.waitForSelector("text=Safety Architecture");
    await page.screenshot({ path: `${OUT_DIR}/safety-desktop.png`, fullPage: true });
    console.log("✓ Captured safety-desktop.png");

    // 10. Safety Center (Mobile)
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE_URL}/safety`);
    await page.waitForSelector("text=Safety Architecture");
    await page.screenshot({ path: `${OUT_DIR}/safety-mobile.png`, fullPage: true });
    console.log("✓ Captured safety-mobile.png");

    // 11. Incident Workspace (Desktop: Awaiting Approval)
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE_URL}/investigations/inv-mock-001`);
    await page.waitForSelector("text=OPERATOR ACTION REQUIRED");
    await page.screenshot({ path: `${OUT_DIR}/incident-workspace-approval-desktop.png`, fullPage: true });
    console.log("✓ Captured incident-workspace-approval-desktop.png");

    // 12. Incident Workspace (Desktop: Evidence Tab)
    await page.getByRole("button", { name: "Collected Evidence" }).click();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT_DIR}/incident-workspace-evidence-desktop.png`, fullPage: true });
    console.log("✓ Captured incident-workspace-evidence-desktop.png");

    // 13. Incident Workspace (Mobile)
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE_URL}/investigations/inv-mock-001`);
    await page.waitForSelector("text=OPERATOR ACTION REQUIRED");
    await page.screenshot({ path: `${OUT_DIR}/incident-workspace-mobile.png`, fullPage: true });
    console.log("✓ Captured incident-workspace-mobile.png");

    await browser.close();
    console.log("All screenshots captured successfully in docs/images/after/");
  } finally {
    server.kill("SIGTERM");
  }
}

main().catch((err) => {
  console.error("Screenshot capture failed:", err);
  process.exit(1);
});
