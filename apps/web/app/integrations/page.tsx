"use client";

import Link from "next/link";
import { useState } from "react";
import { fillModels, useActiveModels } from "@/lib/models";
import { IntegrationMatrix } from "@/components/integration-matrix";
import { ConnectorsPanel } from "@/components/connectors-panel";
import { Badge, Button, Card, CodeBlock, PageHeader } from "@/components/ui";

type UsageMode = "all" | "demo" | "offline" | "connected";
type Category =
  | "all"
  | "metrics"
  | "logs"
  | "traces"
  | "changes"
  | "dependencies"
  | "knowledge"
  | "alerting";

type Status = "implemented" | "requires_adapter" | "planned";

interface IntegrationItem {
  id: string;
  name: string;
  category: Category;
  mode: "demo" | "offline" | "connected";
  status: Status;
  tagline: string;
  evidenceContributed: string[];
  prerequisites: string[];
  configuration: string;
  exampleQuery: {
    language: string;
    code: string;
  };
  normalization: string;
  troubleshooting: string[];
  targetNode: string;
}

const INTEGRATIONS: IntegrationItem[] = [
  // Demo Mode
  {
    id: "demo-simulator",
    name: "Synthetic Incident Simulator",
    category: "metrics",
    mode: "demo",
    status: "implemented",
    tagline:
      "Deterministic fault generation across 6 published production-like scenarios.",
    evidenceContributed: [
      "Time-series metrics (HTTP 5xx ratios, p95 latency, queue depths, pool utilization)",
      "Structured application error logs and exception stack traces",
      "Git deployment commits, author signatures, and configuration changes",
      "Dependency topology graphs and datastore connection saturation",
    ],
    prerequisites: [
      "PostgreSQL 17 + pgvector container running on port 5433",
      "Local Ollama running the configured {LLM_MODEL} and {EMBEDDING_MODEL}",
      "Database migrations applied to head (0011)",
    ],
    configuration:
      "Built-in: POST /api/v1/incidents/simulate with scenario key (INC-001..003, NEG-001..003) or CLI uv run opspilot simulate.",
    exampleQuery: {
      language: "python",
      code: `# Invoked by MCP read server during investigation:
query_metrics(service="transaction-api", metric="http_requests_5xx_ratio", window="2026-11-03T13:45Z/14:15Z")
search_logs(service="transaction-api", limit=50)
list_recent_deployments(service="ledger-service")`,
    },
    normalization:
      "Persisted directly to ops.evidence with kind: telemetry, deployment, or config. Evaluates bidirectional excursion against baseline mean; computes temporal correlation score Δt against onset timestamp.",
    troubleshooting: [
      "Run make doctor to ensure sim schema and seed data are initialized.",
      "Verify container health with docker inspect -f '{{.State.Health.Status}}' opspilot-postgres.",
    ],
    targetNode: "Telemetry & Changes Agents",
  },

  // Offline / File Mode
  {
    id: "offline-runbooks",
    name: "Markdown & JSON Runbook Corpus",
    category: "knowledge",
    mode: "offline",
    status: "implemented",
    tagline:
      "Operational knowledge base ingested via pgvector hybrid reciprocal rank fusion.",
    evidenceContributed: [
      "Standard Operating Procedures (SOPs) and disaster recovery runbooks",
      "Historical postmortem documents and previous root-cause analyses",
      "Service architecture constraints and database capacity guidelines",
    ],
    prerequisites: [
      "Local Markdown (.md) or JSON (.json) documents in docs/ or knowledge/ directory",
      "YAML front-matter with title, doc_type (runbook, postmortem), services, and lifecycle_status",
    ],
    configuration:
      "Run uv run opspilot ingest (or make bootstrap). Incremental ingestion automatically hashes content via SHA-256 and skips unchanged files.",
    exampleQuery: {
      language: "markdown",
      code: `---
title: Schema Migration Rollback Procedure
doc_type: runbook
services: [ledger-service, transaction-api]
lifecycle_status: current
tags: [database, migration, postgres]
---
# Schema Migration Rollback
## Symptoms
UndefinedColumn errors on transaction-api following deployment.
## Verification
Confirm 5xx error ratio returns below baseline 0.1%.`,
    },
    normalization:
      "Chunked using heading-aware boundaries (220 words / 40 word overlap). Embedded via the configured local {EMBEDDING_MODEL}. Stored in kb.documents and kb.chunks with composite foreign key guards preventing revision drift.",
    troubleshooting: [
      "Re-index the corpus with uv run opspilot ingest --reindex.",
      "Verify chunk count on the /knowledge dashboard page.",
    ],
    targetNode: "Knowledge Agent (Hybrid RAG)",
  },
  {
    id: "offline-telemetry-dumps",
    name: "Uploaded Log, Metric & Event Files",
    category: "metrics",
    mode: "offline",
    status: "implemented",
    tagline:
      "Read-only analysis of your own sanitized .log/.txt, .json and .csv exports (v0.5, Analyze files page).",
    evidenceContributed: [
      "Application logs: timestamped text lines, JSON lines or JSON arrays (level, message, key=value attributes)",
      "Metric samples: CSV (one column per metric, or metric/value rows) and JSON objects with a metric name and value",
      "Change events: deployments, rollbacks, schema migrations, config changes and alerts (JSON or CSV)",
    ],
    prerequisites: [
      "Up to 5 files per incident, 5 MB each, 8 MB total, 50,000 records",
      "A timestamp on every record (ISO-8601 with or without offset, epoch, or web-server log format)",
      "A service per record, or a service declared for the file in the upload form",
    ],
    configuration:
      "Web: Analyze files (/incidents/new) → preview → create & analyze. API: POST /api/v1/incidents/upload/preview and /api/v1/incidents/upload (operator). Files are stored under UPLOAD_DIR; make uploads-purge removes old uploads.",
    exampleQuery: {
      language: "csv",
      code: `timestamp,service,http_5xx_ratio,p95_latency_ms,http_requests_per_min
2026-11-12T09:14:00.000Z,checkout-api,0.0035,182,431
2026-11-12T09:15:00.000Z,checkout-api,0.0491,654,409
# Each cell becomes a MetricRecord with source "service-metrics.csv:row N"`,
    },
    normalization:
      "Parsed by opspilot_shared.uploads into LogRecord / MetricRecord / EventRecord with source file:line, original timestamp and timezone, and service provenance. The file-backed evidence provider (server opspilot-uploaded-evidence) answers search_logs, query_metrics, list_recent_deployments and get_config_changes from them; live health, config, datastore and queue tools report 'not available'. Nothing is invented: rows without a timestamp or service are rejected and listed in the preview.",
    troubleshooting: [
      "Check the preview: rejected rows and their reasons are listed per file.",
      "Timestamps without an offset are read in the timezone chosen on the form and shown as 'assumed <zone>'.",
      "If the analysis finds nothing, the incident time may be outside the data: the window is 3 h before to 30 min after it.",
    ],
    targetNode: "Telemetry & Changes Agents (file-backed provider)",
  },
  {
    id: "offline-traces",
    name: "Uploaded Trace Exports (OTLP/JSON)",
    category: "traces",
    mode: "offline",
    status: "implemented",
    tagline:
      "Failing spans and observed service-to-service calls from OTLP/JSON or simple span JSON (v0.5).",
    evidenceContributed: [
      "Error spans as log-like evidence, naming the downstream service where the failure surfaced",
      "Observed caller → callee edges between services",
    ],
    prerequisites: [
      "OTLP/JSON (resourceSpans) or objects with trace_id, span_id, start time and duration or end time",
    ],
    configuration:
      "Upload the trace export with the other files on the Analyze files page; spans are normalized with their trace, span and parent IDs.",
    exampleQuery: {
      language: "json",
      code: `// OTLP/JSON span (inside resourceSpans[].scopeSpans[].spans[]):
{
  "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
  "spanId": "00f067aa0ba902b7",
  "name": "POST /v1/charges",
  "kind": 2,
  "startTimeUnixNano": "1794474900000000000",
  "endTimeUnixNano": "1794474902040000000",
  "status": {"code": 2, "message": "connection pool exhausted"}
}`,
    },
    normalization:
      "Error spans are served through search_logs with attributes upstream=<failing downstream service>, span_id and source_ref; get_service_dependencies returns edges observed in the traces (kind observed_call).",
    troubleshooting: [
      "Upload the spans of every service in the trace so parent/child links across services can be resolved.",
    ],
    targetNode: "Telemetry & Dependencies Agents (file-backed provider)",
  },

  // Connected Mode
  {
    id: "prometheus-connector",
    name: "Prometheus",
    category: "metrics",
    mode: "connected",
    status: "implemented",
    tagline:
      "Read-only PromQL range queries from approved templates over the official HTTP API (v0.6).",
    evidenceContributed: [
      "Error ratio, p95 latency and request rate per service (built-in templates for http_requests_total / http_request_duration_seconds)",
      "Any gauge or rate an operator adds as a template (e.g. database pool in use)",
      "Every point keeps its Unix timestamp, unit, series labels and the query that returned it",
    ],
    prerequisites: [
      "Prometheus HTTP API reachable from the OpsPilot API (tested only with a local prom/prometheus:v3.5.0; remote, cloud and Mimir/Thanos endpoints not verified)",
      "Read-only access; a bearer token or basic auth if the API is protected (https unless loopback)",
      "A service label on your series (PROMETHEUS_SERVICE_LABEL, default service)",
    ],
    configuration:
      "Apply migration 0011 (make migrate). Set PROMETHEUS_URL (and optionally PROMETHEUS_BEARER_TOKEN or PROMETHEUS_USERNAME/PROMETHEUS_PASSWORD, PROMETHEUS_SERVICE_LABEL, TELEMETRY_TEMPLATES_FILE) in the API environment and restart it. Then Incidents → Connected telemetry. Local test setup with synthetic data: make telemetry-up (stop with make telemetry-down).",
    exampleQuery: {
      language: "promql",
      code: `# Built-in template http_5xx_ratio, rendered for one service ($selector, $rate):
sum(rate(http_requests_total{service="checkout-api",status=~"5.."}[5m]))
  / sum(rate(http_requests_total{service="checkout-api"}[5m]))
# GET /api/v1/query_range?query=...&start=<unix s>&end=<unix s>&step=45`,
    },
    normalization:
      "Each matrix point becomes a MetricRecord (metric name and unit from the template, ts_original as returned, labels kept) with source prometheus/<template>/<service>:point N. NaN/Inf points are skipped and counted, never filled in. The snapshot is stored with the incident and served by opspilot-connected-telemetry.",
    troubleshooting: [
      "Use Test connection on this page: it distinguishes authentication errors, unavailable backends and wrong URLs (404).",
      "A template that returns no data stays 'no data' in the preview: your metric names may differ; add a template in TELEMETRY_TEMPLATES_FILE.",
      "Redirects are refused: point PROMETHEUS_URL at the API itself (not a login page or a UI path).",
    ],
    targetNode: "Telemetry Agent (connected-telemetry snapshot)",
  },
  {
    id: "loki-connector",
    name: "Grafana Loki",
    category: "logs",
    mode: "connected",
    status: "implemented",
    tagline:
      "Read-only LogQL log queries from approved templates over the official HTTP API (v0.6).",
    evidenceContributed: [
      "Error, warning and exception lines of each service in the window",
      "Start-up, shutdown, version and configuration lines (to spot changes)",
      "Every line keeps its nanosecond timestamp, stream labels, level and key=value attributes",
    ],
    prerequisites: [
      "Loki query API reachable from the OpsPilot API (tested only with a local grafana/loki:3.5.0; Grafana Cloud and remote endpoints not verified)",
      "LOKI_TENANT_ID (X-Scope-OrgID) for a multi-tenant Loki; read-only credentials if protected",
      "A service label on your streams (LOKI_SERVICE_LABEL, default service_name)",
    ],
    configuration:
      "Apply migration 0011 (make migrate). Set LOKI_URL (and optionally LOKI_TENANT_ID, LOKI_BEARER_TOKEN or LOKI_USERNAME/LOKI_PASSWORD, LOKI_SERVICE_LABEL) in the API environment and restart it. Lines per query: TELEMETRY_MAX_LOG_LINES (default 2000). Local test setup: make telemetry-up / make telemetry-down.",
    exampleQuery: {
      language: "text",
      code: `// Built-in template errors_warnings, rendered for one service:
{service_name="payment-service"} |~ "(?i)(error|warn|exception|fail|timeout|refused|unavailable|panic|fatal)"
// GET /loki/api/v1/query_range?query=...&start=<ns>&end=<ns>&limit=2000&direction=backward`,
    },
    normalization:
      "Each line becomes a LogRecord (level from the line or stream labels, else inferred and flagged; credential-like values redacted) with source loki/<template>/<service>:entry N. When the line limit is reached the query is marked truncated.",
    troubleshooting: [
      "'no org id' (401) means the Loki is multi-tenant: set LOKI_TENANT_ID.",
      "Use 'Find services in this window' on the incident form to see the values of the service label.",
    ],
    targetNode: "Telemetry Agent (connected-telemetry snapshot)",
  },
  {
    id: "datadog-adapter",
    name: "Datadog",
    category: "metrics",
    mode: "connected",
    status: "implemented",
    tagline:
      "Read-only logs, metrics and APM spans from approved templates over the official Datadog API (v0.9).",
    evidenceContributed: [
      "Error/warning and lifecycle logs per service (Log Management search, cursor-paginated with hard limits)",
      "APM trace metrics: 5xx ratio, trace error ratio, p95 latency and request rate (metrics timeseries query); every returned point, nulls left out",
      "Indexed APM error spans plus the other indexed spans of up to 10 of their traces: real parent/child links and dependencies, flagged partial when a parent was not indexed",
    ],
    prerequisites: [
      "A Datadog API key and an application key scoped to logs_read_data, timeseries_query and apm_read",
      "DATADOG_SITE set to one of the documented sites (datadoghq.com, us3/us5.datadoghq.com, datadoghq.eu, ap1/ap2/uk1.datadoghq.com, ddog-gov.com, us2.ddog-gov.com)",
      "Services tagged with service: (unified service tagging); names must be lower-case slugs to be queried",
    ],
    configuration:
      "Set DATADOG_ENABLED=true, DATADOG_SITE, DATADOG_API_KEY and DATADOG_APP_KEY in the API environment (backend only; never NEXT_PUBLIC_*), optionally DATADOG_ENV and DATADOG_LOG_INDEXES, and restart the API. Requests go only to https://api.<site>. Without an account, make datadog-fixture serves synthetic Datadog responses on 127.0.0.1 (DATADOG_LOCAL_API_URL, loopback only). Verified only against that synthetic fixture so far, not a live organization.",
    exampleQuery: {
      language: "bash",
      code: `# Built-in template http_5xx_ratio, rendered for one service:
a = sum:trace.http.request.hits.by_http_status{service:orders-api,http.status_class:5xx}.as_count()
b = sum:trace.http.request.hits{service:orders-api}.as_count()
formula: a / b
# POST /api/v2/query/timeseries  {"data": {"type": "timeseries_request", ...}}
# Logs: POST /api/v2/logs/events/search  ·  Spans: POST /api/v2/spans/events/search`,
    },
    normalization:
      "Logs become LogRecords (status → level, dd.trace_id kept, credential-like values redacted, source datadog/<template>/<service>:entry N); metric points become MetricRecords with the template's unit (null intervals skipped and counted); spans become SpanRecords with trace, span and parent IDs, duration, and status error only when Datadog flags it (otherwise unset). Change history is not collected (Datadog events are not queried) and stays unknown.",
    troubleshooting: [
      "Test connection validates the API key (GET /api/v1/validate), then probes logs, metrics and spans: 'permission missing' names the permission the application key needs.",
      "HTTP 429: OpsPilot retries at most twice when Datadog's X-RateLimit-Reset is 10 s or less, otherwise reports rate_limited. Span search allows 50 requests per minute per organization.",
      "APM metrics are named after the span of your integration (trace.flask.request, trace.express.request, …): override the templates in TELEMETRY_TEMPLATES_FILE.",
    ],
    targetNode: "Telemetry & Dependencies Agents (connected-telemetry snapshot)",
  },
  {
    id: "aws-cloudwatch",
    name: "AWS CloudWatch & Container Insights",
    category: "metrics",
    mode: "connected",
    status: "planned",
    tagline:
      "CloudWatch Metrics, Log Insights, and ECS/EKS Container telemetry.",
    evidenceContributed: [
      "ALB 5xx counts, RDS CPU/connection saturation, ECS task stop reasons",
      "CloudWatch Logs Insights query aggregations",
    ],
    prerequisites: [
      "AWS IAM Read-Only credentials (cloudwatch:GetMetricData, logs:StartQuery, logs:GetQueryResults)",
      "Configured AWS region (e.g. eu-west-1)",
    ],
    configuration:
      "Planned — not implemented. An adapter would implement the TelemetryConnector contract (docs/integrations/CONNECTORS.md): approved templates in, normalized records with provenance out, read-only. The example below is illustrative.",
    exampleQuery: {
      language: "sql",
      code: `// CloudWatch Logs Insights query:
fields @timestamp, @message, @logStream
| filter @message like /Exception|Error/
| stats count() as errorCount by bin(1m)
| sort errorCount desc`,
    },
    normalization:
      "CloudWatch metric data points converted into unit-standardized floats. Log Insight query results mapped into Evidence(kind='telemetry').",
    troubleshooting: [
      "Ensure CloudWatch Logs Insights queries use bounded time ranges to avoid AWS query quotas.",
    ],
    targetNode: "Telemetry & Dependencies Agents",
  },
  {
    id: "azure-monitor",
    name: "Azure Monitor & Application Insights",
    category: "metrics",
    mode: "connected",
    status: "planned",
    tagline:
      "App Insights telemetry, Kusto (KQL) queries, and Azure Resource health.",
    evidenceContributed: [
      "Application Insights exception telemetry and failed dependency calls",
      "Kusto KQL query results on Log Analytics workspaces",
      "Azure Resource Manager (ARM) health status",
    ],
    prerequisites: [
      "Azure Service Principal with 'Monitoring Reader' role",
      "AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID, and Workspace ID",
    ],
    configuration:
      "Planned — not implemented. An adapter would implement the TelemetryConnector contract (docs/integrations/CONNECTORS.md): approved templates in, normalized records with provenance out, read-only. The example below is illustrative.",
    exampleQuery: {
      language: "text",
      code: `// Kusto KQL query:
exceptions
| where timestamp between(datetime("2026-11-03T13:45Z") .. datetime("2026-11-03T14:15Z"))
| where cloud_RoleName == "transaction-api"
| summarize count() by type, outerMessage, bin(timestamp, 1m)`,
    },
    normalization:
      "KQL tabular output normalized into ops.evidence items with exception categorization.",
    troubleshooting: [
      "Verify Service Principal role assignment in Azure Portal under Access Control (IAM).",
    ],
    targetNode: "Telemetry & Dependencies Agents",
  },
  {
    id: "tempo-jaeger-tracing",
    name: "Tempo, Jaeger & OpenTelemetry Collector",
    category: "traces",
    mode: "connected",
    status: "planned",
    tagline:
      "Live distributed tracing and causal call-chain dependency inspection.",
    evidenceContributed: [
      "End-to-end distributed trace spans across microservices",
      "Upstream vs downstream latency propagation and error roots",
    ],
    prerequisites: [
      "Grafana Tempo or Jaeger gRPC / HTTP query endpoint (e.g. http://tempo:3200)",
      "Standard W3C TraceContext propagation across instrumented services",
    ],
    configuration:
      "Planned — not implemented. An adapter would implement the TelemetryConnector contract (docs/integrations/CONNECTORS.md): approved templates in, normalized records with provenance out, read-only. The example below is illustrative.",
    exampleQuery: {
      language: "text",
      code: `// TraceQL query executed against Tempo:
{ .service.name = "transaction-api" && .status.code = error }`,
    },
    normalization:
      "Trace call graph analysis feeds the Causal Consistency Safety Gate: verifies whether service X is failing due to downstream dependency Y, preventing mistaken rollbacks of healthy services.",
    troubleshooting: [
      "Verify trace ID format (128-bit hex). Test query endpoint with curl http://tempo:3200/status.",
    ],
    targetNode: "Dependencies Agent & Causal Consistency Gate",
  },
  {
    id: "github-actions-deployments",
    name: "GitHub Actions & Deployment Changelogs",
    category: "changes",
    mode: "connected",
    status: "planned",
    tagline: "Live CI/CD release tracking and git commit correlation.",
    evidenceContributed: [
      "Deployment timestamps, release tags, and environment target names",
      "Git commit SHA, author, pull request title, and modified file paths",
    ],
    prerequisites: [
      "GitHub Personal Access Token or App Token with repo:status and actions:read scopes",
      "Repository name (owner/repo)",
    ],
    configuration:
      "Planned — not implemented. An adapter would implement the TelemetryConnector contract (docs/integrations/CONNECTORS.md): approved templates in, normalized records with provenance out, read-only. The example below is illustrative.",
    exampleQuery: {
      language: "bash",
      code: `# Executed against GitHub REST API:
GET /repos/sharma-prawal/opspilot-ai/deployments?environment=production
GET /repos/sharma-prawal/opspilot-ai/commits/23c7ef2`,
    },
    normalization:
      "Each deployment is converted to Evidence(kind='deployment'). OpsPilot calculates the temporal correlation score between commit timestamp and incident onset.",
    troubleshooting: [
      "Verify GitHub token rate limits with curl -H 'Authorization: Bearer $GITHUB_TOKEN' https://api.github.com/rate_limit.",
    ],
    targetNode: "Change Agent & Correlation Safety Gate",
  },
  {
    id: "custom-adapter",
    name: "Custom telemetry adapter",
    category: "logs",
    mode: "connected",
    status: "planned",
    tagline:
      "Your own log or metric store behind the same read-only connector contract.",
    evidenceContributed: [
      "LogRecord / MetricRecord / SpanRecord evidence with provenance, like the Loki, Prometheus and Datadog connectors",
    ],
    prerequisites: [
      "A read-only HTTP API (or SDK) for the store",
      "A way to scope a query to one service and time window",
    ],
    configuration:
      "Planned — not implemented. Implement TelemetryConnector (opspilot_shared/connectors/contract.py) and register it in connectors/registry.py; see docs/integrations/CONNECTORS.md.",
    exampleQuery: {
      language: "python",
      code: `class MyConnector(HttpConnector):  # opspilot_shared/connectors/base.py
    KIND, SIGNAL, NAME = "mystore", "log", "My store"
    def allowed_paths(self): return ["/api/search"]
    async def fetch(self, template, service, window): ...  # -> FetchResult(records + provenance)`,
    },
    normalization:
      "Must return normalized records with source <connector>/<template>/<service>:entry|point N and a QueryProvenance per query; failures as typed ConnectorError kinds, never raised to the graph.",
    troubleshooting: [
      "Keep GET-only, allowlisted paths and no redirects (ReadOnlyHttp does this for you).",
    ],
    targetNode: "Telemetry Agent (connected-telemetry snapshot)",
  },
  {
    id: "alertmanager-pagerduty",
    name: "PagerDuty, Opsgenie & Alertmanager Webhooks",
    category: "alerting",
    mode: "connected",
    status: "planned",
    tagline:
      "Automated investigation trigger on inbound incident paging webhooks.",
    evidenceContributed: [
      "Incident title, firing alert name, severity, and initial alerting service",
      "Raw alert payload labels and annotations",
    ],
    prerequisites: [
      "Configured webhook endpoint URL in PagerDuty / Alertmanager",
      "Webhook secret token for HMAC-SHA256 signature verification",
    ],
    configuration:
      "Future planned route: POST /api/v1/incidents/webhook. Verifies signature, extracts service and onset timestamp, and starts background investigation automatically.",
    exampleQuery: {
      language: "json",
      code: `// Sample PagerDuty webhook event:
{
  "event": {
    "id": "01BZ82Z",
    "event_type": "incident.triggered",
    "data": {
      "title": "High 5xx rate on transaction-api",
      "service": {"summary": "transaction-api"},
      "urgency": "high"
    }
  }
}`,
    },
    normalization:
      "Creates an ops.incidents record and immediately spawns a LangGraph thread, notifying on-call via web UI or Slack webhook.",
    troubleshooting: [
      "Ensure webhook receiver verifies HMAC headers to prevent unauthorized incident creation.",
    ],
    targetNode: "Intake Node",
  },
];

export default function IntegrationsPage() {
  const models = useActiveModels();
  const [selectedMode, setSelectedMode] = useState<UsageMode>("all");
  const [selectedCategory, setSelectedCategory] = useState<Category>("all");
  const [selectedItemId, setSelectedItemId] = useState<string>(
    INTEGRATIONS[0].id,
  );

  const filtered = INTEGRATIONS.filter((item) => {
    if (selectedMode !== "all" && item.mode !== selectedMode) return false;
    if (selectedCategory !== "all" && item.category !== selectedCategory)
      return false;
    return true;
  });

  // Always derive activeItem from filtered list; never show an item excluded by the active filter
  const activeItem =
    filtered.find((i) => i.id === selectedItemId) ?? filtered[0] ?? null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data Sources & Integrations"
        subtitle="Choose a source. Check its capabilities. Inspect its configuration."
        actions={
          <div className="flex items-center gap-2">
            <Link href="/architecture">
              <Button variant="secondary" size="md">
                Interactive Architecture →
              </Button>
            </Link>
            <Link href="/guide">
              <Button variant="primary" size="md">
                Developer Guide
              </Button>
            </Link>
          </div>
        }
      />

      <ConnectorsPanel />
      <section
        aria-labelledby="planned-adapters-title"
        className="planned-adapters"
      >
        <h2
          id="planned-adapters-title"
          className="font-serif-heading text-lg font-bold"
        >
          Planned adapters
        </h2>
        <p className="mt-1 mb-3 text-xs text-muted">
          Not implemented. These providers cannot collect evidence yet.
        </p>
        <ul className="planned-provider-list">
          {INTEGRATIONS.filter((item) =>
            ["azure-monitor", "aws-cloudwatch"].includes(item.id),
          ).map((item) => (
            <li key={item.id}>
              <span>{item.name}</span>
              <Badge>Planned</Badge>
            </li>
          ))}
        </ul>
        <details className="compact-disclosure mt-3">
          <summary>Other planned adapters</summary>
          <ul className="planned-provider-list mt-2">
            {INTEGRATIONS.filter(
              (item) =>
                item.status === "planned" &&
                !["datadog-adapter", "azure-monitor", "aws-cloudwatch"].includes(
                  item.id,
                ),
            ).map((item) => (
              <li key={item.id}>
                <span>{item.name}</span>
                <Badge>Planned</Badge>
              </li>
            ))}
          </ul>
        </details>
      </section>
      <details className="compact-disclosure secondary-catalog">
        <summary>Compare source capabilities</summary>
        <div className="mt-4">
          <IntegrationMatrix />
        </div>
      </details>
      <details className="compact-disclosure">
        <summary>How sources become investigation evidence</summary>
        <div className="rounded-2xl border border-border bg-gradient-to-br from-panel via-panel to-panel-2 p-6 shadow-sm">
          <div className="max-w-3xl space-y-3">
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-accent-soft px-2.5 py-0.5 text-xs font-bold text-accent">
                Platform Independence
              </span>
              <span className="text-xs text-muted">
                Model Context Protocol (MCP) · Pluggable Seams
              </span>
            </div>
            <h2 className="text-lg font-bold text-text sm:text-xl">
              Decoupled Evidence Gathering Across Three Usage Modes
            </h2>
            <p className="text-xs text-muted leading-relaxed">
              OpsPilot AI is not coupled to any single observability provider or
              logging tool. The agent core interacts exclusively with typed port
              interfaces (
              <code className="font-mono text-text">ToolGateway</code>,{" "}
              <code className="font-mono text-text">ChatModel</code>). Whether
              evidence arrives from our deterministic local simulator, uploaded
              export files, or a read-only snapshot from Grafana Loki,
              Prometheus (v0.6) or Datadog (v0.9), it is normalized
              into persisted, source-attributed{" "}
              <code className="font-mono text-text">ops.evidence</code> items
              before reasoning occurs.
            </p>
          </div>
        </div>
      </details>

      <details className="compact-disclosure secondary-catalog">
        <summary>Technical adapter contracts and examples</summary>
        <div className="mt-4 space-y-5">
          {/* Mode Selector & Category Filters */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-xl border border-border bg-panel p-3">
            <div
              className="flex flex-wrap items-center gap-1.5"
              role="tablist"
              aria-label="Usage Modes"
            >
              <button
                role="tab"
                aria-selected={selectedMode === "all"}
                onClick={() => setSelectedMode("all")}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all cursor-pointer ${
                  selectedMode === "all"
                    ? "bg-accent text-white shadow-xs"
                    : "bg-panel-2 text-muted hover:text-text"
                }`}
              >
                All Modes ({INTEGRATIONS.length})
              </button>
              <button
                role="tab"
                aria-selected={selectedMode === "demo"}
                onClick={() => setSelectedMode("demo")}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all cursor-pointer ${
                  selectedMode === "demo"
                    ? "bg-accent text-white shadow-xs"
                    : "bg-panel-2 text-muted hover:text-text"
                }`}
              >
                1. Demo Mode (Simulator)
              </button>
              <button
                role="tab"
                aria-selected={selectedMode === "offline"}
                onClick={() => setSelectedMode("offline")}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all cursor-pointer ${
                  selectedMode === "offline"
                    ? "bg-accent text-white shadow-xs"
                    : "bg-panel-2 text-muted hover:text-text"
                }`}
              >
                2. Offline / File Mode
              </button>
              <button
                role="tab"
                aria-selected={selectedMode === "connected"}
                onClick={() => setSelectedMode("connected")}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-all cursor-pointer ${
                  selectedMode === "connected"
                    ? "bg-accent text-white shadow-xs"
                    : "bg-panel-2 text-muted hover:text-text"
                }`}
              >
                3. Connected Mode (APIs &amp; MCP)
              </button>
            </div>

            <div className="flex items-center gap-2">
              <select
                aria-label="Signal category"
                value={selectedCategory}
                onChange={(e) =>
                  setSelectedCategory(e.target.value as Category)
                }
                className="h-8.5 rounded-lg border border-border bg-panel-2 px-3 text-xs font-medium text-text capitalize focus:outline-hidden"
              >
                <option value="all">All Telemetry Types</option>
                <option value="metrics">Metrics</option>
                <option value="logs">Logs</option>
                <option value="traces">Traces</option>
                <option value="changes">Changes &amp; CI/CD</option>
                <option value="dependencies">Dependencies</option>
                <option value="knowledge">Runbooks &amp; Knowledge</option>
                <option value="alerting">Alerting Webhooks</option>
              </select>
            </div>
          </div>
          {/* Main Two-Column View: Catalog List & Detail Inspector */}
          <div className="grid gap-6 lg:grid-cols-12">
            {/* Left: Integration Cards (5 cols) */}
            <div className="space-y-3 lg:col-span-5">
              {filtered.length === 0 ? (
                <Card>
                  <div className="py-8 text-center text-xs text-muted">
                    No integrations match the selected filter combination (Mode:{" "}
                    {selectedMode}, Category: {selectedCategory}).
                  </div>
                </Card>
              ) : (
                filtered.map((item) => {
                  const isSelected = activeItem?.id === item.id;
                  const isImplemented = item.status === "implemented";
                  const isAdapter = item.status === "requires_adapter";

                  return (
                    <button
                      type="button"
                      aria-pressed={isSelected}
                      key={item.id}
                      onClick={() => setSelectedItemId(item.id)}
                      className={`flex w-full text-left flex-col justify-between rounded-xl border p-4 transition-all cursor-pointer ${
                        isSelected
                          ? "border-accent bg-accent-soft/20 shadow-sm ring-1 ring-accent"
                          : "border-border bg-panel hover:border-border-strong hover:bg-panel-2"
                      }`}
                    >
                      <div>
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-bold text-sm text-text">
                            {item.name}
                          </span>
                          <Badge
                            tone={
                              isImplemented
                                ? "success"
                                : isAdapter
                                  ? "cyan"
                                  : "warn"
                            }
                          >
                            {isImplemented
                              ? "Implemented"
                              : isAdapter
                                ? "Requires Adapter"
                                : "Planned"}
                          </Badge>
                        </div>
                        <p className="mt-1 text-xs text-muted leading-relaxed line-clamp-2">
                          {item.tagline}
                        </p>
                      </div>

                      <div className="mt-3 flex items-center justify-between border-t border-border/60 pt-2 text-[11px] text-muted">
                        <span className="capitalize">{item.category}</span>
                        <span className="font-mono text-accent">
                          Inspect Details →
                        </span>
                      </div>
                    </button>
                  );
                })
              )}
            </div>

            {/* Right: Selected Integration Detail (7 cols) */}
            <div className="space-y-6 lg:col-span-7">
              {activeItem ? (
                <Card
                  title={activeItem.name}
                  subtitle={activeItem.tagline}
                  actions={
                    <Badge
                      tone={
                        activeItem.status === "implemented"
                          ? "success"
                          : activeItem.status === "requires_adapter"
                            ? "cyan"
                            : "warn"
                      }
                    >
                      {activeItem.status === "implemented"
                        ? "Verified Implemented in Repo"
                        : activeItem.status === "requires_adapter"
                          ? "Seam Available · Requires Adapter"
                          : "Planned Roadmap Seam"}
                    </Badge>
                  }
                >
                  <div className="space-y-5 text-xs leading-relaxed">
                    {/* Evidence Contributed */}
                    <div>
                      <h4 className="font-semibold uppercase tracking-wider text-muted text-[10px]">
                        Evidence Contributed to Investigation
                      </h4>
                      <ul className="mt-1.5 list-disc pl-4 space-y-1 text-text-muted">
                        {activeItem.evidenceContributed.map((e, i) => (
                          <li key={i}>{e}</li>
                        ))}
                      </ul>
                    </div>

                    {/* Prerequisites & Authentication */}
                    <div className="rounded-lg border border-border bg-panel-2/40 p-3.5 space-y-1">
                      <h4 className="font-semibold uppercase tracking-wider text-text text-[10px]">
                        Prerequisites &amp; Authentication Requirements
                      </h4>
                      <ul className="mt-1 list-disc pl-4 space-y-0.5 text-text-muted">
                        {activeItem.prerequisites.map((p, i) => (
                          <li key={i}>{fillModels(p, models)}</li>
                        ))}
                      </ul>
                    </div>

                    {/* Configuration Seam */}
                    <div>
                      <h4 className="font-semibold uppercase tracking-wider text-muted text-[10px]">
                        Configuration &amp; Code Seam
                      </h4>
                      <p className="mt-1 text-text-muted">
                        {activeItem.configuration}
                      </p>
                    </div>

                    {/* Example Query / File Structure */}
                    <div>
                      <h4 className="font-semibold uppercase tracking-wider text-muted text-[10px]">
                        Example Query / File Schema
                      </h4>
                      <CodeBlock
                        language={activeItem.exampleQuery.language}
                        code={activeItem.exampleQuery.code}
                      />
                    </div>

                    {/* Normalization & Agent Use */}
                    <div className="rounded-lg border border-info/30 bg-info-soft/30 p-3.5">
                      <h4 className="font-bold uppercase tracking-wider text-info text-[10px]">
                        Normalization &amp; Reasoning Pipeline
                      </h4>
                      <p className="mt-1 text-text leading-relaxed">
                        {fillModels(activeItem.normalization, models)}
                      </p>
                      <div className="mt-2 text-[11px] text-muted">
                        <strong>Primary Consuming Agent: </strong>
                        <span className="text-text font-medium">
                          {activeItem.targetNode}
                        </span>
                      </div>
                    </div>

                    {/* Testing & Troubleshooting */}
                    <div>
                      <h4 className="font-semibold uppercase tracking-wider text-muted text-[10px]">
                        Testing &amp; Troubleshooting Guide
                      </h4>
                      <ul className="mt-1 list-disc pl-4 space-y-1 text-text-muted">
                        {activeItem.troubleshooting.map((t, i) => (
                          <li key={i}>{t}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </Card>
              ) : (
                <Card title="No Integration Selected">
                  <div className="py-12 text-center text-xs text-muted">
                    No integration blueprint matches the active mode and
                    category filters. Choose another filter combination to view
                    architecture and configuration specifications.
                  </div>
                </Card>
              )}
            </div>
          </div>{" "}
        </div>
      </details>
    </div>
  );
}
