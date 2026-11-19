import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { chromium } from "@playwright/test";

const PORT = 3458;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const OUT_DIR = path.resolve(process.cwd(), "../../docs/images/redesign");
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

// Exact schema matching types.ts
const MOCK_INCIDENT_SIMULATOR = {
  id: "inc-sim-002",
  reference: "INC-002",
  title: "Checkout API Database Connection Pool Exhaustion",
  service: "checkout-api",
  environment_id: "production-us-east",
  severity: "critical",
  status: "mitigated",
  evidence_source: "simulator",
  description: "Checkout service p99 latency surged to 8,240ms with 34% HTTP 500 errors. HikariCP connection pool hit 100% saturation (50/50 active).",
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

const MOCK_INVESTIGATION = {
  id: "inv-sim-002",
  incident_id: "inc-sim-002",
  status: "completed",
  current_step: "done",
  model: "llama3.1:8b",
  started_at: "2026-11-19T10:14:30Z",
  completed_at: "2026-11-19T10:16:45Z",
  created_at: "2026-11-19T10:14:30Z",
  updated_at: "2026-11-19T10:16:45Z",
  result: {
    classification: {
      category: "resource_exhaustion",
      confidence: 0.94,
      rationale: "Database connection pool reached saturation limit under heavy checkout traffic.",
      source: "classifier",
    },
    plan: {
      capabilities: ["metrics", "logs", "traces", "git_history"],
      notes: ["Gather HikariCP telemetry", "Inspect PostgreSQL pg_stat_activity", "Check deployment events"],
    },
    rca: {
      summary: "The checkout-api HikariCP pool was configured for a maximum of 10 connections. A concurrent promotional campaign increased inbound traffic from 240 to 780 rps, causing connection timeouts (p99 > 8s) and subsequent HTTP 500 error cascade.",
      hypotheses: [
        {
          rank: 1,
          title: "HikariCP pool size fixed at 10 while checkout traffic tripled post-campaign launch",
          category: "configuration",
          description: "PostgreSQL metrics verify pg_stat_activity connection count saturated at pool ceiling (50/50). Metrics confirm checkout traffic surge from 240 rps to 780 rps.",
          confidence: 0.94,
          supporting_evidence_ids: ["EVID-001", "EVID-002", "EVID-004"],
          contradicting_evidence_ids: [],
        },
        {
          rank: 2,
          title: "Slow query lock contention on order_items table",
          category: "database",
          description: "Lock wait times remained below 4ms across all active transactions; pg_locks shows no exclusive locks.",
          confidence: 0.12,
          supporting_evidence_ids: [],
          contradicting_evidence_ids: ["EVID-003"],
        },
        {
          rank: 3,
          title: "Network socket leak between checkout pods and RDS proxy",
          category: "infrastructure",
          description: "TCP ESTABLISHED counts match active pool metrics; no socket allocation errors or TIME_WAIT buildup.",
          confidence: 0.05,
          supporting_evidence_ids: [],
          contradicting_evidence_ids: ["EVID-005"],
        },
      ],
      evidence_gaps: [],
      followups: ["Implement auto-scaling for connection pool", "Review database connection limits"],
      remediation: {
        summary: "Scaled HikariCP maximumPoolSize from 10 to 40 connections on checkout-api pods.",
        action: "scale_connection_pool",
      },
    },
    remediation_plan: [
      {
        step: 1,
        action_id: "act-01",
        action_type: "scale_connection_pool",
        parameters: { service: "checkout-api", max_connections: "40" },
        params_hash: "hash_40conn",
        rationale: "Increase connection pool ceiling to absorb peak checkout traffic.",
        risk: "Low. RDS database has 150 available connections.",
        role: "operator",
      },
      {
        step: 2,
        action_id: "act-02",
        action_type: "verify_latency",
        parameters: { service: "checkout-api", target_p99_ms: "300" },
        params_hash: "hash_verify",
        rationale: "Verify recovery before closing incident dossier.",
        risk: "None. Read-only verification.",
        role: "operator",
      },
    ],
    safety_evaluations: [
      {
        gate: "GATE-01: Parameter Range Invariant",
        decision: "PASSED",
        reason: "Requested max_connections=40 is within safe RDS instance ceiling (max 150).",
      },
      {
        gate: "GATE-02: Blast Radius Fencing",
        decision: "PASSED",
        reason: "Target service checkout-api is in staging/production tenant isolated pool.",
      },
      {
        gate: "GATE-03: Deterministic Approval Requirement",
        decision: "PASSED",
        reason: "State-changing remediation successfully paused at interrupt() gate for human token signature.",
      },
    ],
    rejected_proposals: [
      {
        proposal: { action: "restart_rds_cluster", service: "postgres-primary" },
        reason: "GATE-BLAST-RADIUS: Restarting database cluster violates safety invariant — exceeds single-service blast radius.",
        category: "safety_gate_rejection",
      },
    ],
    approval: {
      decision: "approved",
      decided_by: "operator-prawal",
      decided_at: "2026-11-19T10:15:45Z",
      comment: "Approved pool expansion to 40 connections after verifying RDS headroom.",
    },
    verification: {
      recovered: true,
      notes: "Post-remediation verified: p99 latency normalized to 142ms, 0 HTTP 500 errors across 12,000 requests.",
      observed_before: 8240,
      observed_after: 142,
    },
    outcome: {
      code: "resolved",
      summary: "Incident resolved through connection pool expansion and validated recovery.",
      escalate: false,
      reason: "Recovery criteria met.",
      actions_executed: 2,
      steps_planned: 2,
    },
  },
};

const MOCK_EVENTS = [
  { id: 1, event_type: "alert_triggered", node: "intake", created_at: "2026-11-19T10:14:22Z", payload: { observations: [{ agent: "monitor", finding: "p99 latency 8240ms on checkout-api" }] } },
  { id: 2, event_type: "evidence_gathered", node: "gather_evidence", created_at: "2026-11-19T10:14:35Z", payload: { tool_calls: [{ id: "t1", tool: "query_prometheus", status: "success", latency_ms: 120 }], evidence_ids: ["EVID-001", "EVID-002"] } },
  { id: 3, event_type: "hypotheses_ranked", node: "formulate_hypotheses", created_at: "2026-11-19T10:14:50Z", payload: { observations: [{ agent: "reasoning", finding: "Rank 1 hypothesis confirmed (confidence 94%)" }] } },
  { id: 4, event_type: "runbook_retrieved", node: "retrieve_runbooks", created_at: "2026-11-19T10:15:05Z", payload: { observations: [{ agent: "rag", finding: "HikariCP Connection Pool Runbook (hybrid score 0.94)" }] } },
  { id: 5, event_type: "safety_gated", node: "safety_check", created_at: "2026-11-19T10:15:20Z", payload: { observations: [{ agent: "safety_kernel", finding: "All 3 deterministic invariant gates passed" }] } },
  { id: 6, event_type: "human_approved", node: "human_approval", created_at: "2026-11-19T10:15:45Z", payload: { observations: [{ agent: "auth", finding: "Operator token verified" }] } },
  { id: 7, event_type: "action_executed", node: "remediate", created_at: "2026-11-19T10:16:10Z", payload: { observations: [{ agent: "action_server", finding: "Scaled pool to 40" }] } },
  { id: 8, event_type: "recovery_verified", node: "verify_recovery", created_at: "2026-11-19T10:16:40Z", payload: { observations: [{ agent: "verification", finding: "Latency normalized to 142ms" }] } },
];

const MOCK_EVIDENCE = [
  {
    evidence_id: "EVID-001",
    kind: "metric",
    service: "checkout-api",
    source_tool: "prometheus:hikaricp_active_connections",
    summary: "HikariCP active connections hit maximum limit 50/50 (100% saturation)",
    data: {
      metric: "hikaricp_active_connections",
      value: 50,
      ceiling: 50,
      state: "saturated",
      attributes: { source_ref: "promql:hikaricp_active_connections{service='checkout-api'}" },
    },
    collected_at: "2026-11-19T10:14:15Z",
  },
  {
    evidence_id: "EVID-002",
    kind: "log",
    service: "checkout-api",
    source_tool: "loki:checkout-api.log",
    summary: "Connection acquisition timeout in checkout request worker pool",
    data: {
      level: "ERROR",
      message: "ConnectionTimeoutException: Connection is not available, request timed out after 30000ms",
      attributes: { source_ref: "loki:checkout-api.log#L1482-L1490" },
    },
    collected_at: "2026-11-19T10:14:18Z",
  },
  {
    evidence_id: "EVID-003",
    kind: "metric",
    service: "postgres-primary",
    source_tool: "prometheus:pg_stat_database_locks",
    summary: "PostgreSQL table lock wait times remain nominal (<4ms)",
    data: {
      metric: "pg_stat_database_locks",
      lock_wait_ms: 3.2,
      exclusive_locks: 0,
      attributes: { source_ref: "promql:rate(pg_stat_database_locks[5m])" },
    },
    collected_at: "2026-11-19T10:14:20Z",
  },
  {
    evidence_id: "EVID-004",
    kind: "change",
    service: "marketing-gateway",
    source_tool: "git:deployments",
    summary: "Traffic campaign initiated 4 minutes prior to latency spike",
    data: {
      commit: "b89f21",
      author: "growth-team",
      message: "Launch CyberWeek early-bird email blast",
      attributes: { source_ref: "git:repo/growth-gateway@b89f21" },
    },
    collected_at: "2026-11-19T10:10:00Z",
  },
  {
    evidence_id: "EVID-005",
    kind: "trace",
    service: "rds-proxy",
    source_tool: "tempo:trace-checkout-4889",
    summary: "Trace span shows 30s delay waiting for database socket checkout",
    data: {
      trace_id: "trace-checkout-4889",
      duration_ms: 30012,
      status: "TIMEOUT",
      attributes: { source_ref: "tempo:span/rds-checkout-acquire-4889" },
    },
    collected_at: "2026-11-19T10:14:25Z",
  },
];

async function main() {
  console.log("Starting Next.js production server on port", PORT);
  const server = spawn("pnpm", ["next", "start", "-p", String(PORT)], {
    stdio: "inherit",
    env: { ...process.env, PORT: String(PORT) },
  });

  try {
    await waitForServer(`${BASE_URL}/`);
    console.log("Next.js server is ready at", BASE_URL);

    const browser = await chromium.launch();

    // Desktop Context (1440x960)
    const desktopContext = await browser.newContext({
      viewport: { width: 1440, height: 960 },
      deviceScaleFactor: 2,
    });
    const desktopPage = await desktopContext.newPage();

    // Mobile Context (390x844)
    const mobileContext = await browser.newContext({
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      deviceScaleFactor: 2,
    });
    const mobilePage = await mobileContext.newPage();

    // Route Interception for realistic Mock Data across both contexts
    for (const page of [desktopPage, mobilePage]) {
      await page.route("**/api/session", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ authenticated: true, role: "operator", sub: "operator-prawal", csrf: "token-9988" }),
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
              llm_model: "llama3.1:8b",
              embedding_model: "bge-m3:latest",
              mcp_read_tools: ["query_loki", "query_prometheus", "read_git_diff", "pg_stat_activity"],
              mcp_action_tools: ["scale_connection_pool", "rollback_deployment"],
              max_concurrent_investigations: 4,
              agent_budgets: { tool_calls: 15, duration_seconds: 180 },
            },
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

      await page.route("**/api/ops/api/v1/incidents/*/investigations", async (route) => {
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
            markdown: `# Forensic RCA: INC-002 Checkout API Database Connection Pool Exhaustion\n\n**Service:** checkout-api\n**Detected:** 2026-11-19 10:14:22 UTC\n**Mitigated:** 2026-11-19 10:16:45 UTC\n\n## Root Cause\nHikariCP connection pool hit 100% saturation due to promotional traffic surge.\n\n## Remediation\nScaled connection pool maximum to 40 connections. Post-remediation p99 normalized to 142ms.`,
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
