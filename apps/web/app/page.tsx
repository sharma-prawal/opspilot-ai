"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { SimulateButton } from "@/components/simulate-button";
import { Badge, Card, Empty, ErrorNote, KV, PageHeader, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { utcTime } from "@/lib/format";

function Count({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-lg border border-border bg-panel px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

export default function OverviewPage() {
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview, refetchInterval: 5000 });
  const deps = useQuery({ queryKey: ["deps"], queryFn: api.dependencies, refetchInterval: 15000 });
  const incidents = useQuery({ queryKey: ["incidents"], queryFn: api.incidents, refetchInterval: 5000 });
  const o = overview.data;
  const sum = (r?: Record<string, number>, keys?: string[]) =>
    Object.entries(r ?? {}).reduce((a, [k, v]) => a + (!keys || keys.includes(k) ? v : 0), 0);

  return (
    <>
      <PageHeader title="System overview" subtitle="Local inference, sandboxed environment, human-approved remediation."
        actions={<SimulateButton />} />
      <ErrorNote error={overview.error} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Count label="Open incidents" value={sum(o?.incidents, ["open", "investigating", "awaiting_approval"])} />
        <Count label="Running investigations" value={sum(o?.investigations, ["queued", "running"])} />
        <Count label="Pending approvals" value={o?.actions?.pending ?? 0} tone={(o?.actions?.pending ?? 0) > 0 ? "text-warn" : ""} />
        <Count label="Knowledge chunks" value={o?.knowledge.chunks ?? 0} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Recent incidents" className="lg:col-span-2"
          actions={<Link href="/incidents" className="text-sm text-accent hover:underline">All incidents</Link>}>
          {incidents.data?.length ? (
            <ul className="divide-y divide-border">
              {incidents.data.slice(0, 6).map((i) => (
                <li key={i.id} className="flex items-center justify-between gap-3 py-2">
                  <Link href={`/incidents/${i.id}`} className="min-w-0">
                    <div className="truncate text-sm font-medium hover:underline">{i.title}</div>
                    <div className="text-xs text-muted">{i.reference} · {i.service} · detected {utcTime(i.detected_at)}</div>
                  </Link>
                  <div className="flex shrink-0 items-center gap-2"><Badge>{i.severity}</Badge><StatusBadge status={i.status} /></div>
                </li>
              ))}
            </ul>
          ) : <Empty>No incidents yet. Simulate INC-001 to start.</Empty>}
        </Card>

        <Card title="Dependencies">
          {deps.data ? (
            <ul className="space-y-2 text-sm">
              {Object.entries(deps.data.checks).map(([name, c]) => (
                <li key={name} className="flex items-center justify-between">
                  <span>{name.replace("_", " ")}</span>
                  <StatusBadge status={c.ok ? "healthy" : "unhealthy"} />
                </li>
              ))}
            </ul>
          ) : <ErrorNote error={deps.error} />}
          {o && (
            <div className="mt-4 border-t border-border pt-3">
              <KV items={[
                ["LLM", <code key="l" className="font-mono text-xs">{o.runtime.llm_model}</code>],
                ["Embeddings", <code key="e" className="font-mono text-xs">{o.runtime.embedding_model}</code>],
                ["MCP tools", `${o.runtime.mcp_read_tools.length} read · ${o.runtime.mcp_action_tools.length} action`],
                ["Budgets", `${o.runtime.agent_budgets.tool_calls} tools · ${o.runtime.agent_budgets.llm_calls} LLM · ${o.runtime.agent_budgets.rounds} rounds`],
                ["Documents", o.knowledge.documents],
              ]} />
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
