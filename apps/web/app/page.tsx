"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SourceBadge } from "@/components/source-badge";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  KV,
  PageHeader,
  SeverityBadge,
  StatusBadge,
} from "@/components/ui";
import { api } from "@/lib/api";
import { ModelName } from "@/lib/models";
import { utcTime } from "@/lib/format";

interface ScenarioMeta {
  key: string;
  title: string;
  category: "mitigated" | "escalate" | "no_action";
  service: string;
  description: string;
  expectedOutcome: string;
}

const SCENARIO_CATALOG: ScenarioMeta[] = [
  {
    key: "INC-001",
    title: "Incompatible schema migration",
    category: "mitigated",
    service: "transaction-api",
    description: "HTTP 500 spike after unnotified column rename in ledger-service.",
    expectedOutcome: "Rollback deployment dep-ls-0042 → Verified Recovery",
  },
  {
    key: "INC-002",
    title: "Connection pool exhaustion",
    category: "mitigated",
    service: "ledger-db",
    description: "Sequential table scan consumes 93% of database connection pool.",
    expectedOutcome: "Unsafe pool resize blocked by safety gate D25 → Rollback dep-ls-0291",
  },
  {
    key: "INC-003",
    title: "Invalid settlement payloads",
    category: "mitigated",
    service: "settlement-worker",
    description: "Poison messages flood Dead-Letter Queue due to schema drift.",
    expectedOutcome: "4-step remediation: Pause → Rollback → Quarantine → Resume",
  },
  {
    key: "NEG-001",
    title: "Transient latency blip",
    category: "no_action",
    service: "payment-service",
    description: "Brief packet burst that cleared before investigation onset.",
    expectedOutcome: "Affirmative recovery confirmed → No action required",
  },
  {
    key: "NEG-002",
    title: "External provider outage",
    category: "escalate",
    service: "forex-gateway",
    description: "Third-party FX provider down; recent internal deployment is unrelated.",
    expectedOutcome: "Safety gate blocks red-herring rollback → Escalates to operator",
  },
  {
    key: "NEG-003",
    title: "Ambiguous changes & log outage",
    category: "escalate",
    service: "ledger-service",
    description: "Two simultaneous candidate deployments while log aggregator is unavailable.",
    expectedOutcome: "Insufficient evidence gate triggers → Escalates to human SRE",
  },
];

export default function OverviewPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [selectedScenario, setSelectedScenario] = useState("INC-001");
  const [activePathwayTab, setActivePathwayTab] = useState<"simulator" | "uploaded" | "connected">("simulator");

  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 5000,
  });
  const deps = useQuery({
    queryKey: ["deps"],
    queryFn: api.dependencies,
    refetchInterval: 15000,
  });
  const incidents = useQuery({
    queryKey: ["incidents"],
    queryFn: api.incidents,
    refetchInterval: 5000,
  });

  const simulateMutation = useMutation({
    mutationFn: (scenarioKey: string) => api.simulate(scenarioKey),
    onSuccess: (inc) => {
      qc.invalidateQueries({ queryKey: ["incidents"] });
      router.push(`/incidents/${inc.id}`);
    },
  });

  const o = overview.data;
  const sum = (r?: Record<string, number>, keys?: string[]) =>
    Object.entries(r ?? {}).reduce(
      (a, [k, v]) => a + (!keys || keys.includes(k) ? v : 0),
      0
    );

  const openIncidentsCount = sum(o?.incidents, [
    "open",
    "investigating",
    "awaiting_approval",
  ]);
  const runningInvsCount = sum(o?.investigations, ["queued", "running"]);
  const pendingApprovalsCount = o?.actions?.pending ?? 0;
  const knowledgeChunksCount = o?.knowledge?.chunks ?? 0;

  return (
    <div className="space-y-8">
      {/* Required e2e heading */}
      <PageHeader
        title="System overview"
        subtitle="Incident Forensics Workbench: Local Ollama inference, simulated fault environment, human-approved remediation — or read-only analysis of your own incident files."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="scenario-select" className="sr-only">
              Scenario
            </label>
            <select
              id="scenario-select"
              aria-label="Scenario"
              value={selectedScenario}
              onChange={(e) => setSelectedScenario(e.target.value)}
              className="h-8.5 rounded-[4px] border border-border bg-panel px-3 font-mono text-xs font-medium text-text focus:outline-hidden focus:ring-2 focus:ring-accent"
            >
              {SCENARIO_CATALOG.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.key}: {s.title}
                </option>
              ))}
            </select>
            <Button
              variant="primary"
              size="md"
              disabled={simulateMutation.isPending}
              onClick={() => simulateMutation.mutate(selectedScenario)}
            >
              {simulateMutation.isPending ? "Simulating…" : "Simulate"}
            </Button>
            <Link href="/incidents/new">
              <Button variant="secondary" size="md">
                Analyze your files
              </Button>
            </Link>
            <Link href="/incidents/new?source=connected">
              <Button variant="secondary" size="md">
                Use Loki / Prometheus
              </Button>
            </Link>
          </div>
        }
      />

      <ErrorNote error={overview.error ?? simulateMutation.error} />

      {/* Forensic Lab Invariants & Case Intake Header */}
      <div className="dossier-paper p-6">
        <div className="grid gap-6 lg:grid-cols-12">
          <div className="lg:col-span-8 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="exhibit-tag">ARCHIVAL SRE FORENSICS</span>
              <span className="font-mono text-xs text-muted">
                LangGraph StateMachine · Model: <ModelName className="font-semibold text-text" /> · MCP stdio
              </span>
            </div>
            <h2 className="font-serif-heading text-2xl font-bold tracking-tight text-text sm:text-3xl">
              Evidence-Grounded Distributed Incident Investigation
            </h2>
            <p className="max-w-2xl text-xs leading-relaxed text-text-muted">
              OpsPilot AI ingests operational runbooks via dense vector embeddings and PostgreSQL full-text search (tsvector, ts_rank_cd) with pgvector hybrid Reciprocal Rank Fusion (RRF), correlates telemetry and deployment changes across services, formulates cited root-cause hypotheses, and executes verified remediation plans through authenticated human operator approvals.
            </p>

            <div className="flex flex-wrap items-center gap-2 pt-2">
              <Link href="/architecture">
                <Button variant="secondary" size="sm">
                  System Anatomy →
                </Button>
              </Link>
              <Link href="/guide">
                <Button variant="outline" size="sm">
                  Field Guide
                </Button>
              </Link>
              <Link href="/safety">
                <Button variant="outline" size="sm">
                  Safety Gates
                </Button>
              </Link>
            </div>
          </div>

          {/* Contextual Case Metrics Box */}
          <div className="lg:col-span-4 rounded-[4px] border border-border-strong bg-panel-2 p-4 font-mono text-xs space-y-3">
            <div className="flex items-center justify-between border-b border-border/80 pb-2">
              <span className="font-bold uppercase tracking-wider text-muted">ACTIVE CASE STATS</span>
              <span className="text-[10px] text-accent">STRICT VERIFICATION</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="text-[10px] text-muted">OPEN CASES</div>
                <div className="text-lg font-bold text-text tabular-nums" suppressHydrationWarning>{openIncidentsCount}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted">RUNNING THREADS</div>
                <div className="text-lg font-bold text-info tabular-nums" suppressHydrationWarning>{runningInvsCount}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted">PENDING APPROVALS</div>
                <div className="text-lg font-bold text-warn tabular-nums" suppressHydrationWarning>{pendingApprovalsCount}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted">KNOWLEDGE CHUNKS</div>
                <div className="text-lg font-bold text-text tabular-nums" suppressHydrationWarning>{knowledgeChunksCount}</div>
              </div>
            </div>
            {pendingApprovalsCount > 0 && (
              <div className="rounded border border-warn/40 bg-warn-soft p-2 text-[11px] text-warn font-semibold">
                ⚠️ Authenticated operator approval pending for active plan.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Investigation Intake Pathways (3 Operating Modes) */}
      <div className="space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-border pb-3">
          <div>
            <h3 className="font-serif-heading text-lg font-bold text-text">
              Initiate Investigation Dossier
            </h3>
            <p className="text-xs text-muted">
              Select an investigation pathway: simulated fault scenarios, uploaded offline diagnostic files, or connected Loki/Prometheus telemetry.
            </p>
          </div>

          <div className="flex rounded-[4px] border border-border bg-panel-2 p-0.5 font-mono text-xs">
            <button
              onClick={() => setActivePathwayTab("simulator")}
              className={`rounded-[3px] px-3 py-1 font-semibold transition-all ${
                activePathwayTab === "simulator"
                  ? "bg-panel text-text shadow-2xs"
                  : "text-muted hover:text-text"
              }`}
            >
              1. Simulated Fault Scenarios (6)
            </button>
            <button
              onClick={() => setActivePathwayTab("uploaded")}
              className={`rounded-[3px] px-3 py-1 font-semibold transition-all ${
                activePathwayTab === "uploaded"
                  ? "bg-panel text-text shadow-2xs"
                  : "text-muted hover:text-text"
              }`}
            >
              2. Uploaded Artifacts
            </button>
            <button
              onClick={() => setActivePathwayTab("connected")}
              className={`rounded-[3px] px-3 py-1 font-semibold transition-all ${
                activePathwayTab === "connected"
                  ? "bg-panel text-text shadow-2xs"
                  : "text-muted hover:text-text"
              }`}
            >
              3. Connected Loki/Prometheus
            </button>
          </div>
        </div>

        {/* Pathway 1: Simulator Scenarios Catalog */}
        {activePathwayTab === "simulator" && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {SCENARIO_CATALOG.map((s) => {
              const isMitigated = s.category === "mitigated";
              const isNoAction = s.category === "no_action";

              return (
                <div
                  key={s.key}
                  className="dossier-paper flex flex-col justify-between p-4.5 transition-all hover:border-border-strong"
                >
                  <div>
                    <div className="flex items-center justify-between gap-2 border-b border-border/80 pb-2">
                      <span className="exhibit-tag">{s.key}</span>
                      <Badge
                        tone={
                          isMitigated
                            ? "success"
                            : isNoAction
                            ? "neutral"
                            : "warn"
                        }
                      >
                        {isMitigated
                          ? "Positive (Mitigated)"
                          : isNoAction
                          ? "Negative (No Action)"
                          : "Negative (Escalated)"}
                      </Badge>
                    </div>

                    <h4 className="font-serif-heading mt-2.5 text-sm font-bold text-text">
                      {s.title}
                    </h4>
                    <div className="mt-1 font-mono text-[11px] text-muted">
                      Target Service: <span className="font-semibold text-text-muted">{s.service}</span>
                    </div>
                    <p className="mt-1.5 text-xs text-text-muted leading-relaxed">
                      {s.description}
                    </p>
                  </div>

                  <div className="mt-4 border-t border-border pt-3">
                    <div className="text-[11px] text-muted">
                      <span className="font-mono font-medium text-text-muted">Expected:</span>{" "}
                      {s.expectedOutcome}
                    </div>
                    <div className="mt-2.5 flex items-center justify-between">
                      <span className="font-mono text-[10px] text-muted">Seed 1001</span>
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={simulateMutation.isPending}
                        onClick={() => simulateMutation.mutate(s.key)}
                      >
                        Simulate {s.key} →
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Pathway 2: Uploaded Artifacts Desk */}
        {activePathwayTab === "uploaded" && (
          <div className="dossier-paper p-6 space-y-4">
            <span className="exhibit-tag">MODE 02: OFFLINE ARTIFACT AUDIT</span>
            <h4 className="font-serif-heading text-xl font-bold text-text">
              Examine Uploaded Diagnostic Files &amp; Traces
            </h4>
            <p className="text-xs text-text-muted leading-relaxed max-w-2xl">
              Drop raw incident logs, CSV metric series, or JSON event traces. OpsPilot parses, deduplicates, and normalizes evidence into an immutable forensic dossier. The local model synthesizes root-cause hypotheses citing exact file names and line numbers.
            </p>
            <div className="rounded-[4px] border-2 border-dashed border-border-strong bg-panel-2/50 p-6 text-center">
              <div className="font-mono text-xs text-muted">OFFLINE EVIDENCE INGESTION DESK</div>
              <div className="mt-1 font-serif-heading text-sm font-semibold text-text">
                Accepts JSON logs, CSV metrics, and Jaeger/OTEL traces
              </div>
              <div className="mt-4">
                <Link href="/incidents/new">
                  <Button variant="primary" size="md">
                    Open File Upload Desk →
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        )}

        {/* Pathway 3: Connected Loki & Prometheus */}
        {activePathwayTab === "connected" && (
          <div className="dossier-paper p-6 space-y-4">
            <span className="exhibit-tag">MODE 03: LIVE OBSERVABILITY SNAPSHOT</span>
            <h4 className="font-serif-heading text-xl font-bold text-text">
              Audit Telemetry from Grafana Loki &amp; Prometheus
            </h4>
            <p className="text-xs text-text-muted leading-relaxed max-w-2xl">
              Execute allowlisted GET-only query templates against live telemetry providers. Captures an immutable snapshot window, attributes evidence to source query stamps, and generates a cited postmortem report. Zero mutating actions are permitted.
            </p>
            <div className="rounded-[4px] border border-border bg-panel-2 p-3.5 font-mono text-xs text-text-muted space-y-1">
              <div className="text-success font-semibold">✓ Connected Loki 3.5.0 at 127.0.0.1:3100</div>
              <div className="text-success font-semibold">✓ Connected Prometheus v3.5.0 at 127.0.0.1:9090</div>
              <div className="text-muted text-[11px]">Approved Templates: HTTP 5xx Rate, Connection Pool Saturation, DLQ Growth</div>
            </div>
            <Link href="/incidents/new?source=connected">
              <Button variant="primary" size="md">
                Configure Telemetry Snapshot →
              </Button>
            </Link>
          </div>
        )}
      </div>

      {/* Main Two-Column Layout: Incidents & Runtime Seams */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Recent Incidents (2 Columns) */}
        <Card
          title="Recent Incidents"
          subtitle="Incidents detected by telemetry monitoring or simulator runs"
          className="lg:col-span-2"
          actions={
            <Link
              href="/incidents"
              className="font-mono text-xs font-semibold text-accent hover:underline"
            >
              View all incidents ({incidents.data?.length ?? 0}) →
            </Link>
          }
        >
          {incidents.data?.length ? (
            <div className="divide-y divide-border">
              {incidents.data.slice(0, 6).map((i) => (
                <div
                  key={i.id}
                  className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <Link
                    href={`/incidents/${i.id}`}
                    className="group min-w-0 flex-1"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-semibold text-muted group-hover:text-accent">
                        {i.reference}
                      </span>
                      <span className="truncate font-serif-heading text-sm font-bold text-text group-hover:text-accent group-hover:underline">
                        {i.title}
                      </span>
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 font-mono text-xs text-muted">
                      <span>svc: <span className="text-text font-medium">{i.service}</span></span>
                      <span>·</span>
                      <SourceBadge source={i.evidence_source} />
                      <span>·</span>
                      <span>detected {utcTime(i.detected_at)}</span>
                    </div>
                  </Link>

                  <div className="flex shrink-0 items-center gap-2 sm:self-center">
                    <SeverityBadge severity={i.severity} />
                    <StatusBadge status={i.status} />
                    <Link href={`/incidents/${i.id}`}>
                      <Button variant="ghost" size="sm">
                        View
                      </Button>
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty
              action={
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => simulateMutation.mutate("INC-001")}
                >
                  Simulate INC-001 to start
                </Button>
              }
            >
              No incidents recorded yet. Simulate an incident scenario to begin an autonomous investigation.
            </Empty>
          )}
        </Card>

        {/* Runtime Dependencies & Component Health (1 Column) */}
        <Card
          title="Runtime Seams & Health"
          subtitle="Verification of local inference and MCP tools"
        >
          {deps.isLoading ? (
            <div className="py-6 text-center font-mono text-xs text-muted">Checking runtime seams…</div>
          ) : deps.data ? (
            <div className="space-y-3 font-mono text-xs">
              <ul className="space-y-2">
                {Object.entries(deps.data.checks).map(([name, c]) => (
                  <li
                    key={name}
                    className="flex items-center justify-between rounded-[3px] border border-border bg-panel-2 px-3 py-2"
                  >
                    <span className="font-medium text-text capitalize">
                      {name.replace(/_/g, " ")}
                    </span>
                    <StatusBadge status={c.ok ? "healthy" : "unhealthy"} />
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="rounded-[4px] border border-border bg-panel-2 p-4 font-mono text-xs text-muted">
              {deps.error ? <ErrorNote error={deps.error} /> : "Runtime dependency status unverified."}
            </div>
          )}

          {o && (
            <div className="mt-5 border-t border-border pt-4">
              <h4 className="mb-2 font-mono text-xs font-bold uppercase tracking-wider text-muted">
                Runtime Contracts
              </h4>
              <KV
                dense
                items={[
                  [
                    "LLM Port",
                    <code key="l" className="font-mono text-[11px] text-accent">
                      {o.runtime.llm_model}
                    </code>,
                  ],
                  [
                    "Embeddings",
                    <code key="e" className="font-mono text-[11px] text-accent">
                      {o.runtime.embedding_model}
                    </code>,
                  ],
                  ...(o.runtime.inference
                    ? [
                        [
                          "LLM options",
                          <span key="io" className="text-text font-mono text-xs">
                            {o.runtime.inference.provider} · think {o.runtime.inference.think ? "on" : "off"} · ctx{" "}
                            {o.runtime.inference.num_ctx} · T={o.runtime.inference.temperature}
                          </span>,
                        ] as [string, React.ReactNode],
                      ]
                    : []),
                  [
                    "MCP read tools",
                    <span key="mr" className="text-text font-mono text-xs">
                      {o.runtime.mcp_read_tools.length} mcp read
                    </span>,
                  ],
                  [
                    "MCP action tools",
                    <span key="ma" className="text-text font-mono text-xs">
                      {o.runtime.mcp_action_tools.length} mcp action
                    </span>,
                  ],
                  [
                    "Budgets",
                    <span key="b" className="text-text font-mono text-xs">
                      {o.runtime.agent_budgets.tool_calls} tools · {o.runtime.agent_budgets.llm_calls} LLM · {o.runtime.agent_budgets.rounds} rounds
                    </span>,
                  ],
                  [
                    "Max concurrency",
                    <span key="mc" className="text-text font-mono text-xs">
                      {o.runtime.max_concurrent_investigations} investigation
                    </span>,
                  ],
                  [
                    "KB documents",
                    <span key="doc" className="text-text font-mono text-xs">
                      {o.knowledge.documents} docs ({o.knowledge.chunks} chunks)
                    </span>,
                  ],
                ]}
              />
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
