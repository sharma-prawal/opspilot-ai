import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "@playwright/test";

const PORT = 3458;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const WEB_DIR = path.resolve(import.meta.dirname, "..");
const OUT_DIR = path.resolve(import.meta.dirname, "../../../docs/images/redesign");
const ARTIFACT_DIR = "/Users/prawalsharma/.gemini/antigravity/brain/23573cec-f20e-4e56-85f1-f2e2d997c8c1/images";

for (const dir of [OUT_DIR, ARTIFACT_DIR]) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

async function waitForServer(url, timeoutMs = 25000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.status === 200 || res.status === 404) return true;
    } catch {
      // retry
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`Server did not respond at ${url} within ${timeoutMs}ms`);
}

// Realistic fixtures derived strictly from published v0.6.0 INC-002 trace and documentation
const MOCK_INCIDENT_SIMULATOR = {
  id: "inc-sim-002",
  reference: "INC-002",
  title: "Ledger Service Connection Pool Exhaustion on ledger-db",
  service: "ledger-db",
  environment_id: "production-us-east",
  severity: "critical",
  status: "mitigated",
  evidence_source: "simulator",
  description: "PostgreSQL connection pool on ledger-db saturated at 93% (130 active sessions). Sequential table scans on ledger_entries caused by ledger-service deployment dep-ls-0291.",
  detected_at: "2026-11-19T10:14:22Z",
  created_at: "2026-11-19T10:14:25Z",
};

const MOCK_INCIDENT_UPLOADED = {
  id: "inc-upload-001",
  reference: "UPL-8821",
  title: "Payment Gateway Latency Spike & Tokenizer 502s",
  service: "payment-gateway",
  environment_id: "production-eu-west",
  severity: "high",
  status: "mitigated",
  evidence_source: "upload",
  description: "Uploaded application logs, metrics CSV, and trace spans from incident window 09:30-10:15 UTC. Forensic read-only audit.",
  detected_at: "2026-11-19T09:31:00Z",
  created_at: "2026-11-19T10:16:00Z",
};

const MOCK_UPLOAD_DATASET = {
  id: "ds-upload-001",
  incident_id: "inc-upload-001",
  timezone: "UTC",
  created_at: "2026-11-19T10:16:00Z",
  retention_days: 14,
  affected_services: ["payment-gateway", "tokenizer"],
  files: [
    { index: 0, name: "payment-gateway.log", format: "text/plain", bytes: 148200, records: { log: 840 }, rejected: 0, issues: [] },
    { index: 1, name: "metrics-5xx.csv", format: "text/csv", bytes: 32400, records: { metric: 120 }, rejected: 0, issues: [] },
    { index: 2, name: "trace-samples.json", format: "application/json", bytes: 85200, records: { trace: 45 }, rejected: 0, issues: [] },
  ],
  queries: [],
  summary: {
    records: { log: 840, metric: 120, trace: 45 },
    rejected: 0,
    redactions: 2,
    services: ["payment-gateway", "tokenizer"],
    start: "2026-11-19T09:30:00Z",
    end: "2026-11-19T10:15:00Z",
    warnings: [],
  },
};

const MOCK_UPLOAD_INVESTIGATION = {
  id: "inv-upload-001",
  incident_id: "inc-upload-001",
  status: "completed",
  current_step: "done",
  model: "qwen3.5:9b-q4_K_M",
  created_at: "2026-11-19T10:16:30Z",
  updated_at: "2026-11-19T10:17:15Z",
  result: {
    outcome: {
      code: "analysis_complete",
      read_only: true,
      summary: "Read-only forensic audit complete: identified tokenizer connection timeout cascade.",
      reason: "Retrospective analysis of uploaded telemetry. Action execution and live recovery verification are disabled in read-only audit mode.",
      suggested_steps: 2,
      actions_executed: 0,
      steps_planned: 0,
    },
  },
};

const MOCK_INVESTIGATION = {
  id: "inv-sim-002",
  incident_id: "inc-sim-002",
  status: "completed",
  current_step: "done",
  model: "qwen3.5:9b-q4_K_M",
  started_at: "2026-11-19T10:14:30Z",
  completed_at: "2026-11-19T10:16:45Z",
  created_at: "2026-11-19T10:14:30Z",
  updated_at: "2026-11-19T10:16:45Z",
  result: {
    classification: {
      category: "deployment_regression",
      confidence: 0.95,
      rationale: "ledger-service deployment 2.9.1 introduced an unindexed query, causing sequential scans and connection pool exhaustion.",
      source: "classifier",
    },
    plan: {
      capabilities: ["telemetry", "changes", "knowledge"],
      notes: ["Gather database pool telemetry", "Inspect deployment diff dep-ls-0291", "Review capacity invariants"],
    },
    rca: {
      summary: "ledger-service deployment 2.9.1 introduced an unindexed query on ledger_entries. The model initially proposed scaling the connection pool, but deterministic safety gate D25 blocked it as unsafe (>90% capacity). Rollback of deployment dep-ls-0291 was approved and successfully mitigated the incident.",
      hypotheses: [
        {
          rank: 1,
          title: "ledger-service deployment dep-ls-0291 caused connection pool exhaustion on ledger-db",
          category: "deployment_regression",
          description: "Deployment 2.9.1 introduced an endpoint querying ledger_entries without an index, consuming ~130 connections in sequential scans and driving pool to 93% saturation.",
          confidence: 0.95,
          supporting_evidence_ids: ["EVID-001", "EVID-002", "EVID-004"],
          contradicting_evidence_ids: [],
        },
        {
          rank: 2,
          title: "Transient traffic spike on checkout gateway",
          category: "external",
          description: "Traffic increase started 15 minutes before incident onset and leveled off; does not correlate with connection duration.",
          confidence: 0.15,
          supporting_evidence_ids: [],
          contradicting_evidence_ids: ["EVID-003"],
        },
        {
          rank: 3,
          title: "Missing index on ledger_entries(account_id, created_at)",
          category: "database",
          description: "Database sequential scans confirmed, but root trigger is the newly introduced deployment calling this query path.",
          confidence: 0.70,
          supporting_evidence_ids: ["EVID-001", "EVID-005"],
          contradicting_evidence_ids: [],
        },
      ],
      evidence_gaps: [],
      followups: ["Add index on ledger_entries(account_id, created_at)", "Verify migration review checklist in CI"],
      remediation: {
        summary: "Rolled back deployment dep-ls-0291 on ledger-service. Unsafe pool expansion blocked by capacity gate.",
        action: "rollback_deployment",
      },
    },
    remediation_plan: [
      {
        step: 1,
        action_id: "act-01",
        action_type: "rollback_deployment",
        parameters: { service: "ledger-service", deployment_id: "dep-ls-0291" },
        params_hash: "8a9d37ae27e7d2b5ab7e944b43c591c746e8d0ace194cd521ed06f0c0e92ee7f",
        rationale: "Revert ledger-service deployment 2.9.1 to remove the slow unindexed query and release connection pool pressure.",
        risk: "Low. Previous version 2.8.4 is verified healthy.",
        role: "resolution",
      },
    ],
    safety_evaluations: [
      {
        gate: "GATE-01: Capacity Invariant (Safety Gate D25)",
        decision: "BLOCKED",
        reason: "Proposed scale_connection_pool ledger-db -> 80 exceeds 90% usable connection limit (200 ceiling). Unsafe action blocked by deterministic gate.",
      },
      {
        gate: "GATE-02: Blast Radius Fencing",
        decision: "PASSED",
        reason: "Target service ledger-service is within production-us-east fault domain.",
      },
      {
        gate: "GATE-03: Authenticated Human Approval",
        decision: "PASSED",
        reason: "Rollback execution paused at deterministic gate; approved with authenticated operator token.",
      },
    ],
    rejected_proposals: [
      {
        proposal: { action: "scale_connection_pool", service: "ledger-db", max_connections: 80 },
        reason: "GATE-CAPACITY: Projected connections (80 per replica) exceed 90% database ceiling on ledger-db. Unsafe pool expansion blocked.",
        category: "safety_gate_rejection",
      },
    ],
    approval: {
      decision: "approved",
      decided_by: "operator",
      decided_at: "2026-11-19T10:15:45Z",
      comment: "Approved rollback of dep-ls-0291 after verifying safety gate blocked unsafe pool expansion.",
    },
    verification: {
      recovered: true,
      notes: "Post-remediation verified: ledger-db active connections dropped from 93% to 18%, latency normalized to SLO baseline.",
      observed_before: 8240,
      observed_after: 142,
    },
    outcome: {
      code: "mitigated",
      summary: "Incident mitigated through deployment rollback (dep-ls-0291). Unsafe pool expansion blocked by capacity safety gate.",
      escalate: false,
      reason: "Recovery criteria met and independently verified.",
      actions_executed: 1,
      steps_planned: 1,
    },
  },
};

const MOCK_EVENTS = [
  { id: 1, event_type: "alert_triggered", node: "intake", created_at: "2026-11-19T10:14:22Z", payload: { observations: [{ agent: "monitor", finding: "ledger-db connection pool hit 93% saturation" }] } },
  { id: 2, event_type: "plan_created", node: "plan", created_at: "2026-11-19T10:14:30Z", payload: { observations: [{ agent: "planner", finding: "Formulated forensic telemetry and git audit plan" }] } },
  { id: 3, event_type: "evidence_gathered", node: "gather_evidence", created_at: "2026-11-19T10:14:45Z", payload: { tool_calls: [{ id: "t1", tool: "pg_stat_activity", status: "success", latency_ms: 120 }], evidence_ids: ["EVID-001", "EVID-002", "EVID-004"] } },
  { id: 4, event_type: "hypotheses_ranked", node: "formulate_hypotheses", created_at: "2026-11-19T10:15:00Z", payload: { observations: [{ agent: "reasoning", finding: "Rank 1 hypothesis confirmed (confidence 95%)" }] } },
  { id: 5, event_type: "safety_gated", node: "safety_check", created_at: "2026-11-19T10:15:20Z", payload: { observations: [{ agent: "safety_kernel", finding: "Capacity Gate D25 blocked unsafe scale_connection_pool proposal" }] } },
  { id: 6, event_type: "approval_requested", node: "human_approval", created_at: "2026-11-19T10:15:45Z", payload: { observations: [{ agent: "auth", finding: "Rollback dep-ls-0291 approved by operator" }] } },
  { id: 7, event_type: "action_executed", node: "remediate", created_at: "2026-11-19T10:16:10Z", payload: { observations: [{ agent: "action_server", finding: "Rolled back dep-ls-0291 on ledger-service" }] } },
  { id: 8, event_type: "recovery_verified", node: "verify_recovery", created_at: "2026-11-19T10:16:40Z", payload: { observations: [{ agent: "verification", finding: "Connections returned to 18%; latency normalized" }] } },
  { id: 9, event_type: "workflow_completed", node: "report", created_at: "2026-11-19T10:16:45Z", payload: { observations: [{ agent: "reporter", finding: "RCA postmortem dossier published" }] } },
];

const MOCK_EVIDENCE = [
  {
    evidence_id: "EVID-001",
    kind: "metric",
    service: "ledger-db",
    source_tool: "postgresql:active_connections",
    summary: "ledger-db connection pool hit 93% saturation ceiling (130 active sessions)",
    data: {
      metric: "pg_stat_activity",
      value: 130,
      ceiling: 140,
      state: "saturated",
      attributes: { source_ref: "pg_stat_activity:active_connections{db='ledger-db'}" },
    },
    collected_at: "2026-11-19T10:14:15Z",
  },
  {
    evidence_id: "EVID-002",
    kind: "log",
    service: "ledger-service",
    source_tool: "loki:ledger-service.log",
    summary: "Slow sequential query scanning ledger_entries table without index",
    data: {
      level: "WARN",
      message: "QueryExecutionTimeWarning: SELECT * FROM ledger_entries WHERE account_id = $1 took 4210ms (seq scan)",
      attributes: { source_ref: "loki:ledger-service.log#L2104-L2118" },
    },
    collected_at: "2026-11-19T10:14:18Z",
  },
  {
    evidence_id: "EVID-003",
    kind: "metric",
    service: "transaction-api",
    source_tool: "prometheus:http_requests_total",
    summary: "Inbound traffic increase started 15 min earlier and plateaued; does not account for connection hold time",
    data: {
      metric: "http_requests_total",
      rate: "410 rps",
      attributes: { source_ref: "promql:rate(http_requests_total[5m])" },
    },
    collected_at: "2026-11-19T10:14:20Z",
  },
  {
    evidence_id: "EVID-004",
    kind: "change",
    service: "ledger-service",
    source_tool: "git:deployments",
    summary: "Deployment dep-ls-0291 (v2.9.1) deployed 12 minutes prior to pool saturation",
    data: {
      commit: "f4a19e",
      author: "backend-team",
      deployment_id: "dep-ls-0291",
      message: "feat(ledger): add account statement export endpoint",
      attributes: { source_ref: "git:ledger-service@f4a19e#dep-ls-0291" },
    },
    collected_at: "2026-11-19T10:10:00Z",
  },
  {
    evidence_id: "EVID-005",
    kind: "trace",
    service: "ledger-db",
    source_tool: "tempo:trace-ledger-query-9941",
    summary: "Trace shows 4.2s execution time spent inside database sequential scan",
    data: {
      trace_id: "trace-ledger-query-9941",
      duration_ms: 4215,
      status: "SLOW_QUERY",
      attributes: { source_ref: "tempo:span/ledger-db-exec-9941" },
    },
    collected_at: "2026-11-19T10:14:25Z",
  },
];

async function main() {
  console.log("Starting Next.js production server on port", PORT);
  const server = spawn("pnpm", ["next", "start", "-p", String(PORT)], {
    cwd: WEB_DIR,
    stdio: "inherit",
    env: {
      ...process.env,
      PORT: String(PORT),
      OPSPILOT_WEB_SESSION_SECRET: process.env.OPSPILOT_WEB_SESSION_SECRET || "ops-pilot-session-secret-for-screenshots-must-be-32-chars-long",
      OPSPILOT_WEB_OPERATOR_PASSPHRASE: process.env.OPSPILOT_WEB_OPERATOR_PASSPHRASE || "operator-passphrase-must-be-12-chars",
    },
  });

  try {
    await waitForServer(`${BASE_URL}/`);
    console.log("Next.js server is ready at", BASE_URL);

    const browser = await chromium.launch();

    const SESSION_SECRET = "c018a1e23f05d9a9b24479e00184b91f1a56c32174de62f83190ab74c83e10fa";
    function createSessionCookie(secret, sub = "operator", role = "operator") {
      const session = {
        sub,
        role,
        exp: Math.floor(Date.now() / 1000) + 8 * 3600,
        csrf: crypto.randomBytes(24).toString("base64url"),
      };
      const body = Buffer.from(JSON.stringify(session)).toString("base64url");
      const sig = crypto.createHmac("sha256", secret).update(body).digest("base64url");
      return { cookieValue: `${body}.${sig}`, session };
    }
    const { cookieValue, session: mockSession } = createSessionCookie(SESSION_SECRET);

    // Desktop Context (1440x960)
    const desktopContext = await browser.newContext({
      viewport: { width: 1440, height: 960 },
      deviceScaleFactor: 2,
    });
    await desktopContext.addCookies([
      { name: "opspilot_session", value: cookieValue, url: BASE_URL },
    ]);
    const desktopPage = await desktopContext.newPage();

    // Mobile Context (390x844)
    const mobileContext = await browser.newContext({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      deviceScaleFactor: 2,
    });
    await mobileContext.addCookies([
      { name: "opspilot_session", value: cookieValue, url: BASE_URL },
    ]);
    const mobilePage = await mobileContext.newPage();

    // Route Interception for realistic Mock Data across both contexts
    for (const page of [desktopPage, mobilePage]) {
      await page.route("**/api/session", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            authenticated: true,
            role: "operator",
            sub: "operator",
            csrf: mockSession.csrf,
            exp: mockSession.exp,
          }),
        });
      });

      await page.route("**/api/ops/api/v1/system/overview", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            incidents: { open: 1, investigating: 1, mitigated: 4 },
            investigations: { queued: 0, running: 1, completed: 5 },
            actions: { pending: 1, executed: 6 },
            knowledge: { documents: 8, chunks: 64 },
            runtime: {
              llm_model: "qwen3.5:9b-q4_K_M",
              embedding_model: "qwen3-embedding:0.6b",
              mcp_read_tools: ["query_loki", "query_prometheus", "read_git_diff", "pg_stat_activity"],
              mcp_action_tools: ["rollback_deployment", "scale_connection_pool"],
              max_concurrent_investigations: 4,
              agent_budgets: { tool_calls: 15, duration_seconds: 180 },
            },
          }),
        });
      });

      await page.route("**/api/ops/api/v1/system/identity", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            version: "0.7.0",
            instance: "screenshot-harness",
            database: "opspilot_test",
            llm_model: "qwen3.5:9b-q4_K_M",
            embedding_model: "qwen3-embedding:0.6b",
            connectors: { loki: true, prometheus: true },
          }),
        });
      });

      await page.route("**/api/ops/api/v1/incidents", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MOCK_INCIDENT_SIMULATOR, MOCK_INCIDENT_UPLOADED]),
        });
      });

      await page.route("**/api/ops/api/v1/incidents/inc-sim-002", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_INCIDENT_SIMULATOR),
        });
      });

      await page.route("**/api/ops/api/v1/incidents/inc-upload-001", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_INCIDENT_UPLOADED),
        });
      });

      await page.route("**/api/ops/api/v1/incidents/inc-upload-001/dataset", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_UPLOAD_DATASET),
        });
      });

      await page.route("**/api/ops/api/v1/incidents/inc-upload-001/investigations", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MOCK_UPLOAD_INVESTIGATION]),
        });
      });

      await page.route("**/api/ops/api/v1/incidents/inc-sim-002/investigations", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([MOCK_INVESTIGATION]),
        });
      });

      await page.route("**/api/ops/api/v1/investigations/inv-sim-002", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_INVESTIGATION),
        });
      });

      await page.route("**/api/ops/api/v1/investigations/inv-upload-001", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_UPLOAD_INVESTIGATION),
        });
      });

      await page.route("**/api/ops/api/v1/investigations/inv-sim-002/evidence", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_EVIDENCE),
        });
      });

      await page.route("**/api/ops/api/v1/investigations/inv-sim-002/events", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_EVENTS),
        });
      });

      await page.route("**/api/ops/api/v1/investigations/inv-sim-002/tool-calls", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      });

      await page.route("**/api/ops/api/v1/investigations/inv-sim-002/actions", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      });

      await page.route("**/api/ops/api/v1/investigations/inv-sim-002/report", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            status: "ready",
            markdown: `# Forensic RCA: INC-002 Ledger Service Connection Pool Exhaustion\n\n**Service:** ledger-db / ledger-service\n**Detected:** 2026-11-19 10:14:22 UTC\n**Mitigated:** 2026-11-19 10:16:45 UTC\n**Outcome:** Mitigated via rollback_deployment dep-ls-0291 (recovery independently verified)\n\n## Safety Gate Evaluation\n- **GATE-CAPACITY (Safety Gate D25):** BLOCKED unsafe proposal to scale ledger-db connection pool to 80 (exceeds 90% database ceiling).\n- **Remediation Resolution:** Approved rollback of deployment dep-ls-0291 (v2.9.1 -> v2.8.4).\n\n## Post-Remediation Verification\nActive database connections on ledger-db normalized from 93% saturation (130 active sessions) to 18% baseline (25 active sessions). Latency and 5xx error rates returned to SLO baseline.`,
          }),
        });
      });

      await page.route("**/api/ops/health/dependencies", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            checks: {
              postgres: { ok: true, pgvector: "0.8.0", migration: "head", latency_ms: 1.2 },
              ollama: { ok: true, version: "0.1.24", llm: { model: "qwen3.5:9b-q4_K_M" } },
              execution_owner: { ok: true, owner: "opspilot-owner", database: "opspilot_test" },
              mcp_read: { ok: true, server: "opspilot-read", tools: 13 },
              mcp_actions: { ok: true, server: "opspilot-actions", tools: 2 },
            },
            config: {
              llm_model: "qwen3.5:9b-q4_K_M",
              embedding_model: "qwen3-embedding:0.6b",
              embedding_dimensions: 1024,
              mcp_transport: "stdio",
              max_concurrent_investigations: 4,
            },
          }),
        });
      });

      await page.route("**/api/ops/api/v1/incidents/scenarios", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            { key: "INC-001", title: "Checkout DB Connection Pool Exhaustion" },
            { key: "INC-002", title: "Ledger Service Connection Pool Exhaustion" },
            { key: "INC-003", title: "Auth Redis Failover Storm" },
            { key: "INC-004", title: "Inventory gRPC Deadline Exceeded" },
            { key: "INC-005", title: "Payment Webhook Circuit Breaker Open" },
            { key: "INC-006", title: "Search Re-indexing Memory Pressure" },
          ]),
        });
      });

      await page.route("**/api/ops/api/v1/approvals*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      });

      await page.route("**/api/ops/api/v1/connectors*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            loki: { configured: true, name: "Grafana Loki", signal: "log" },
            prometheus: { configured: true, name: "Prometheus", signal: "metric" },
          }),
        });
      });
    }

    const captures = [
      // Desktop Captures
      { name: "redesign-intake-home-desktop.png", url: "/", type: "desktop" },
      { name: "redesign-incidents-roster-desktop.png", url: "/incidents", type: "desktop" },
      { name: "redesign-investigation-workbench-desktop.png", url: "/investigations/inv-sim-002", type: "desktop" },
      { name: "redesign-incident-dossier-readonly-desktop.png", url: "/incidents/inc-upload-001", type: "desktop" },
      { name: "redesign-architecture-desktop.png", url: "/architecture", type: "desktop" },
      { name: "redesign-safety-desktop.png", url: "/safety", type: "desktop" },
      { name: "redesign-guide-desktop.png", url: "/guide", type: "desktop" },
      // Mobile Captures
      { name: "redesign-intake-home-mobile.png", url: "/", type: "mobile" },
      { name: "redesign-investigation-workbench-mobile.png", url: "/investigations/inv-sim-002", type: "mobile" },
      { name: "redesign-guide-mobile.png", url: "/guide", type: "mobile" },
    ];

    for (const c of captures) {
      const page = c.type === "desktop" ? desktopPage : mobilePage;
      console.log(`Capturing [${c.type}] ${c.name} at ${c.url}...`);
      await page.goto(`${BASE_URL}${c.url}`, { waitUntil: "networkidle" });
      await page.waitForTimeout(600);
      console.log(`Page URL after navigation: ${page.url()}`);

      // Smoke check: Ensure page did not crash into an error boundary
      const errorBoundaryCount = await page.locator("text=/This page couldn['’]t load|Application error/i").count();
      if (errorBoundaryCount > 0) {
        throw new Error(`Page at ${c.url} rendered an error boundary!`);
      }
      if (c.url === "/") {
        const heading = page.getByRole("heading", { name: "System overview" });
        await heading.waitFor({ state: "visible", timeout: 5000 });
      }

      const outPath = path.join(OUT_DIR, c.name);
      await page.screenshot({ path: outPath, fullPage: false });

      const artifactPath = path.join(ARTIFACT_DIR, c.name);
      fs.copyFileSync(outPath, artifactPath);
      console.log(`Saved -> ${outPath}`);
    }

    await browser.close();
    console.log("All screenshots captured and saved successfully!");
  } finally {
    server.kill("SIGTERM");
  }
}

main().catch((err) => {
  console.error("Screenshot capture failed:", err);
  process.exit(1);
});
