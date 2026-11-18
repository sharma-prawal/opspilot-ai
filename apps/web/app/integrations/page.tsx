"use client";

import Link from "next/link";
import { useState } from "react";
import { fillModels, useActiveModels } from "@/lib/models";
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
    tagline: "Deterministic fault generation across 6 published production-like scenarios.",
    evidenceContributed: [
      "Time-series metrics (HTTP 5xx ratios, p95 latency, queue depths, pool utilization)",
      "Structured application error logs and exception stack traces",
      "Git deployment commits, author signatures, and configuration changes",
      "Dependency topology graphs and datastore connection saturation",
    ],
    prerequisites: [
      "PostgreSQL 17 + pgvector container running on port 5433",
      "Local Ollama running the configured {LLM_MODEL} and {EMBEDDING_MODEL}",
      "Database migrations applied to head (0009)",
    ],
    configuration: "Built-in: POST /api/v1/incidents/simulate with scenario key (INC-001..003, NEG-001..003) or CLI uv run opspilot simulate.",
    exampleQuery: {
      language: "python",
      code: `# Invoked by MCP read server during investigation:
query_metrics(service="transaction-api", metric="http_requests_5xx_ratio", window="2026-11-03T13:45Z/14:15Z")
search_logs(service="transaction-api", limit=50)
list_recent_deployments(service="ledger-service")`,
    },
    normalization: "Persisted directly to ops.evidence with kind: telemetry, deployment, or config. Evaluates bidirectional excursion against baseline mean; computes temporal correlation score Δt against onset timestamp.",
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
    tagline: "Operational knowledge base ingested via pgvector hybrid reciprocal rank fusion.",
    evidenceContributed: [
      "Standard Operating Procedures (SOPs) and disaster recovery runbooks",
      "Historical postmortem documents and previous root-cause analyses",
      "Service architecture constraints and database capacity guidelines",
    ],
    prerequisites: [
      "Local Markdown (.md) or JSON (.json) documents in docs/ or knowledge/ directory",
      "YAML front-matter with title, doc_type (runbook, postmortem), services, and lifecycle_status",
    ],
    configuration: "Run uv run opspilot ingest (or make bootstrap). Incremental ingestion automatically hashes content via SHA-256 and skips unchanged files.",
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
    normalization: "Chunked using heading-aware boundaries (220 words / 40 word overlap). Embedded via the configured local {EMBEDDING_MODEL}. Stored in kb.documents and kb.chunks with composite foreign key guards preventing revision drift.",
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
    tagline: "Read-only analysis of your own sanitized .log/.txt, .json and .csv exports (v0.5, Analyze files page).",
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
    configuration: "Web: Analyze files (/incidents/new) → preview → create & analyze. API: POST /api/v1/incidents/upload/preview and /api/v1/incidents/upload (operator). Files are stored under UPLOAD_DIR; make uploads-purge removes old uploads.",
    exampleQuery: {
      language: "csv",
      code: `timestamp,service,http_5xx_ratio,p95_latency_ms,http_requests_per_min
2026-11-12T09:14:00.000Z,checkout-api,0.0035,182,431
2026-11-12T09:15:00.000Z,checkout-api,0.0491,654,409
# Each cell becomes a MetricRecord with source "service-metrics.csv:row N"`,
    },
    normalization: "Parsed by opspilot_shared.uploads into LogRecord / MetricRecord / EventRecord with source file:line, original timestamp and timezone, and service provenance. The file-backed evidence provider (server opspilot-uploaded-evidence) answers search_logs, query_metrics, list_recent_deployments and get_config_changes from them; live health, config, datastore and queue tools report 'not available'. Nothing is invented: rows without a timestamp or service are rejected and listed in the preview.",
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
    tagline: "Failing spans and observed service-to-service calls from OTLP/JSON or simple span JSON (v0.5).",
    evidenceContributed: [
      "Error spans as log-like evidence, naming the downstream service where the failure surfaced",
      "Observed caller → callee edges between services",
    ],
    prerequisites: [
      "OTLP/JSON (resourceSpans) or objects with trace_id, span_id, start time and duration or end time",
    ],
    configuration: "Upload the trace export with the other files on the Analyze files page; spans are normalized with their trace, span and parent IDs.",
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
    normalization: "Error spans are served through search_logs with attributes upstream=<failing downstream service>, span_id and source_ref; get_service_dependencies returns edges observed in the traces (kind observed_call).",
    troubleshooting: [
      "Upload the spans of every service in the trace so parent/child links across services can be resolved.",
    ],
    targetNode: "Telemetry & Dependencies Agents (file-backed provider)",
  },

  // Connected Mode
  {
    id: "prometheus-adapter",
    name: "Prometheus / Cortex / Thanos / Mimir",
    category: "metrics",
    mode: "connected",
    status: "requires_adapter",
    tagline: "Live PromQL time-series metrics over HTTP API or MCP protocol.",
    evidenceContributed: [
      "Request rates, error ratios, latency percentiles (p50, p95, p99), and satuation gauges",
      "Kubernetes pod container restarts, CPU throttling, and memory limits",
    ],
    prerequisites: [
      "Prometheus HTTP API endpoint reachable over local or VPN network",
      "Read-only query permissions (no write or administrative access)",
    ],
    configuration: "Set PROMETHEUS_URL=http://prometheus:9090 and optional PROMETHEUS_TOKEN in .env. Plugs into McpToolGateway via PrometheusReadAdapter.",
    exampleQuery: {
      language: "promql",
      code: `# Executed by MCP read server during telemetry analysis:
sum(rate(http_requests_total{service="transaction-api",status=~"5.."}[2m]))
/
sum(rate(http_requests_total{service="transaction-api"}[2m]))`,
    },
    normalization: "Queries range api/v1/query_range across the incident analysis window. Normalizes metric matrix into standard points array; unit-aware shift detector verifies recovery post-action.",
    troubleshooting: [
      "Test endpoint reachability with curl -s $PROMETHEUS_URL/-/healthy.",
      "Check PromQL step interval alignment to prevent timeout on wide analysis windows.",
    ],
    targetNode: "Telemetry Agent & Recovery Verification",
  },
  {
    id: "loki-adapter",
    name: "Grafana Loki",
    category: "logs",
    mode: "connected",
    status: "requires_adapter",
    tagline: "High-throughput LogQL search and stream clustering.",
    evidenceContributed: [
      "Application exception logs, stack traces, and database driver errors",
      "Log volume spikes and log-derived error rates",
    ],
    prerequisites: [
      "Grafana Loki query API endpoint (e.g. http://loki:3100)",
      "Optional X-Scope-OrgID tenant header for multi-tenant clusters",
    ],
    configuration: "Configure LOKI_URL=http://loki:3100. Implement LokiReadAdapter in packages/mcp/opspilot_mcp/adapters/loki.py.",
    exampleQuery: {
      language: "text",
      code: `// LogQL executed over Loki /loki/api/v1/query_range:
{service="transaction-api", env="production"} |= "error" | json | __error__=""`,
    },
    normalization: "Ingests raw log lines; strips transient variables (IP addresses, transaction IDs, timestamps) using drain/masking regex. Clusters unique signatures and counts frequencies.",
    troubleshooting: [
      "Verify query limit bounds (max 500 lines per call) to avoid overwhelming model context window.",
    ],
    targetNode: "Telemetry Agent",
  },
  {
    id: "datadog-adapter",
    name: "Datadog Unified Platform",
    category: "metrics",
    mode: "connected",
    status: "requires_adapter",
    tagline: "APM traces, metric anomalies, monitor states, and deployment events.",
    evidenceContributed: [
      "Datadog Metric queries and monitor state transition events",
      "APM service error tracking and deployment overlay markers",
    ],
    prerequisites: [
      "Datadog API Key and Application Key with read-only scopes",
      "Datadog site domain (e.g. datadoghq.com, datadoghq.eu)",
    ],
    configuration: "Set DD_API_KEY, DD_APP_KEY, and DD_SITE in .env. Plugs into ToolGateway via DatadogApiClient.",
    exampleQuery: {
      language: "bash",
      code: `# Executed against Datadog v2 API:
GET /api/v2/events?filter[query]=source:github+service:ledger-service
GET /api/v1/query?from=1700000000&to=1700001800&query=avg:trace.http.request.errors{service:transaction-api}`,
    },
    normalization: "Events mapped to Evidence(kind='deployment') for change correlation scoring. Metrics normalized to MetricSeries.",
    troubleshooting: [
      "Verify API/App key permissions with curl -X GET 'https://api.datadoghq.com/api/v1/validate'.",
    ],
    targetNode: "Changes & Telemetry Agents",
  },
  {
    id: "aws-cloudwatch",
    name: "AWS CloudWatch & Container Insights",
    category: "metrics",
    mode: "connected",
    status: "requires_adapter",
    tagline: "CloudWatch Metrics, Log Insights, and ECS/EKS Container telemetry.",
    evidenceContributed: [
      "ALB 5xx counts, RDS CPU/connection saturation, ECS task stop reasons",
      "CloudWatch Logs Insights query aggregations",
    ],
    prerequisites: [
      "AWS IAM Read-Only credentials (cloudwatch:GetMetricData, logs:StartQuery, logs:GetQueryResults)",
      "Configured AWS region (e.g. eu-west-1)",
    ],
    configuration: "Set AWS_REGION and standard AWS credentials (IAM role or AWS_ACCESS_KEY_ID). Implement CloudWatchReadAdapter.",
    exampleQuery: {
      language: "sql",
      code: `// CloudWatch Logs Insights query:
fields @timestamp, @message, @logStream
| filter @message like /Exception|Error/
| stats count() as errorCount by bin(1m)
| sort errorCount desc`,
    },
    normalization: "CloudWatch metric data points converted into unit-standardized floats. Log Insight query results mapped into Evidence(kind='telemetry').",
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
    status: "requires_adapter",
    tagline: "App Insights telemetry, Kusto (KQL) queries, and Azure Resource health.",
    evidenceContributed: [
      "Application Insights exception telemetry and failed dependency calls",
      "Kusto KQL query results on Log Analytics workspaces",
      "Azure Resource Manager (ARM) health status",
    ],
    prerequisites: [
      "Azure Service Principal with 'Monitoring Reader' role",
      "AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID, and Workspace ID",
    ],
    configuration: "Implement AzureMonitorAdapter using azure-monitor-query Python SDK.",
    exampleQuery: {
      language: "text",
      code: `// Kusto KQL query:
exceptions
| where timestamp between(datetime("2026-11-03T13:45Z") .. datetime("2026-11-03T14:15Z"))
| where cloud_RoleName == "transaction-api"
| summarize count() by type, outerMessage, bin(timestamp, 1m)`,
    },
    normalization: "KQL tabular output normalized into ops.evidence items with exception categorization.",
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
    status: "requires_adapter",
    tagline: "Live distributed tracing and causal call-chain dependency inspection.",
    evidenceContributed: [
      "End-to-end distributed trace spans across microservices",
      "Upstream vs downstream latency propagation and error roots",
    ],
    prerequisites: [
      "Grafana Tempo or Jaeger gRPC / HTTP query endpoint (e.g. http://tempo:3200)",
      "Standard W3C TraceContext propagation across instrumented services",
    ],
    configuration: "Configure TEMPO_URL=http://tempo:3200. Implement TempoTraceAdapter.",
    exampleQuery: {
      language: "text",
      code: `// TraceQL query executed against Tempo:
{ .service.name = "transaction-api" && .status.code = error }`,
    },
    normalization: "Trace call graph analysis feeds the Causal Consistency Safety Gate: verifies whether service X is failing due to downstream dependency Y, preventing mistaken rollbacks of healthy services.",
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
    status: "requires_adapter",
    tagline: "Live CI/CD release tracking and git commit correlation.",
    evidenceContributed: [
      "Deployment timestamps, release tags, and environment target names",
      "Git commit SHA, author, pull request title, and modified file paths",
    ],
    prerequisites: [
      "GitHub Personal Access Token or App Token with repo:status and actions:read scopes",
      "Repository name (owner/repo)",
    ],
    configuration: "Set GITHUB_TOKEN in .env. Implement GitHubDeploymentsAdapter querying /repos/{owner}/{repo}/deployments.",
    exampleQuery: {
      language: "bash",
      code: `# Executed against GitHub REST API:
GET /repos/sharma-prawal/opspilot-ai/deployments?environment=production
GET /repos/sharma-prawal/opspilot-ai/commits/23c7ef2`,
    },
    normalization: "Each deployment is converted to Evidence(kind='deployment'). OpsPilot calculates the temporal correlation score between commit timestamp and incident onset.",
    troubleshooting: [
      "Verify GitHub token rate limits with curl -H 'Authorization: Bearer $GITHUB_TOKEN' https://api.github.com/rate_limit.",
    ],
    targetNode: "Change Agent & Correlation Safety Gate",
  },
  {
    id: "alertmanager-pagerduty",
    name: "PagerDuty, Opsgenie & Alertmanager Webhooks",
    category: "alerting",
    mode: "connected",
    status: "planned",
    tagline: "Automated investigation trigger on inbound incident paging webhooks.",
    evidenceContributed: [
      "Incident title, firing alert name, severity, and initial alerting service",
      "Raw alert payload labels and annotations",
    ],
    prerequisites: [
      "Configured webhook endpoint URL in PagerDuty / Alertmanager",
      "Webhook secret token for HMAC-SHA256 signature verification",
    ],
    configuration: "Future planned route: POST /api/v1/incidents/webhook. Verifies signature, extracts service and onset timestamp, and starts background investigation automatically.",
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
    normalization: "Creates an ops.incidents record and immediately spawns a LangGraph thread, notifying on-call via web UI or Slack webhook.",
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
  const [selectedItemId, setSelectedItemId] = useState<string>(INTEGRATIONS[0].id);

  const filtered = INTEGRATIONS.filter((item) => {
    if (selectedMode !== "all" && item.mode !== selectedMode) return false;
    if (selectedCategory !== "all" && item.category !== selectedCategory) return false;
    return true;
  });

  // Always derive activeItem from filtered list; never show an item excluded by the active filter
  const activeItem = filtered.find((i) => i.id === selectedItemId) ?? filtered[0] ?? null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data Sources & Integrations"
        subtitle="Source-agnostic evidence ingestion: explore how synthetic simulators, air-gapped file exports, and live telemetry platforms integrate into standardized evidence."
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

      {/* Hero Banner: Source-Agnostic Philosophy */}
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
            OpsPilot AI is not coupled to any single observability provider or logging tool. The agent core interacts exclusively with typed port interfaces (<code className="font-mono text-text">ToolGateway</code>, <code className="font-mono text-text">ChatModel</code>). Whether evidence arrives from our deterministic local simulator, offline export files on a disconnected laptop, or enterprise observability APIs, it is normalized into immutable, verifiable <code className="font-mono text-text">ops.evidence</code> items before reasoning occurs.
          </p>
        </div>
      </div>

      {/* Mode Selector & Category Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-xl border border-border bg-panel p-3">
        <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="Usage Modes">
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
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value as Category)}
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
                No integrations match the selected filter combination (Mode: {selectedMode}, Category: {selectedCategory}).
              </div>
            </Card>
          ) : (
            filtered.map((item) => {
              const isSelected = activeItem?.id === item.id;
              const isImplemented = item.status === "implemented";
              const isAdapter = item.status === "requires_adapter";

              return (
                <div
                  key={item.id}
                  onClick={() => setSelectedItemId(item.id)}
                  className={`flex flex-col justify-between rounded-xl border p-4 transition-all cursor-pointer ${
                    isSelected
                      ? "border-accent bg-accent-soft/20 shadow-sm ring-1 ring-accent"
                      : "border-border bg-panel hover:border-border-strong hover:bg-panel-2"
                  }`}
                >
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-sm text-text">{item.name}</span>
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
                    <span className="font-mono text-accent">Inspect Details →</span>
                  </div>
                </div>
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
                  <p className="mt-1 text-text-muted">{activeItem.configuration}</p>
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
                    <span className="text-text font-medium">{activeItem.targetNode}</span>
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
                No integration blueprint matches the active mode and category filters. Choose another filter combination to view architecture and configuration specifications.
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
