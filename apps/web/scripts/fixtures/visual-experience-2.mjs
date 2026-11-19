/** Explicitly synthetic UI fixtures. No model, database or live connector is contacted. */
const time = "2026-11-19T12:04:00Z";
export function fixtureState() {
  return {
    source: "simulator",
    status: "awaiting_approval",
    empty: false,
    unavailable: false,
    loading: false,
    blockedOnly: false,
    decisions: [],
  };
}
export const evidence = [
  {
    evidence_id: "ev-metric-errors",
    kind: "metric_anomaly",
    source_tool: "query_metrics",
    collected_by: "telemetry",
    service: "transaction-api",
    summary:
      "HTTP 5xx ratio rose after onset; the current ratio remains elevated.",
    data: {
      metric: "http_5xx_ratio",
      unit: "ratio",
      baseline: 0.001,
      extreme: 0.42,
      current: 0.38,
      onset: "2026-11-19T12:00:00Z",
      points: 61,
      sources: "metrics.csv:row 2–62",
    },
    citation: null,
    relevance: 0.9,
    observed_at: "2026-11-19T12:00:00Z",
  },
  {
    evidence_id: "ev-metric-latency",
    kind: "metric_anomaly",
    source_tool: "query_metrics",
    collected_by: "telemetry",
    service: "transaction-api",
    summary: "Latency is above the pre-incident baseline.",
    data: {
      metric: "p95_latency_ms",
      unit: "ms",
      baseline: 140,
      extreme: 1600,
      current: 1480,
      points: 61,
    },
    citation: null,
    relevance: 0.8,
    observed_at: "2026-11-19T12:00:20Z",
  },
  {
    evidence_id: "ev-log-schema",
    kind: "log_pattern",
    source_tool: "search_logs",
    collected_by: "telemetry",
    service: "ledger-service",
    summary: "UndefinedColumn errors reference amount_cents in ledger_entries.",
    data: {
      level: "ERROR",
      count: 1480,
      attributes: { source_ref: "ledger.log:line 42" },
      example: "column amount_cents does not exist",
    },
    citation: null,
    relevance: 0.95,
    observed_at: "2026-11-19T12:00:05Z",
  },
  {
    evidence_id: "ev-change-deploy",
    kind: "deployment",
    source_tool: "list_recent_deployments",
    collected_by: "changes",
    service: "ledger-service",
    summary: "A schema migration deployment preceded the first observed error.",
    data: { id: "demo-deploy-42", kind: "schema_migration", correlation: 0.9 },
    citation: null,
    relevance: 0.9,
    observed_at: "2026-11-19T11:59:00Z",
  },
  {
    evidence_id: "ev-dependency",
    kind: "dependency",
    source_tool: "get_service_dependencies",
    collected_by: "dependencies",
    service: "transaction-api",
    summary: "transaction-api depends on ledger-service over synchronous HTTP.",
    data: {
      edge: {
        service: "transaction-api",
        depends_on: "ledger-service",
        kind: "sync_http",
        critical: true,
      },
      health: { status: "unhealthy" },
    },
    citation: null,
    relevance: 0.7,
    observed_at: null,
  },
  {
    evidence_id: "ev-runbook",
    kind: "runbook",
    source_tool: "search_runbooks",
    collected_by: "knowledge",
    service: "ledger-service",
    summary:
      "Current schema migration runbook describes compatibility checks and rollback prerequisites.",
    data: { lifecycle: "current" },
    citation: {
      document_id: "demo-doc",
      chunk_id: "demo-chunk",
      source_uri: "runbooks/schema-migration.md",
      title: "Schema migration response",
      heading_path: "Compatibility checks",
    },
    relevance: 0.8,
    observed_at: null,
  },
];
const hypotheses = [
  {
    rank: 1,
    title: "Schema migration broke ledger compatibility",
    category: "deployment_regression",
    description:
      "The model associates the schema errors and the preceding deployment with the failure. Review the actual migration before authorizing a rollback.",
    confidence: 0.91,
    supporting_evidence_ids: [
      "ev-log-schema",
      "ev-change-deploy",
      "ev-metric-errors",
      "ev-runbook",
    ],
    contradicting_evidence_ids: [],
  },
  {
    rank: 2,
    title: "Database connection pressure",
    category: "resource_exhaustion",
    description:
      "A competing explanation; the recorded schema error contradicts a pool-only diagnosis.",
    confidence: 0.27,
    supporting_evidence_ids: ["ev-metric-latency"],
    contradicting_evidence_ids: ["ev-log-schema"],
  },
];
function incident(state, n = 0) {
  return {
    id: n ? `demo-incident-${n}` : "demo-incident",
    reference: `CASE-20261119-${String(n + 1).padStart(3, "0")}`,
    title:
      n === 1
        ? "Elevated latency on checkout-api"
        : n === 2
          ? "Payment errors from uploaded files"
          : "Elevated HTTP 5xx on transaction-api",
    description: "Synthetic browser fixture for frontend verification.",
    severity: n ? "high" : "critical",
    status:
      state.status === "completed"
        ? "mitigated"
        : state.status === "running"
          ? "investigating"
          : "awaiting_approval",
    service: n === 1 ? "checkout-api" : "transaction-api",
    environment_id: "synthetic-ui-only",
    evidence_source: n === 1 ? "connector" : n === 2 ? "upload" : state.source,
    detected_at: "2026-11-19T12:00:00Z",
    created_at: time,
  };
}
function action(state) {
  const approved = state.status === "completed";
  return {
    id: "demo-action",
    investigation_id: "demo-investigation",
    incident_id: "demo-incident",
    action_type: "rollback_deployment",
    parameters: { service: "ledger-service", deployment_id: "demo-deploy-42" },
    params_hash: "synthetic-parameter-hash",
    rationale:
      "Restore schema compatibility after reviewing the cited errors and deployment.",
    risk: "medium",
    status: approved ? "approved" : "pending",
    requested_at: time,
    decided_at: approved ? time : null,
    decided_by: approved ? "fixture-operator" : null,
    decision_comment: null,
    executed_at: approved ? time : null,
    execution_result: approved ? { ok: true } : null,
    verification: approved
      ? { recovered: true, notes: "Synthetic postconditions passed." }
      : null,
  };
}
function investigation(state) {
  const readOnly = state.source !== "simulator";
  const complete = state.status === "completed";
  return {
    id: "demo-investigation",
    incident_id: "demo-incident",
    status: state.status,
    current_step:
      state.status === "running"
        ? "telemetry"
        : complete
          ? "report"
          : "await_approval",
    model: "local-model:synthetic-fixture",
    started_at: "2026-11-19T12:03:00Z",
    completed_at: complete ? time : null,
    error:
      state.status === "failed"
        ? "Synthetic model-unavailable failure. Evidence remains inspectable."
        : null,
    error_class: state.status === "failed" ? "ModelUnavailable" : null,
    created_at: time,
    updated_at: time,
    result:
      state.status === "running"
        ? {}
        : {
            rca: {
              summary:
                "The investigation associates transaction-api errors with a schema migration in ledger-service. The schema error, deployment record and operational runbook support the leading explanation.",
              hypotheses,
              evidence_gaps: [
                "The deployment diff has not been independently reviewed.",
              ],
              citation_violations: [],
            },
            remediation_plan:
              readOnly || state.blockedOnly
                ? []
                : [
                    {
                      ...action(state),
                      action_id: "demo-action",
                      step: 1,
                      role: "resolution",
                    },
                  ],
            suggested_remediation: readOnly
              ? [
                  {
                    step: 1,
                    action_type: "review_schema_migration",
                    parameters: { service: "ledger-service" },
                    rationale: "Inspect compatibility before making a change.",
                    risk: "medium",
                    role: "resolution",
                  },
                ]
              : [],
            rejected_proposals: [
              {
                proposal: { action_type: "scale_connection_pool" },
                reason:
                  "The proposed expansion exceeds the datastore capacity boundary.",
                category: "unsafe",
              },
            ],
            executions:
              complete && !readOnly && !state.blockedOnly
                ? [
                    {
                      step: 1,
                      status: "succeeded",
                      action_type: "rollback_deployment",
                      message: "Synthetic simulator execution.",
                    },
                  ]
                : [],
            verification:
              complete && !readOnly && !state.blockedOnly
                ? {
                    recovered: true,
                    notes:
                      "Synthetic simulator metrics and health postconditions passed.",
                  }
                : null,
            outcome: complete
              ? {
                  code: readOnly
                    ? "analysis_complete"
                    : state.blockedOnly
                      ? "proposal_blocked"
                      : "mitigated",
                  summary: readOnly
                    ? "Analysis complete. Review the cited findings and suggested next steps."
                    : state.blockedOnly
                      ? "The proposed action was blocked; escalate for review."
                      : "Simulator recovery verified after the approved rollback.",
                  escalate: state.blockedOnly,
                  reason:
                    "Explicitly synthetic browser fixture, not an evaluation result.",
                  actions_executed: !readOnly && !state.blockedOnly ? 1 : 0,
                  steps_planned: !readOnly && !state.blockedOnly ? 1 : 0,
                  read_only: readOnly,
                  suggested_steps: readOnly ? 1 : 0,
                }
              : null,
          },
  };
}
export async function installFixtures(page, state) {
  await page.route("**/api/session", (route) =>
    route.fulfill({
      json: {
        authenticated: true,
        sub: "fixture-operator",
        role: "operator",
        csrf: "synthetic-csrf",
      },
    }),
  );
  await page.route("**/api/ops/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      "/api/ops",
      "",
    );
    if (state.loading) await new Promise((r) => setTimeout(r, 800));
    if (state.unavailable)
      return route.fulfill({
        status: 503,
        json: { detail: "Synthetic backend unavailable" },
      });
    let data;
    if (path.endsWith("/system/overview"))
      data = {
        incidents: { open: 2, investigating: 1, awaiting_approval: 1 },
        investigations: { running: 1 },
        actions: { pending: 1 },
        knowledge: { documents: 23, chunks: 168 },
        runtime: {
          llm_model: "local-model:synthetic-fixture",
          embedding_model: "embedding:synthetic-fixture",
          mcp_read_tools: ["query_metrics", "search_logs"],
          mcp_action_tools: ["rollback_deployment"],
          max_concurrent_investigations: 1,
          agent_budgets: {},
        },
      };
    else if (path.endsWith("/health/dependencies"))
      data = {
        checks: {
          postgresql: { ok: true },
          ollama_llm: { ok: true },
          mcp_read: { ok: true },
          mcp_actions: { ok: true },
        },
        config: {},
      };
    else if (path.endsWith("/scenarios"))
      data = [{ key: "INC-001", title: "Incompatible schema migration" }];
    else if (path === "/api/v1/incidents")
      data = state.empty
        ? []
        : [incident(state), incident(state, 1), incident(state, 2)];
    else if (path === "/api/v1/incidents/simulate") data = incident(state);
    else if (path.endsWith("/incidents/demo-incident/investigations"))
      data = [investigation(state)];
    else if (path.endsWith("/incidents/demo-incident")) data = incident(state);
    else if (path.endsWith("/events"))
      data = [
        "intake",
        "plan",
        "telemetry",
        "changes",
        "knowledge",
        "rca",
        "await_approval",
      ].map((node, i) => ({
        id: i + 1,
        event_type:
          node === "await_approval" ? "approval_requested" : "node_completed",
        node,
        created_at: `2026-11-19T12:03:${String(i * 8).padStart(2, "0")}Z`,
        payload:
          node === "telemetry"
            ? {
                evidence_ids: ["ev-metric-errors", "ev-log-schema"],
                observations: [
                  {
                    agent: "telemetry",
                    finding:
                      "Schema errors coincide with an elevated HTTP 5xx ratio.",
                  },
                ],
              }
            : {},
      }));
    else if (path.endsWith("/evidence")) data = state.empty ? [] : evidence;
    else if (path.endsWith("/actions"))
      data =
        state.source === "simulator" &&
        !state.blockedOnly &&
        state.status !== "running"
          ? [action(state)]
          : [];
    else if (path.endsWith("/tool-calls"))
      data = evidence
        .slice(0, 4)
        .map((e, i) => ({
          id: `tool-${i}`,
          tool: e.source_tool,
          server: "mcp-read",
          agent: e.collected_by,
          arguments: {},
          status: "ok",
          latency_ms: 15 + i,
          result_summary: e.summary,
          error: null,
          started_at: time,
        }));
    else if (path.endsWith("/report"))
      data = {
        status: "completed",
        markdown:
          "# Synthetic incident report\n\n## Ranked hypotheses\n\nSchema migration broke compatibility [ev-log-schema].\n\nModel-estimated confidence values are not calibrated probabilities.\n\nSuggested remediation (not executed) applies only to read-only sources.",
      };
    else if (path.endsWith("/investigations/demo-investigation"))
      data = investigation(state);
    else if (path.includes("/approvals/demo-action/decision")) {
      const body = route.request().postDataJSON();
      state.decisions.push(body);
      state.status = "completed";
      data = action(state);
    } else if (path.endsWith("/approvals"))
      data =
        state.source === "simulator" && !state.blockedOnly
          ? [action(state)]
          : [];
    else if (path === "/api/v1/connectors")
      data = {
        connectors: [
          {
            id: "loki",
            kind: "loki",
            name: "Grafana Loki",
            signal: "log",
            configured: true,
            endpoint: "http://127.0.0.1:3310",
            auth: "bearer",
            service_label: "service_name",
            templates: [{ id: "errors", label: "Errors and warnings" }],
          },
          {
            id: "prometheus",
            kind: "prometheus",
            name: "Prometheus",
            signal: "metric",
            configured: false,
            hint: "configure PROMETHEUS_URL",
          },
        ],
        template_problems: [],
        planned: ["Datadog", "Azure Monitor", "AWS CloudWatch"],
        max_queries: 12,
      };
    else if (path.endsWith("/connectors/loki/test"))
      data = {
        connector: "loki",
        status: "ok",
        message: "Synthetic Loki answered.",
        checked_at: time,
        version: "synthetic",
      };
    else
      return route.fulfill({
        status: 404,
        json: { detail: `No synthetic fixture for ${path}` },
      });
    return route.fulfill({ json: data });
  });
}
