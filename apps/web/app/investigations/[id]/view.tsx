"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApprovalCard } from "@/components/approval-card";
import { Badge, Button, Card, ConfidenceBar, Empty, ErrorNote, PageHeader, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { ACTIVE_STATUSES, humanize, ms, STAGES, stageIndex, utcTime } from "@/lib/format";
import type { Evidence, WorkflowEvent } from "@/lib/types";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

function Stepper({ events, current, status }: { events: WorkflowEvent[]; current: string | null; status: string }) {
  const visited = new Set(events.filter((e) => e.node).map((e) => stageIndex(e.node)));
  const activeIdx = TERMINAL.has(status) ? -1 : stageIndex(current);
  return (
    <ol className="flex flex-wrap gap-1.5" aria-label="Workflow progress">
      {STAGES.map((s, i) => {
        const state = i === activeIdx ? "active" : visited.has(i) ? "done" : "todo";
        const cls = state === "active" ? "border-accent bg-accent-soft text-accent"
          : state === "done" ? "border-border bg-panel text-text" : "border-dashed border-border text-muted";
        return (
          <li key={s.key} aria-current={state === "active" ? "step" : undefined}
            className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium ${cls}`}>
            <span aria-hidden className={`size-1.5 rounded-full ${state === "active" ? "animate-pulse bg-accent" : state === "done" ? "bg-success" : "bg-border"}`} />
            {s.label}
          </li>
        );
      })}
    </ol>
  );
}

function Timeline({ events }: { events: WorkflowEvent[] }) {
  const rows = events.filter((e) => e.event_type !== "node_started" || false);
  if (!rows.length) return <Empty>Waiting for the first step…</Empty>;
  return (
    <ol className="space-y-2.5">
      {rows.map((e) => {
        const p = e.payload;
        const tools = p.tool_calls ?? [];
        const llm = p.llm_calls ?? [];
        return (
          <li key={e.id} className="border-l-2 border-border pl-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="tabular-nums text-muted">{utcTime(e.created_at).slice(11)}</span>
              <span className="font-medium">{e.node ? humanize(e.node) : humanize(e.event_type)}</span>
              {e.event_type !== "node_completed" && e.node && <Badge>{humanize(e.event_type)}</Badge>}
            </div>
            {p.active_task && (
              <div className="mt-0.5 text-xs text-muted">→ next: <span className="font-mono">{p.active_task.capability}{p.active_task.service ? `:${p.active_task.service}` : ""}</span> — {p.active_task.reason}</div>
            )}
            {tools.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {tools.map((t) => (
                  <Badge key={t.id} tone={t.status === "ok" ? "neutral" : "danger"}>
                    <span className="font-mono">{t.tool}</span> {ms(t.latency_ms)}
                  </Badge>
                ))}
              </div>
            )}
            {llm.map((c, i) => (
              <div key={i} className="mt-1 text-xs text-muted">
                LLM <span className="font-mono">{c.purpose}</span> · {c.model} · {ms(c.latency_ms)} · {c.prompt_tokens ?? "?"}→{c.completion_tokens ?? "?"} tokens
              </div>
            ))}
            {(p.observations ?? []).map((o, i) => <p key={i} className="mt-1 text-xs">{o.finding}</p>)}
            {(p.errors ?? []).map((er, i) => <p key={i} className="mt-1 text-xs text-danger">[{er.error_class}] {er.message}</p>)}
            {e.event_type === "approval_requested" && <p className="mt-1 text-xs text-warn">Paused — waiting for operator approval.</p>}
          </li>
        );
      })}
    </ol>
  );
}

function EvidenceList({ evidence, highlight }: { evidence: Evidence[]; highlight: Set<string> }) {
  const kinds = useMemo(() => Array.from(new Set(evidence.map((e) => e.kind))), [evidence]);
  const [kind, setKind] = useState<string>("all");
  const shown = evidence.filter((e) => kind === "all" || e.kind === kind);
  return (
    <>
      <div className="mb-3 flex flex-wrap gap-1" role="group" aria-label="Filter evidence by kind">
        {["all", ...kinds].map((k) => (
          <button key={k} onClick={() => setKind(k)} aria-pressed={kind === k}
            className={`rounded-md border px-2 py-0.5 text-xs ${kind === k ? "border-accent bg-accent-soft text-accent" : "border-border text-muted hover:text-text"}`}>
            {humanize(k)} {k === "all" ? evidence.length : evidence.filter((e) => e.kind === k).length}
          </button>
        ))}
      </div>
      <ul className="divide-y divide-border">
        {shown.map((e) => (
          <li key={e.evidence_id} id={e.evidence_id} className={`py-2.5 ${highlight.has(e.evidence_id) ? "bg-accent-soft/40 -mx-2 px-2 rounded" : ""}`}>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <code className="font-mono">{e.evidence_id}</code>
              <Badge>{humanize(e.kind)}</Badge>
              {e.service && <span className="font-mono text-muted">{e.service}</span>}
              <span className="text-muted">via {e.source_tool} · relevance {e.relevance.toFixed(2)}</span>
              {highlight.has(e.evidence_id) && <Badge tone="info">cited</Badge>}
            </div>
            <p className="mt-1 text-sm break-words">{e.summary}</p>
            {e.citation && (
              <p className="mt-1 text-xs text-muted">
                Source: <span className="font-mono">{e.citation.source_uri}</span> › {e.citation.heading_path} · chunk <code className="font-mono">{e.citation.chunk_id.slice(0, 8)}</code>
              </p>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

export function InvestigationView() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const inv = useQuery({
    queryKey: ["investigation", id], queryFn: () => api.investigation(id),
    refetchInterval: (q) => (q.state.data && TERMINAL.has(q.state.data.status) ? false : 2000),
  });
  const live = !inv.data || !TERMINAL.has(inv.data.status) || inv.data.executing_in_process;
  const poll = live ? 2500 : false;
  const events = useQuery({ queryKey: ["events", id], queryFn: () => api.events(id), refetchInterval: poll });
  const evidence = useQuery({ queryKey: ["evidence", id], queryFn: () => api.evidence(id), refetchInterval: poll });
  const actions = useQuery({ queryKey: ["actions", id], queryFn: () => api.actions(id), refetchInterval: poll });
  const tools = useQuery({ queryKey: ["tools", id], queryFn: () => api.toolCalls(id), refetchInterval: poll });
  const report = useQuery({ queryKey: ["report", id], queryFn: () => api.report(id), enabled: inv.data?.status === "completed" || inv.data?.status === "failed" });
  const incident = useQuery({ queryKey: ["incident", inv.data?.incident_id], queryFn: () => api.incident(inv.data!.incident_id), enabled: !!inv.data });
  const resume = useMutation({ mutationFn: () => api.resume(id), onSuccess: () => qc.invalidateQueries() });
  const cancel = useMutation({ mutationFn: () => api.cancel(id, "operator"), onSuccess: () => qc.invalidateQueries() });
  const [showReport, setShowReport] = useState(true);
  // Polling stops once the run is terminal; fetch everything one last time on that transition so
  // writes from the final nodes (execute/verify/report) are never missed.
  const status = inv.data?.status;
  useEffect(() => {
    if (status && TERMINAL.has(status)) {
      for (const key of ["events", "evidence", "actions", "tools", "report"]) qc.invalidateQueries({ queryKey: [key, id] });
    }
  }, [status, id, qc]);

  const v = inv.data;
  const rca = v?.result?.rca;
  const hyps = rca?.hypotheses ?? [];
  const cited = new Set(hyps.flatMap((h) => h.supporting_evidence_ids));
  const evById = new Map((evidence.data ?? []).map((e) => [e.evidence_id, e]));
  const canResume = v && (v.status === "interrupted" || v.status === "failed") && !v.executing_in_process;

  return (
    <>
      <PageHeader
        title={incident.data ? `${incident.data.reference}: ${incident.data.title}` : "Investigation"}
        subtitle={v && <>Investigation <code className="font-mono">{v.id.slice(0, 8)}</code> · model {v.model} · started {utcTime(v.started_at)}{v.incident_id && <> · <Link className="text-accent hover:underline" href={`/incidents/${v.incident_id}`}>incident</Link></>}</>}
        actions={<>
          {v && <StatusBadge status={v.status} />}
          {canResume && <Button onClick={() => resume.mutate()} disabled={resume.isPending}>Resume from checkpoint</Button>}
          {v && !TERMINAL.has(v.status) && <Button variant="danger" onClick={() => cancel.mutate()} disabled={cancel.isPending}>Cancel</Button>}
        </>}
      />
      <ErrorNote error={inv.error ?? resume.error ?? cancel.error} />
      {v && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <Stepper events={events.data ?? []} current={v.current_step} status={v.status} />
          {ACTIVE_STATUSES.has(v.status) && <span className="text-xs text-muted">Active step: <span className="font-mono">{v.current_step ?? "starting"}</span></span>}
        </div>
      )}
      {v?.error && <p className="mb-4 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">[{v.error_class}] {v.error}</p>}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Root cause analysis" actions={v?.result?.classification && (
            <span className="text-xs text-muted">initial triage: {v.result.classification.category} ({v.result.classification.source})</span>)}>
            {rca?.summary ? (
              <>
                <p className="text-sm leading-relaxed">{rca.summary}</p>
                <ol className="mt-4 space-y-3">
                  {hyps.map((h) => (
                    <li key={h.rank} className="rounded-md border border-border p-3">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="text-sm font-medium">{h.rank}. {h.title}</div>
                        <ConfidenceBar value={h.confidence} />
                      </div>
                      <div className="mt-1"><Badge>{humanize(h.category)}</Badge></div>
                      <p className="mt-2 text-sm text-muted">{h.description}</p>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {h.supporting_evidence_ids.map((eid) => (
                          <a key={eid} href={`#${eid}`} title={evById.get(eid)?.summary} className="rounded border border-border px-1.5 py-0.5 font-mono text-[11px] hover:border-accent">
                            {eid}{evById.get(eid) ? ` · ${humanize(evById.get(eid)!.kind)}` : ""}
                          </a>
                        ))}
                        {h.contradicting_evidence_ids.map((eid) => (
                          <a key={eid} href={`#${eid}`} className="rounded border border-danger/40 px-1.5 py-0.5 font-mono text-[11px] text-danger">✕ {eid}</a>
                        ))}
                      </div>
                    </li>
                  ))}
                </ol>
                {!!rca.evidence_gaps?.length && (
                  <div className="mt-4"><h3 className="text-xs font-semibold text-muted uppercase">Evidence gaps</h3>
                    <ul className="mt-1 list-disc pl-5 text-sm">{rca.evidence_gaps.map((g, i) => <li key={i}>{g}</li>)}</ul></div>
                )}
                {!!rca.citation_violations?.length && (
                  <p className="mt-3 text-xs text-warn">Discarded {rca.citation_violations.length} fabricated evidence ID(s) cited by the model.</p>
                )}
              </>
            ) : <Empty>{v && TERMINAL.has(v.status) ? "No RCA was produced." : "Collecting evidence — hypotheses appear after the RCA step."}</Empty>}
          </Card>

          <Card title="Remediation">
            {actions.data?.length ? (
              <div className="space-y-4">{actions.data.map((a) => <ApprovalCard key={a.id} action={a} />)}</div>
            ) : v?.result?.rejected_proposals?.length ? (
              <ul className="text-sm">{v.result.rejected_proposals.map((r, i) => <li key={i}>Model proposal blocked by policy: {r.reason}</li>)}</ul>
            ) : <Empty>No remediation proposed yet.</Empty>}
          </Card>

          <Card title={`Evidence (${evidence.data?.length ?? 0})`}>
            {evidence.data?.length ? <EvidenceList evidence={evidence.data} highlight={cited} /> : <Empty>No evidence yet.</Empty>}
          </Card>

          {report.data && (
            <Card title="RCA report" actions={<Button onClick={() => setShowReport((s) => !s)}>{showReport ? "Hide" : "Show"}</Button>}>
              {showReport && <article className="prose-report"><ReactMarkdown remarkPlugins={[remarkGfm]}>{report.data.markdown}</ReactMarkdown></article>}
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card title="Timeline"><Timeline events={events.data ?? []} /></Card>
          <Card title={`Tool calls (${tools.data?.length ?? 0})`}>
            {tools.data?.length ? (
              <ul className="space-y-1.5 text-xs">
                {tools.data.map((t) => (
                  <li key={t.id} className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div><span className="font-mono">{t.tool}</span> <span className="text-muted">· {t.agent} · {t.server}</span></div>
                      <div className="truncate text-muted" title={JSON.stringify(t.arguments)}>{t.error ?? t.result_summary ?? ""}</div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5"><span className="tabular-nums text-muted">{ms(t.latency_ms)}</span><StatusBadge status={t.status} /></div>
                  </li>
                ))}
              </ul>
            ) : <Empty>None yet.</Empty>}
          </Card>
        </div>
      </div>
    </>
  );
}
