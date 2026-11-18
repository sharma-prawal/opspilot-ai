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
  StatCard,
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
    expectedOutcome: "Unsafe pool resize blocked by safety gate → Rollback dep-ls-0291",
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
  const knowledgeChunksCount = o?.knowledge.chunks ?? 0;

  return (
    <div className="space-y-6">
      {/* Required e2e heading */}
      <PageHeader
        title="System overview"
        subtitle="Local Ollama inference, simulated fault environment, human-approved remediation — or read-only analysis of your own incident files."
        actions={
          <div className="flex items-center gap-2">
            <label htmlFor="scenario-select" className="sr-only">
              Scenario
            </label>
            <select
              id="scenario-select"
              aria-label="Scenario"
              value={selectedScenario}
              onChange={(e) => setSelectedScenario(e.target.value)}
              className="h-8.5 rounded-lg border border-border bg-panel px-3 text-xs font-medium text-text focus:outline-hidden focus:ring-2 focus:ring-accent"
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
          </div>
        }
      />

      <ErrorNote error={overview.error ?? simulateMutation.error} />

      {/* Product Hero & Value Proposition */}
      <div className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-panel via-panel to-panel-2 p-6 shadow-sm">
        <div className="relative z-10 flex flex-col justify-between gap-6 lg:flex-row lg:items-center">
          <div className="max-w-3xl space-y-2">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center rounded-md bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent">
                Autonomous SRE Agent
              </span>
              <span className="text-xs text-muted">
                LangGraph StateGraph · Local Ollama (<ModelName className="font-mono" />) · MCP stdio
              </span>
            </div>
            <h2 className="text-lg font-bold tracking-tight text-text sm:text-xl">
              Deterministic, Evidence-Grounded Distributed Incident Remediation
            </h2>
            <p className="text-sm leading-relaxed text-muted">
              OpsPilot AI ingests operational runbooks via hybrid pgvector RAG, correlates
              telemetry and deployment changes across services, formulates cited root-cause
              hypotheses, and executes verified remediation plans through cryptographic
              human operator approvals.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5 sm:shrink-0">
            <Link href="/architecture">
              <Button variant="secondary" size="md">
                Interactive Architecture →
              </Button>
            </Link>
            <Link href="/guide">
              <Button variant="outline" size="md">
                Getting Started Guide
              </Button>
            </Link>
            <Link href="/safety">
              <Button variant="outline" size="md">
                Safety Gates
              </Button>
            </Link>
          </div>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:gap-4">
        <StatCard
          label="Open incidents"
          value={openIncidentsCount}
          subtitle="Awaiting resolution or triage"
          tone={openIncidentsCount > 0 ? "warn" : "neutral"}
          badge={
            openIncidentsCount > 0 ? (
              <span className="size-2 rounded-full bg-warn animate-pulse" />
            ) : undefined
          }
        />
        <StatCard
          label="Running investigations"
          value={runningInvsCount}
          subtitle="Active LangGraph execution threads"
          tone={runningInvsCount > 0 ? "info" : "neutral"}
          badge={
            runningInvsCount > 0 ? (
              <span className="size-2 rounded-full bg-info animate-pulse" />
            ) : undefined
          }
        />
        <StatCard
          label="Pending approvals"
          value={pendingApprovalsCount}
          subtitle="Signed tokens awaiting operator decision"
          tone={pendingApprovalsCount > 0 ? "warn" : "neutral"}
          badge={
            pendingApprovalsCount > 0 ? (
              <Badge tone="warn">Action Required</Badge>
            ) : undefined
          }
        />
        <StatCard
          label="Knowledge chunks"
          value={knowledgeChunksCount}
          subtitle={`${o?.knowledge.documents ?? 0} runbooks & postmortems`}
          tone="neutral"
        />
      </div>

      {/* Synthetic Scenarios Catalog Launchpad */}
      <Card
        title="Synthetic Incident Scenarios"
        subtitle="Seeded, deterministic fault scenarios to evaluate agent behavior, safety gates, and recovery."
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {SCENARIO_CATALOG.map((s) => {
            const isMitigated = s.category === "mitigated";
            const isNoAction = s.category === "no_action";

            return (
              <div
                key={s.key}
                className="flex flex-col justify-between rounded-xl border border-border bg-panel-2/60 p-4 transition-all hover:border-border-strong hover:bg-panel-2"
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-sm font-bold text-accent">
                      {s.key}
                    </span>
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
                  <h3 className="mt-1.5 text-sm font-semibold text-text">
                    {s.title}
                  </h3>
                  <div className="mt-1 flex items-center gap-1.5 font-mono text-xs text-muted">
                    <span>svc:</span>
                    <span className="text-text-muted">{s.service}</span>
                  </div>
                  <p className="mt-2 text-xs text-muted leading-relaxed">
                    {s.description}
                  </p>
                </div>

                <div className="mt-4 border-t border-border/80 pt-3">
                  <div className="text-[11px] text-muted">
                    <span className="font-medium text-text-muted">Expected:</span>{" "}
                    {s.expectedOutcome}
                  </div>
                  <div className="mt-2.5 flex items-center justify-between">
                    <span className="text-[10px] text-muted">Seed 1001</span>
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
      </Card>

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
              className="text-xs font-semibold text-accent hover:underline"
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
                      <span className="truncate text-sm font-medium text-text group-hover:text-accent group-hover:underline">
                        {i.title}
                      </span>
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
                      <span>svc: <span className="font-mono text-text-muted">{i.service}</span></span>
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
            <div className="py-6 text-center text-xs text-muted">Checking runtime seams…</div>
          ) : deps.data ? (
            <div className="space-y-3">
              <ul className="space-y-2 text-xs">
                {Object.entries(deps.data.checks).map(([name, c]) => (
                  <li
                    key={name}
                    className="flex items-center justify-between rounded-lg border border-border bg-panel-2/50 px-3 py-2"
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
            <div className="rounded-lg border border-border bg-panel-2/40 p-4 text-xs text-muted">
              {deps.error ? <ErrorNote error={deps.error} /> : "Runtime dependency status unverified."}
            </div>
          )}

          {o && (
            <div className="mt-5 border-t border-border pt-4">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">
                Runtime Contracts
              </h3>
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
                          <span key="io" className="text-text">
                            {o.runtime.inference.provider} · think {o.runtime.inference.think ? "on" : "off"} · ctx{" "}
                            {o.runtime.inference.num_ctx} · T={o.runtime.inference.temperature}
                          </span>,
                        ] as [string, React.ReactNode],
                      ]
                    : []),
                  [
                    "MCP read tools",
                    <span key="mr" className="text-text">
                      {o.runtime.mcp_read_tools.length} mcp read
                    </span>,
                  ],
                  [
                    "MCP action tools",
                    <span key="ma" className="text-text">
                      {o.runtime.mcp_action_tools.length} mcp action
                    </span>,
                  ],
                  [
                    "Budgets",
                    <span key="b" className="text-text">
                      {o.runtime.agent_budgets.tool_calls} tools · {o.runtime.agent_budgets.llm_calls} LLM · {o.runtime.agent_budgets.rounds} rounds
                    </span>,
                  ],
                  [
                    "Max concurrency",
                    <span key="mc" className="text-text">
                      {o.runtime.max_concurrent_investigations} investigation
                    </span>,
                  ],
                  [
                    "KB documents",
                    <span key="doc" className="text-text">
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
