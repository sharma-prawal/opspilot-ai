import type { Page } from "@playwright/test";
import type { Evidence, Hypothesis, QueryProvenance, UploadedDataset } from "../lib/types";
import { fixture, incidentId, investigationId, metric } from "../e2e-pass-a/fixtures";

export { investigationId };
export const at = "2026-11-20T12:00:00Z";
export const evidence: Evidence[] = [
  { ...metric, data: { ...metric.data, sources: "cloudwatch/errors/checkout-api:point 4" } },
  { evidence_id: "ev-config", kind: "log_pattern", service: "checkout-api", source_tool: "search_logs", collected_by: "telemetry",
    summary: "Configuration loaded with db.pool.max_size=8 (previous 40)", relevance: 0.75, observed_at: "2026-11-20T11:55:00Z", citation: null,
    data: { first_seen: "2026-11-20T11:55:00Z", last_seen: "2026-11-20T11:55:00Z", sample: "configuration loaded: db.pool.max_size=8 (previous 40)",
      change_observation: true, count: 1, level: "INFO", attributes: { source_ref: "cloudwatch/lifecycle/checkout-api:entry 3" } } },
  { evidence_id: "ev-traffic", kind: "log_pattern", service: "checkout-api", source_tool: "search_logs", collected_by: "telemetry",
    summary: "No increase in incoming request volume in the collected sample", relevance: 0.7, observed_at: at, citation: null,
    data: { message: "request rate remained within baseline", attributes: { source_ref: "uploaded/traffic.jsonl:line 22" } } },
];
export const hypotheses: Hypothesis[] = [
  { rank: 1, title: "Connection pool limit may explain checkout timeouts", category: "configuration_error", confidence: 0.87,
    description: "The recorded pool-size reduction coincides with elevated errors. This association does not independently establish the cause.",
    supporting_evidence_ids: ["ev-config", "ev-historical", "ev-missing"], contradicting_evidence_ids: ["ev-traffic"],
    evidence_warnings: ["A configuration observation is not complete deployment history. Causality remains unverified."] },
  { rank: 2, title: "A traffic increase may have exhausted the pool", category: "resource_exhaustion", confidence: 0.4,
    description: "A competing model explanation; the sampled traffic record contradicts a load increase.",
    supporting_evidence_ids: ["ev-historical"], contradicting_evidence_ids: ["ev-traffic"], evidence_warnings: [] },
];
const query: QueryProvenance = {
  id: "azure-errors", connector: "azure_monitor", connector_name: "Azure Monitor", endpoint: "fixture", template: "errors",
  template_label: "Error logs", service: "checkout-api", query: "AppTraces | where SeverityLevel >= 3", start: "2026-11-20T11:30:00Z",
  end: at, step_seconds: null, limit: 100, status: "empty", error: null, returned: 0, rejected: 0, redactions: 0,
  truncated: false, series: null, unit: "", fetched_at: "2026-11-20T12:01:00Z", duration_ms: 30, issues: [],
};
export const dataset: UploadedDataset = {
  dataset_id: "synthetic-snapshot", incident_id: incidentId, timezone: "UTC", affected_services: ["checkout-api"], files: [],
  queries: [query, { ...query, id: "cw-unmapped", connector: "cloudwatch", connector_name: "AWS CloudWatch", status: "error",
    error: { kind: "not_configured", message: "No mapped resource" }, aws: { not_queried: true } },
    { ...query, id: "partial-logs", connector: "datadog", connector_name: "Datadog", status: "ok", returned: 3, truncated: true, issues: ["Sampling coverage is limited; correlation is incomplete."] },
    { ...query, id: "denied-logs", connector: "loki", connector_name: "Loki", status: "error", error: { kind: "permission_denied", message: "Source unavailable" } },
    { ...query, id: "cw-collected", connector: "cloudwatch", connector_name: "AWS CloudWatch", status: "ok", returned: 3 },
    { ...query, id: "prom-empty", connector: "prometheus", connector_name: "Prometheus", status: "empty" }],
  created_at: "2026-11-20T12:01:00Z", retention_days: 30,
  summary: { records: { log: 3, metric: 1, span: 0, event: 0 }, rejected: 0, redactions: 0, services: ["checkout-api"],
    metrics_by_service: { "checkout-api": ["http_5xx_ratio"] }, event_types: [], start: query.start, end: at, timezones: ["UTC"],
    window: { start: query.start, end: at }, samples: { log: [], metric: [], span: [], event: [] },
    warnings: ["Deployment/change history was not collected. Missing sources stay unknown."] },
};
export async function workbenchFixture(page: Page, source: "simulator" | "upload" | "connector" = "connector", pending = false) {
  await fixture(page, { source, authorization: pending ? "pending" : "approve" });
  await page.route(`**/api/ops/api/v1/investigations/${investigationId}`, route => route.fulfill({ json: {
    id: investigationId, incident_id: incidentId, status: pending ? "awaiting_approval" : "completed", current_step: "report", model: "synthetic-model",
    started_at: at, created_at: at, updated_at: at, completed_at: pending ? null : "2026-11-20T12:03:00Z", error: null,
    result: { window: { start: dataset.summary.start, end: at },
      rca: { summary: "Model claims the configuration change caused the errors; this remains an unverified hypothesis.", hypotheses,
        evidence_warnings: ["Unsupported causal assertion: an observed change is not a verified cause."],
        evidence_gaps: ["Deployment/change history is unknown", "No complete trace correlation"],
        impact: { state: "ongoing", reasons: ["Elevated 5xx ratio observed at the end of the evidence window"] } },
      suggested_remediation: source === "simulator" ? [] : [{ step: 1, action_type: "restart_service", parameters: { service: "checkout-api" },
        rationale: "Model suggestion only", risk: "medium", role: "recovery", limitations: ["Restarting may reload the same persisted configuration."] }],
      remediation_plan: source === "simulator" ? [{ step: 1, role: "recovery", action_type: "restart_service", parameters: { service: "checkout-api" }, rationale: "Synthetic only", risk: "low" }] : [],
      executions: source === "simulator" && !pending ? [{ step: 1, status: "succeeded", message: "Synthetic execution", action_type: "restart_service" }] : [],
      verification: source === "simulator" && !pending ? { recovered: true, notes: "Synthetic sandbox verification; historical evidence is separate" } : null,
    },
  } }));
  await page.route(`**/api/ops/api/v1/investigations/${investigationId}/evidence`, route => route.fulfill({ json: evidence }));
  await page.route(`**/api/ops/api/v1/incidents/${incidentId}/dataset`, route => route.fulfill({ json: { ...dataset, queries: source === "upload" ? [] : dataset.queries } }));
}
