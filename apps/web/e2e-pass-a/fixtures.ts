import type { Page } from "@playwright/test";

export const incidentId = "11111111-1111-4111-8111-111111111111";
export const investigationId = "22222222-2222-4222-8222-222222222222";
export const actionId = "33333333-3333-4333-8333-333333333333";
const at = "2026-11-20T12:00:00Z";
export const incidents = Array.from({ length: 75 }, (_, n) => ({
  id: n === 0 ? incidentId : `11111111-1111-4111-8111-${String(n).padStart(12, "0")}`,
  reference: `SYNTHETIC-${String(n + 1).padStart(3, "0")}`,
  title: n === 74 ? "Older needle case" : "Synthetic saved case",
  description: "Explicitly synthetic Pass A fixture", severity: "SEV2", status: n % 2 ? "resolved" : "open",
  service: "checkout-api", evidence_source: n % 3 ? "upload" : "simulator", environment_id: null,
  detected_at: at, created_at: at,
}));
export const metric = {
  evidence_id: "ev-historical", kind: "metric_anomaly", source_tool: "query_metrics", collected_by: "telemetry",
  service: "checkout-api", summary: "Synthetic historical metric", data: {
    metric: "http_5xx_ratio", baseline: 0, extreme: 0.4, current: 0.3, unit: "ratio",
  }, citation: null, relevance: 0.9, observed_at: at,
};
export async function fixture(page: Page, options: {
  authorization?: "approve" | "reject" | "expired" | "pending" | "unknown" | "unavailable";
  source?: "simulator" | "upload";
  observationTime?: string | null;
} = {}) {
  const source = options.source ?? "simulator";
  const authorization = options.authorization ?? "approve";
  const pending = authorization === "pending";
  const action = {
    id: actionId, investigation_id: investigationId, incident_id: incidentId,
    action_type: "restart_service", parameters: { service: "checkout-api" }, params_hash: "a".repeat(64),
    rationale: "Synthetic saved action", risk: "low", status: pending ? "pending" : "succeeded", requested_at: at,
    decided_at: pending ? null : "2026-11-20T12:02:00Z", decided_by: pending ? null : "execution-record", decision_comment: null,
    executed_at: pending ? null : "2026-11-20T12:01:00Z", execution_result: pending ? null : { status: "succeeded" },
    verification: pending ? null : { recovered: true, notes: "Synthetic sandbox verification" },
    authorization: ["unknown", "unavailable", "pending"].includes(authorization) ? null : "[REDACTED]",
    decision_history: ["unknown", "unavailable", "pending"].includes(authorization) ? null : {
      decision: authorization, decided_by: "original-sre", decided_at: at,
    },
  };
  await page.route("**/api/session", route => route.fulfill({ json: route.request().method() === "DELETE" ? { authenticated: false } : {
    authenticated: true, sub: "synthetic-operator", role: "operator", csrf: "synthetic-test-csrf",
  } }));
  await page.route("**/api/ops/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/ops/", "");
    let body: unknown = [];
    if (path === "api/v1/incidents/search") {
      const q = (url.searchParams.get("q") ?? "").trim().toLowerCase();
      const sourceFilter = url.searchParams.get("source");
      const status = url.searchParams.get("status");
      const offset = Number(url.searchParams.get("offset") ?? 0), limit = Number(url.searchParams.get("limit") ?? 50);
      const matching = incidents.filter(i => `${i.reference} ${i.title} ${i.service}`.toLowerCase().includes(q) &&
        (!sourceFilter || i.evidence_source === sourceFilter) && (!status || i.status === status));
      body = { items: matching.slice(offset, offset + limit), total: matching.length, limit, offset };
    } else if (path === "api/v1/incidents") body = incidents.slice(0, 50);
    else if (path === "api/v1/incidents/scenarios") body = [{ key: "INC-001", title: "Synthetic unusually long scenario label that must shrink without moving the Simulate button outside the viewport" }];
    else if (path === `api/v1/incidents/${incidentId}`) body = { ...incidents[0], evidence_source: source, status: "resolved" };
    else if (path === `api/v1/investigations/${investigationId}`) body = {
      id: investigationId, incident_id: incidentId, status: "completed", current_step: "report", model: "synthetic-model",
      started_at: at, completed_at: "2026-11-20T12:03:00Z", created_at: at, updated_at: at, error: null, error_class: null,
      executing_in_process: false, result: {
        rca: { summary: "Synthetic saved investigation", hypotheses: [], evidence_gaps: [] },
        remediation_plan: [], executions: pending ? [] : [{ step: 1, status: "succeeded", message: "Synthetic", action_type: "restart_service" }],
        verification: pending ? null : { recovered: true, notes: "Synthetic sandbox verification" },
      },
    };
    else if (path.endsWith("/actions")) {
      if (authorization === "unavailable") return route.fulfill({ status: 503, json: { error: { message: "Synthetic history unavailable" } } });
      body = source === "simulator" ? [action] : [];
    } else if (path.endsWith("/evidence")) body = [{ ...metric, observed_at: options.observationTime === undefined ? at : options.observationTime }];
    else if (path.endsWith("/report")) body = { markdown: "# Synthetic saved report", status: "completed" };
    else if (path === "api/v1/system/overview") body = {
      incidents: { open: 38, resolved: 37 }, incident_sources: { simulator: 25, upload: 50 },
      investigations: { completed: 1 }, actions: { succeeded: 1 }, knowledge: { documents: 19, chunks: 100 },
      runtime: { llm_model: "synthetic-model", embedding_model: "synthetic-embedding", mcp_read_tools: [], mcp_action_tools: [], max_concurrent_investigations: 1, agent_budgets: {} },
    };
    else if (path === "health/dependencies") body = { checks: { test: { ok: true } }, config: {} };
    else if (path === "api/v1/connectors") body = { connectors: [], template_problems: [], planned: [], max_queries: 10 };
    return route.fulfill({ json: body });
  });
}
