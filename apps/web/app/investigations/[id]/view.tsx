"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApprovalCard } from "@/components/approval-card";
import { SourceBadge } from "@/components/source-badge";
import {
  Badge,
  Button,
  Card,
  ConfidenceBar,
  Empty,
  ErrorNote,
  PageHeader,
  SeverityBadge,
  StatusBadge,
} from "@/components/ui";
import { api } from "@/lib/api";
import {
  ACTIVE_STATUSES,
  humanize,
  ms,
  STAGES,
  stageIndex,
  utcTime,
} from "@/lib/format";
import type { Evidence, WorkflowEvent } from "@/lib/types";
import { downloadText } from "@/lib/uploads";

/** Where stored evidence came from (file and line/row, or connector query and entry/point) */
function sourceRef(e: Evidence): string | null {
  const d = e.data as { attributes?: { source_ref?: string }; sources?: string; metadata?: { source_ref?: string } };
  return d?.attributes?.source_ref ?? d?.sources ?? d?.metadata?.source_ref ?? null;
}

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

function Stepper({
  events,
  current,
  status,
  readOnly = false,
}: {
  events: WorkflowEvent[];
  current: string | null;
  status: string;
  readOnly?: boolean;
}) {
  const visited = new Set(
    events.filter((e) => e.node).map((e) => stageIndex(e.node))
  );
  const activeIdx = TERMINAL.has(status) ? -1 : stageIndex(current);

  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Workflow progress">
      {STAGES.map((s, i) => {
        const isActive = i === activeIdx;
        const isDone = visited.has(i);
        const disabled = readOnly && s.key === "remediate";
        const label = readOnly && s.key === "approval" ? "Suggestions" : disabled ? "Remediate (read-only: off)" : s.label;

        let style = "border border-dashed border-border bg-panel-2 text-muted";
        if (isActive) {
          style = "border-accent bg-accent-soft text-accent font-semibold shadow-2xs ring-1 ring-accent/30";
        } else if (isDone) {
          style = "border-border bg-panel text-text font-medium";
        }
        if (disabled) style = "border-dashed border-border bg-panel-2/40 text-muted/60 line-through";

        return (
          <li
            key={s.key}
            aria-current={isActive ? "step" : undefined}
            className={`flex items-center gap-1.5 rounded-[4px] border px-2.5 py-1 font-mono text-xs transition-all ${style}`}
          >
            <span
              aria-hidden
              className={`size-1.5 rounded-full ${
                isActive
                  ? "animate-pulse bg-accent"
                  : isDone
                  ? "bg-success"
                  : "bg-border-strong"
              }`}
            />
            <span>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Synchronized Incident Timeline / Time-Scrubber Ribbon (incorporating Concept B into Concept A) */
function SynchronizedTimeRibbon({
  startedAt,
  events,
  onSelectEvent,
  selectedEventId,
}: {
  startedAt?: string | null;
  events: WorkflowEvent[];
  onSelectEvent?: (eventId: number) => void;
  selectedEventId?: number | null;
}) {
  const startTimeMs = startedAt ? new Date(startedAt).getTime() : 0;

  // Format delta offset e.g. "T+00:00", "T+00:24"
  const getOffset = (created: string) => {
    if (!startTimeMs) return "T+00:00";
    const curMs = new Date(created).getTime();
    const diffSec = Math.max(0, Math.round((curMs - startTimeMs) / 1000));
    const m = Math.floor(diffSec / 60);
    const s = diffSec % 60;
    return `T+${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  };

  const keyEvents = events.filter(
    (e) => e.event_type !== "node_started" || e.node === "triage"
  );

  return (
    <div className="dossier-paper p-3.5 space-y-2">
      <div className="flex items-center justify-between font-mono text-[11px] text-muted border-b border-border pb-1.5">
        <div className="flex items-center gap-2">
          <span className="font-bold text-accent">SYNCHRONIZED INCIDENT TIMELINE</span>
          <span>·</span>
          <span>RELATIVE OFFSET Δt</span>
        </div>
        <span className="text-text-muted">Real Agent Events ({events.length})</span>
      </div>

      <div className="flex items-center gap-2 overflow-x-auto py-1 scrollbar-thin">
        {keyEvents.slice(-7).map((ev) => {
          const isSelected = selectedEventId === ev.id;
          const isApproval = ev.event_type === "approval_requested";
          const isDone = ev.node === "verify_recovery" || ev.event_type === "workflow_completed";
          const offset = getOffset(ev.created_at);

          return (
            <button
              key={ev.id}
              onClick={() => onSelectEvent?.(ev.id)}
              className={`flex shrink-0 items-center gap-2 rounded-[3px] border px-2.5 py-1 text-left font-mono text-xs transition-all cursor-pointer ${
                isSelected
                  ? "border-accent bg-accent-soft text-accent ring-1 ring-accent"
                  : isApproval
                  ? "border-warn/60 bg-warn-soft/40 text-warn"
                  : isDone
                  ? "border-success/60 bg-success-soft/30 text-success"
                  : "border-border bg-panel-2 hover:bg-panel text-text"
              }`}
            >
              <span className="font-bold tabular-nums text-[11px] text-muted">{offset}</span>
              <span className="font-semibold text-text truncate max-w-[140px]">
                {ev.node ? humanize(ev.node) : humanize(ev.event_type)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Timeline({
  events,
  selectedEventId,
}: {
  events: WorkflowEvent[];
  selectedEventId?: number | null;
}) {
  const rows = events.filter((e) => e.event_type !== "node_started" || false);
  if (!rows.length) return <Empty>Waiting for the first workflow event…</Empty>;

  return (
    <ol className="relative space-y-3.5 border-l-2 border-border pl-4 text-xs font-mono">
      {rows.map((e) => {
        const p = e.payload;
        const tools = p.tool_calls ?? [];
        const llm = p.llm_calls ?? [];
        const isApproval = e.event_type === "approval_requested";
        const isSelected = selectedEventId === e.id;

        return (
          <li
            key={e.id}
            id={`event-${e.id}`}
            className={`relative rounded p-2 transition-colors ${
              isSelected ? "bg-accent-soft/30 border border-accent/40" : ""
            }`}
          >
            <span
              aria-hidden
              className={`absolute -left-[23px] top-3 size-2.5 rounded-full border border-panel ${
                isApproval
                  ? "bg-warn ring-2 ring-warn/30 animate-pulse"
                  : e.node
                  ? "bg-accent"
                  : "bg-muted"
              }`}
            />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] tabular-nums text-muted">
                {utcTime(e.created_at).slice(11)}
              </span>
              <span className="font-serif-heading text-sm font-bold text-text">
                {e.node ? humanize(e.node) : humanize(e.event_type)}
              </span>
              {e.event_type !== "node_completed" && e.node && (
                <Badge tone={isApproval ? "warn" : "neutral"}>
                  {humanize(e.event_type)}
                </Badge>
              )}
            </div>

            {p.active_task && (
              <div className="mt-1 rounded bg-panel-2 px-2 py-1 text-[11px] text-muted">
                <span className="text-text-muted font-medium">Task dispatch:</span>{" "}
                <span className="font-bold text-accent">
                  {p.active_task.capability}
                  {p.active_task.service ? `:${p.active_task.service}` : ""}
                </span>{" "}
                — {p.active_task.reason}
              </div>
            )}

            {tools.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {tools.map((t) => (
                  <Badge
                    key={t.id}
                    tone={t.status === "ok" ? "neutral" : "danger"}
                    className="text-[10px]"
                  >
                    <span>{t.tool}</span>
                    <span className="text-muted">·</span>
                    <span className="tabular-nums">{ms(t.latency_ms)}</span>
                  </Badge>
                ))}
              </div>
            )}

            {llm.map((c, i) => (
              <div
                key={i}
                className="mt-1 text-[11px] text-muted flex items-center gap-1.5"
              >
                <span className="text-purple font-semibold">LLM {c.purpose}</span>
                <span>·</span>
                <span>{c.model}</span>
                <span>·</span>
                <span>{ms(c.latency_ms)}</span>
                <span>·</span>
                <span>
                  {c.prompt_tokens ?? "?"}→{c.completion_tokens ?? "?"} tok
                </span>
              </div>
            ))}

            {(p.observations ?? []).map((o, i) => (
              <p
                key={i}
                className="mt-1 rounded border border-border bg-panel-2/50 p-2 text-xs text-text-muted leading-relaxed font-sans"
              >
                {o.finding}
              </p>
            ))}

            {(p.errors ?? []).map((er, i) => (
              <p
                key={i}
                className="mt-1 rounded border border-danger/30 bg-danger-soft p-2 text-xs text-danger"
              >
                <strong>[{er.error_class}]</strong> {er.message}
              </p>
            ))}

            {isApproval && (
              <div className="mt-1.5 rounded border border-warn/40 bg-warn-soft px-2.5 py-1.5 text-xs text-warn font-medium font-sans">
                ⏸ Paused at LangGraph interrupt — awaiting operator approval.
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function EvidenceList({
  evidence,
  highlight,
  selectedEvidenceId,
  onSelectEvidence,
  activeHypSupportingSet,
  activeHypContradictingSet,
  selectedHypothesisRank,
}: {
  evidence: Evidence[];
  highlight: Set<string>;
  selectedEvidenceId?: string | null;
  onSelectEvidence?: (id: string) => void;
  activeHypSupportingSet?: Set<string>;
  activeHypContradictingSet?: Set<string>;
  selectedHypothesisRank?: number;
}) {
  const kinds = useMemo(
    () => Array.from(new Set(evidence.map((e) => e.kind))),
    [evidence]
  );
  const [kind, setKind] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [onlyCited, setOnlyCited] = useState(false);

  const shown = evidence.filter((e) => {
    if (kind !== "all" && e.kind !== kind) return false;
    if (onlyCited && !highlight.has(e.evidence_id)) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return (
        e.evidence_id.toLowerCase().includes(q) ||
        e.summary.toLowerCase().includes(q) ||
        (e.service && e.service.toLowerCase().includes(q)) ||
        e.source_tool.toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div className="space-y-3 font-mono">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div
          className="flex flex-wrap gap-1"
          role="group"
          aria-label="Filter evidence by kind"
        >
          {["all", ...kinds].map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              aria-pressed={kind === k}
              className={`rounded-[3px] border px-2.5 py-1 text-xs font-semibold transition-colors cursor-pointer ${
                kind === k
                  ? "border-accent bg-accent-soft text-accent"
                  : "border-border bg-panel-2 text-muted hover:text-text"
              }`}
            >
              {humanize(k)}{" "}
              <span className="text-[10px] opacity-75">
                ({k === "all"
                  ? evidence.length
                  : evidence.filter((e) => e.kind === k).length})
              </span>
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search evidence..."
            className="h-7 w-40 rounded-[3px] border border-border bg-panel-2 px-2 text-xs text-text placeholder:text-muted/60 focus:outline-hidden"
          />
          <button
            onClick={() => setOnlyCited(!onlyCited)}
            className={`rounded-[3px] border px-2 py-1 text-xs font-medium transition-colors cursor-pointer ${
              onlyCited
                ? "border-info bg-info-soft text-info font-bold"
                : "border-border text-muted hover:text-text"
            }`}
          >
            Cited only
          </button>
        </div>
      </div>

      <div className="divide-y divide-border rounded-[4px] border border-border bg-panel">
        {shown.length > 0 ? (
          shown.map((e) => {
            const isCited = highlight.has(e.evidence_id);
            const isSelected = selectedEvidenceId === e.evidence_id;
            const isSupportingActive = activeHypSupportingSet?.has(e.evidence_id);
            const isContradictingActive = activeHypContradictingSet?.has(e.evidence_id);

            return (
              <div
                key={e.evidence_id}
                id={e.evidence_id}
                onClick={() => onSelectEvidence?.(e.evidence_id)}
                className={`p-3.5 transition-colors cursor-pointer ${
                  isSelected
                    ? "bg-accent-soft/30 border-l-4 border-l-accent"
                    : isSupportingActive
                    ? "bg-accent-soft/15 border-l-3 border-l-accent"
                    : isContradictingActive
                    ? "bg-danger-soft/20 border-l-3 border-l-danger"
                    : isCited
                    ? "bg-accent-soft/10 border-l-2 border-l-accent/60"
                    : "hover:bg-panel-2/50"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="exhibit-tag">
                      {e.evidence_id}
                    </span>
                    <Badge>{humanize(e.kind)}</Badge>
                    {e.service && (
                      <span className="text-[11px] text-muted">
                        svc:{e.service}
                      </span>
                    )}
                    {isSupportingActive && (
                      <span className="text-[10px] font-bold text-accent uppercase">
                        ★ Supports Hyp #{selectedHypothesisRank}
                      </span>
                    )}
                    {isContradictingActive && (
                      <span className="text-[10px] font-bold text-danger uppercase">
                        ✕ Contradicts Hyp #{selectedHypothesisRank}
                      </span>
                    )}
                    {!isSupportingActive && isCited && <span className="text-[10px] font-bold text-accent uppercase">★ Cited in RCA</span>}
                  </div>
                  <div className="flex items-center gap-2 text-[11px] text-muted">
                    <span>tool: {e.source_tool}</span>
                    <span>·</span>
                    <span>rel: {e.relevance.toFixed(2)}</span>
                  </div>
                </div>

                <p className="mt-2 text-xs text-text leading-relaxed font-sans font-medium">
                  {e.summary}
                </p>

                {sourceRef(e) && (
                  <div className="mt-2 rounded border border-purple/30 bg-purple-soft/20 px-2.5 py-1.5 text-[11px] text-muted font-mono">
                    <span className="font-semibold text-text-muted">Source reference coordinate:</span>{" "}
                    <span className="text-purple font-bold">{sourceRef(e)}</span>
                  </div>
                )}

                {e.citation && (
                  <div className="mt-2 rounded border border-border bg-panel-2 px-2.5 py-1.5 text-[11px] text-muted font-mono">
                    <span className="font-semibold text-text-muted">Runbook citation:</span>{" "}
                    <span className="text-accent font-bold">
                      {e.citation.source_uri}
                    </span>{" "}
                    › {e.citation.heading_path} · chunk{" "}
                    <code className="text-[10px]">
                      {e.citation.chunk_id.slice(0, 8)}
                    </code>
                  </div>
                )}
              </div>
            );
          })
        ) : (
          <div className="p-6 text-center text-xs text-muted">
            No evidence matches the active filters.
          </div>
        )}
      </div>
    </div>
  );
}

export function InvestigationView() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();

  const inv = useQuery({
    queryKey: ["investigation", id],
    queryFn: () => api.investigation(id),
    refetchInterval: (q) =>
      q.state.data && TERMINAL.has(q.state.data.status) ? false : 2000,
  });

  const live = !inv.data || !TERMINAL.has(inv.data.status) || inv.data.executing_in_process;
  const poll = live ? 2500 : false;

  const events = useQuery({
    queryKey: ["events", id],
    queryFn: () => api.events(id),
    refetchInterval: poll,
  });
  const evidence = useQuery({
    queryKey: ["evidence", id],
    queryFn: () => api.evidence(id),
    refetchInterval: poll,
  });
  const actions = useQuery({
    queryKey: ["actions", id],
    queryFn: () => api.actions(id),
    refetchInterval: poll,
  });
  const tools = useQuery({
    queryKey: ["tools", id],
    queryFn: () => api.toolCalls(id),
    refetchInterval: poll,
  });
  const report = useQuery({
    queryKey: ["report", id],
    queryFn: () => api.report(id),
    enabled:
      inv.data?.status === "completed" || inv.data?.status === "failed",
  });
  const incident = useQuery({
    queryKey: ["incident", inv.data?.incident_id],
    queryFn: () => api.incident(inv.data!.incident_id),
    enabled: !!inv.data?.incident_id,
  });

  const resume = useMutation({
    mutationFn: () => api.resume(id),
    onSuccess: () => qc.invalidateQueries(),
  });
  const cancel = useMutation({
    mutationFn: () => api.cancel(id),
    onSuccess: () => qc.invalidateQueries(),
  });

  const [showReport, setShowReport] = useState(true);
  const [activeTab, setActiveTab] = useState<"analysis" | "evidence" | "traces">(
    "analysis"
  );
  const [selectedHypothesisRank, setSelectedHypothesisRank] = useState<number>(1);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);

  const status = inv.data?.status;
  useEffect(() => {
    if (status && TERMINAL.has(status)) {
      for (const key of ["events", "evidence", "actions", "tools", "report"]) {
        qc.invalidateQueries({ queryKey: [key, id] });
      }
    }
  }, [status, id, qc]);

  const v = inv.data;
  const rca = v?.result?.rca;
  const hyps = useMemo(() => rca?.hypotheses ?? [], [rca]);
  const cited = useMemo(
    () => new Set(hyps.flatMap((h) => h.supporting_evidence_ids)),
    [hyps]
  );
  const evById = useMemo(
    () => new Map((evidence.data ?? []).map((e) => [e.evidence_id, e])),
    [evidence.data]
  );

  const canResume =
    v && (v.status === "interrupted" || v.status === "failed") && !v.executing_in_process;

  const outcome = v?.result?.outcome;
  const isAwaitingApproval = v?.status === "awaiting_approval";
  const source = incident.data?.evidence_source;
  const readOnly = source === "upload" || source === "connector";
  const suggested = v?.result?.suggested_remediation ?? [];

  // Active selected hypothesis for interactive highlighting
  const activeHypothesis = hyps.find((h) => h.rank === selectedHypothesisRank) ?? hyps[0];
  const activeHypSupportingSet = useMemo(
    () => new Set(activeHypothesis?.supporting_evidence_ids ?? []),
    [activeHypothesis]
  );
  const activeHypContradictingSet = useMemo(
    () => new Set(activeHypothesis?.contradicting_evidence_ids ?? []),
    [activeHypothesis]
  );

  return (
    <div className="space-y-6">
      {/* Top Breadcrumb & Dossier Identity */}
      <div>
        <div className="mb-2 flex items-center gap-2 font-mono text-xs text-muted">
          <Link href="/incidents" className="hover:text-text transition-colors">
            Incidents
          </Link>
          <span>/</span>
          {incident.data && (
            <Link
              href={`/incidents/${incident.data.id}`}
              className="font-bold hover:text-text transition-colors"
            >
              {incident.data.reference}
            </Link>
          )}
          <span>/</span>
          <span className="text-text-muted">DOSSIER-{id.slice(0, 8)}</span>
        </div>

        <PageHeader
          title={
            incident.data
              ? `${incident.data.reference}: ${incident.data.title}`
              : "Incident Forensics Workbench"
          }
          subtitle={
            v && (
              <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-xs text-muted">
                {incident.data && <SourceBadge source={incident.data.evidence_source} />}
                <span>
                  Dossier ID: <code className="font-bold text-text">{v.id.slice(0, 8)}</code>
                </span>
                <span>·</span>
                <span>
                  Model: <strong className="text-text font-semibold">{v.model}</strong>
                </span>
                <span>·</span>
                <span>Started: {utcTime(v.started_at)}</span>
                {v.incident_id && (
                  <>
                    <span>·</span>
                    <Link
                      className="text-accent hover:underline font-semibold"
                      href={`/incidents/${v.incident_id}`}
                    >
                      Incident Record →
                    </Link>
                  </>
                )}
              </div>
            )
          }
          actions={
            <div className="flex flex-wrap items-center gap-2">
              {incident.data && <SeverityBadge severity={incident.data.severity} />}
              {v && <StatusBadge status={v.status} />}
              {canResume && (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => resume.mutate()}
                  disabled={resume.isPending}
                >
                  {resume.isPending ? "Resuming…" : "Resume from checkpoint"}
                </Button>
              )}
              {v && !TERMINAL.has(v.status) && (
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => cancel.mutate()}
                  disabled={cancel.isPending}
                >
                  {cancel.isPending ? "Cancelling…" : "Cancel"}
                </Button>
              )}
            </div>
          }
        />
      </div>

      <ErrorNote error={inv.error ?? resume.error ?? cancel.error} />

      {/* Synchronized Incident Timeline / Time-Scrubber Ribbon */}
      <SynchronizedTimeRibbon
        startedAt={v?.started_at}
        events={events.data ?? []}
        onSelectEvent={(eventId) => {
          setSelectedEventId(eventId);
          setActiveTab("traces");
        }}
        selectedEventId={selectedEventId}
      />

      {/* Read-Only Forensic Mode Banners (Requirement 5) */}
      {source === "connector" && (
        <div className="dossier-paper border-l-4 border-l-info p-4 text-xs font-mono text-text">
          <div className="flex items-center gap-2 font-bold text-info">
            <span className="stamp-readonly">READ-ONLY FORENSIC AUDIT</span>
            <span>Connected Loki / Prometheus Telemetry Snapshot</span>
          </div>
          <p className="mt-1 font-sans text-text-muted leading-relaxed">
            Telemetry is captured from the allowlisted query snapshot (connector tool server{" "}
            <code>opspilot-connected-telemetry</code>); runbooks are indexed from pgvector. Remediation steps are provided as advisory suggestions only. Real infrastructure actions are disabled.
          </p>
        </div>
      )}
      {source === "upload" && (
        <div className="dossier-paper border-l-4 border-l-purple p-4 text-xs font-mono text-text">
          <div className="flex items-center gap-2 font-bold text-purple">
            <span className="stamp-readonly">READ-ONLY FORENSIC AUDIT</span>
            <span>Uploaded Artifacts &amp; Trace Analysis</span>
          </div>
          <p className="mt-1 font-sans text-text-muted leading-relaxed">
            Evidence is ingested from uploaded diagnostic files (tool server <code>opspilot-uploaded-evidence</code>). Remediation is published as advisory guidance only. No mutating commands are executed.
          </p>
        </div>
      )}

      {/* Pipeline Stepper */}
      {v && (
        <div className="dossier-paper p-4 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2">
            <span className="font-mono text-xs font-bold uppercase tracking-wider text-muted">
              Forensic Workflow Execution Pipeline
            </span>
            {ACTIVE_STATUSES.has(v.status) && (
              <span className="flex items-center gap-1.5 font-mono text-xs text-muted">
                <span className="size-2 rounded-full bg-accent animate-pulse" />
                Active node: <span className="font-bold text-accent">{v.current_step ?? "initializing"}</span>
              </span>
            )}
          </div>
          <Stepper
            events={events.data ?? []}
            current={v.current_step}
            status={v.status}
            readOnly={readOnly}
          />
        </div>
      )}

      {/* Prominent Next Action Alert: Awaiting Operator Approval */}
      {isAwaitingApproval && (
        <div
          role="alert"
          className="dossier-paper border-2 border-warn bg-warn-soft/40 p-5"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="size-2.5 rounded-full bg-warn animate-ping" />
                <h3 className="font-mono text-xs font-bold uppercase tracking-wider text-warn">
                  OPERATOR ACTION REQUIRED — Remediation Paused For Human Review
                </h3>
              </div>
              <p className="text-xs text-text-muted leading-relaxed font-sans">
                The agent completed evidence correlation and formulated an evidence-backed remediation plan.
                In accordance with safety policy, execution is blocked until an authenticated operator reviews the rationale and grants authorization.
              </p>
            </div>
            <a
              href="#remediation-section"
              className="inline-flex shrink-0 items-center justify-center rounded-[4px] bg-warn px-4 py-2 font-mono text-xs font-bold text-white hover:bg-warn/90 shadow-xs transition-all"
            >
              Review Proposed Action ↓
            </a>
          </div>
        </div>
      )}

      {/* Structured Outcome Banner */}
      {outcome && (
        <div
          role="status"
          className={`dossier-paper p-4 ${
            outcome.escalate
              ? "border-warn/40 bg-warn-soft/20"
              : outcome.code === "mitigated"
              ? "border-success/40 bg-success-soft/20"
              : "border-border bg-panel-2"
          }`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/80 pb-2">
            <div className="flex items-center gap-2 font-mono text-xs font-bold text-text">
              <span>Investigation Outcome:</span>
              <StatusBadge status={outcome.code} />
              {outcome.escalate && (
                <Badge tone="warn">
                  Human Escalation Required
                  {outcome.escalate_to ? ` · ${outcome.escalate_to}` : ""}
                </Badge>
              )}
            </div>
            <div className="font-mono text-xs text-muted">
              {outcome.read_only
                ? `read-only · ${outcome.suggested_steps ?? 0} suggested step(s) · nothing executed`
                : `${outcome.actions_executed} of ${outcome.steps_planned} planned actions executed`}
            </div>
          </div>
          <div className="mt-2 text-xs text-text leading-relaxed font-sans">
            <p className="font-semibold">{outcome.summary}</p>
            {outcome.reason && (
              <p className="mt-1 text-text-muted">{outcome.reason}</p>
            )}
          </div>
        </div>
      )}

      {/* Workspace Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-border font-mono text-xs">
        <button
          onClick={() => setActiveTab("analysis")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 font-bold transition-all cursor-pointer ${
            activeTab === "analysis"
              ? "border-accent text-accent"
              : "border-transparent text-muted hover:text-text"
          }`}
        >
          <span>Analysis &amp; Remediation</span>
          {isAwaitingApproval && (
            <span className="size-2 rounded-full bg-warn animate-pulse" />
          )}
        </button>
        <button
          onClick={() => setActiveTab("evidence")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 font-bold transition-all cursor-pointer ${
            activeTab === "evidence"
              ? "border-accent text-accent"
              : "border-transparent text-muted hover:text-text"
          }`}
        >
          <span>Collected Evidence Exhibits</span>
          <span className="rounded bg-panel-2 px-1.5 py-0.2 text-[10px]">
            {evidence.data?.length ?? 0}
          </span>
        </button>
        <button
          onClick={() => setActiveTab("traces")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 font-bold transition-all cursor-pointer ${
            activeTab === "traces"
              ? "border-accent text-accent"
              : "border-transparent text-muted hover:text-text"
          }`}
        >
          <span>Audit Timeline &amp; Tool Traces</span>
          <span className="rounded bg-panel-2 px-1.5 py-0.2 text-[10px]">
            {tools.data?.length ?? 0} tools
          </span>
        </button>
      </div>

      {/* Tab 1: Analysis & Remediation */}
      {activeTab === "analysis" && (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            {/* Root Cause Hypotheses Dossier */}
            <Card
              title="Root Cause Hypotheses"
              subtitle="Evidence-grounded hypothesis ranking (model-estimated confidence, uncalibrated probability)"
              actions={
                v?.result?.classification && (
                  <span className="font-mono text-xs text-muted">
                    triage:{" "}
                    <strong className="text-text">
                      {v.result.classification.category}
                    </strong>{" "}
                    ({v.result.classification.source})
                  </span>
                )
              }
            >
              {rca?.summary ? (
                <div className="space-y-4">
                  <div className="rounded-[4px] border border-border bg-panel-2 p-3.5 text-xs text-text leading-relaxed font-sans">
                    <span className="font-bold text-accent font-mono uppercase">Forensic Summary: </span>
                    {rca.summary}
                  </div>

                  <ol className="space-y-3 font-mono">
                    {hyps.map((h) => {
                      const isSelected = selectedHypothesisRank === h.rank;
                      return (
                        <li
                          key={h.rank}
                          onClick={() => setSelectedHypothesisRank(h.rank)}
                          className={`cursor-pointer rounded-[4px] border p-4 transition-all ${
                            isSelected
                              ? "border-accent bg-accent-soft/10 ring-1 ring-accent/40 shadow-xs"
                              : "border-border bg-panel hover:border-border-strong hover:bg-panel-2/40"
                          }`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <span className="grid size-5 place-items-center rounded-sm bg-panel-2 text-xs font-bold text-accent">
                                {h.rank}
                              </span>
                              <span className="font-serif-heading text-sm font-bold text-text">
                                {h.title}
                              </span>
                            </div>
                            <ConfidenceBar value={h.confidence} />
                          </div>

                          <div className="mt-2">
                            <Badge tone="cyan">{humanize(h.category)}</Badge>
                          </div>

                          <p className="mt-2 text-xs text-text-muted leading-relaxed font-sans">
                            {h.description}
                          </p>

                          {/* Interactive Evidence Citation Coordinates */}
                          <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border pt-2.5 text-[11px] text-muted">
                            <span className="font-bold text-text-muted">
                              Supporting exhibits:
                            </span>
                            {h.supporting_evidence_ids.map((eid) => (
                              <button
                                key={eid}
                                onClick={(ev) => {
                                  ev.stopPropagation();
                                  setSelectedEvidenceId(eid);
                                  setActiveTab("evidence");
                                }}
                                title={evById.get(eid)?.summary}
                                className="rounded border border-border bg-panel px-1.5 py-0.5 text-[10px] text-accent hover:border-accent hover:bg-accent-soft/20 font-bold"
                              >
                                {eid}
                                {evById.get(eid)
                                  ? ` · ${humanize(evById.get(eid)!.kind)}`
                                  : ""}
                              </button>
                            ))}
                            {h.contradicting_evidence_ids.map((eid) => (
                              <button
                                key={eid}
                                onClick={(ev) => {
                                  ev.stopPropagation();
                                  setSelectedEvidenceId(eid);
                                  setActiveTab("evidence");
                                }}
                                className="rounded border border-danger/40 bg-danger-soft/20 px-1.5 py-0.5 text-[10px] text-danger font-bold"
                              >
                                ✕ {eid}
                              </button>
                            ))}
                          </div>
                        </li>
                      );
                    })}
                  </ol>

                  {!!rca.evidence_gaps?.length && (
                    <div className="rounded-[4px] border border-warn/30 bg-warn-soft/20 p-3 font-mono">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-warn">
                        Identified Evidence Gaps &amp; Uncertainties
                      </h4>
                      <ul className="mt-1 list-disc pl-4 text-xs text-text-muted space-y-0.5 font-sans">
                        {rca.evidence_gaps.map((g, i) => (
                          <li key={i}>{g}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {!!rca.citation_violations?.length && (
                    <div className="rounded-[4px] border border-warn/30 bg-warn-soft/30 px-3 py-2 font-mono text-xs text-warn">
                      ⚠ Discarded {rca.citation_violations.length} fabricated evidence ID(s) cited by the model that did not exist in persisted telemetry.
                    </div>
                  )}
                </div>
              ) : (
                <Empty>
                  {v && TERMINAL.has(v.status)
                    ? "No Root Cause Analysis was generated."
                    : "Collecting telemetry and knowledge... hypotheses will populate once the RCA node runs."}
                </Empty>
              )}
            </Card>

            {/* Read-Only Mode: Advisory Suggestions (Requirement 5) */}
            {readOnly && (
              <Card
                id="remediation-section"
                title="Suggested Remediation (Read-Only Advice)"
                subtitle="Validated against evidence gates as advisory findings. OpsPilot executes no mutating actions in read-only mode."
              >
                {suggested.length ? (
                  <ol className="space-y-2 font-mono" aria-label="Suggested remediation">
                    {suggested.map((p) => (
                      <li key={p.step} className="rounded-[4px] border border-border bg-panel-2 p-3 text-xs">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-bold text-muted">{p.step}.</span>
                          <span className="font-semibold text-text">{p.action_type}</span>
                          <Badge>{p.role}</Badge>
                          <Badge tone="purple">suggestion · not executed</Badge>
                        </div>
                        <div className="mt-1 text-[11px] text-text-muted">
                          {Object.entries(p.parameters).map(([k, val]) => `${k}=${val}`).join(" · ")}
                        </div>
                        {p.rationale && <p className="mt-1 text-text-muted font-sans">{p.rationale}</p>}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Empty>
                    {v && TERMINAL.has(v.status)
                      ? `No remediation step was supported well enough by the ${source === "connector" ? "connected telemetry" : "uploaded evidence"} to suggest. See the next investigation steps in the report.`
                      : "Suggestions appear after the root-cause analysis."}
                  </Empty>
                )}
                {!!v?.result?.rejected_proposals?.length && (
                  <div className="mt-4 rounded-[4px] border border-border bg-panel-2 p-3 font-mono">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-muted">
                      Model proposals not suggested ({v.result.rejected_proposals.length})
                    </h4>
                    <ul className="mt-1.5 space-y-1 text-xs text-text-muted">
                      {v.result.rejected_proposals.map((r, i) => (
                        <li key={i}>
                          <code className="text-text font-bold">{String(r.proposal.action_type)}</code> —{" "}
                          {r.category ? `${r.category}: ` : ""}
                          {r.reason}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Card>
            )}

            {/* Mutating Mode: Remediation Plan & Safety Gates */}
            {!readOnly && (
              <Card
                id="remediation-section"
                title="Remediation Plan & Safety Gates"
                subtitle="Deterministic validation against invariant safety gates prior to human approval"
              >
                {!!v?.result?.remediation_plan?.length && (
                  <div className="mb-4">
                    <h4 className="mb-2 font-mono text-xs font-bold uppercase tracking-wider text-muted">
                      Execution Plan Steps ({v.result.remediation_plan.length})
                    </h4>
                    <ol className="flex flex-wrap gap-2 font-mono" aria-label="Remediation plan">
                      {v.result.remediation_plan.map((p) => {
                        const done = v.result?.executions?.find(
                          (x) => x.step === p.step
                        );
                        return (
                          <li
                            key={p.step}
                            className="flex items-center gap-2 rounded-[3px] border border-border bg-panel-2 px-3 py-1.5 text-xs"
                          >
                            <span className="font-bold text-muted">
                              {p.step}.
                            </span>
                            <span className="font-semibold text-text">
                              {p.action_type}
                            </span>
                            <Badge tone="neutral">{p.role}</Badge>
                            {p.added_by === "policy" && (
                              <Badge tone="info">policy-added</Badge>
                            )}
                            {done ? (
                              <StatusBadge status={done.status} />
                            ) : (
                              <span className="text-muted text-[11px]">pending</span>
                            )}
                          </li>
                        );
                      })}
                    </ol>
                  </div>
                )}

                {/* Blocked Proposals Demonstration */}
                {!!v?.result?.rejected_proposals?.length && (
                  <div className="mb-4 rounded-[4px] border border-danger/40 bg-danger-soft p-4 font-mono">
                    <div className="flex items-center gap-2">
                      <span className="text-danger font-bold">🛡</span>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-danger">
                        Proposals Blocked By Deterministic Safety Gates ({v.result.rejected_proposals.length})
                      </h4>
                    </div>
                    <p className="mt-1 text-[11px] text-text-muted font-sans">
                      The model proposed the following state changes, but deterministic safety gates blocked them before any human approval request was issued:
                    </p>
                    <ul className="mt-2.5 space-y-2 text-xs">
                      {v.result.rejected_proposals.map((r, i) => (
                        <li
                          key={i}
                          className="rounded border border-danger/30 bg-panel p-2.5"
                        >
                          <div className="flex items-center gap-2">
                            <Badge tone="danger">
                              blocked: {r.category || "unsafe"}
                            </Badge>
                            <code className="font-bold text-text">
                              {String(r.proposal.action_type)}
                            </code>
                          </div>
                          <p className="mt-1 text-xs text-text-muted font-medium font-sans">
                            Violation: {r.reason}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Action Requests & Approval Card */}
                {actions.data?.length ? (
                  <div className="space-y-4">
                    {actions.data.map((a) => (
                      <ApprovalCard key={a.id} action={a} />
                    ))}
                  </div>
                ) : v?.result?.rejected_proposals?.length ? null : (
                  <Empty>No remediation action proposed.</Empty>
                )}
              </Card>
            )}

            {/* Formal RCA Postmortem Report */}
            {report.data && (
              <Card
                title="RCA Postmortem Report"
                subtitle="Structured engineering incident report with evidence citations"
                actions={
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        downloadText(
                          `RCA-${incident.data?.reference ?? id.slice(0, 8)}.md`,
                          report.data!.markdown,
                        )
                      }
                    >
                      Download Markdown
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => setShowReport((s) => !s)}
                    >
                      {showReport ? "Collapse Report" : "Expand Report"}
                    </Button>
                  </div>
                }
              >
                {showReport && (
                  <article className="prose-report">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {report.data.markdown}
                    </ReactMarkdown>
                  </article>
                )}
              </Card>
            )}
          </div>

          {/* Right Column: Verification & Activity Feed */}
          <div className="space-y-6">
            {/* Recovery Verification Card */}
            {v?.result?.verification && (
              <Card
                title="Recovery Verification"
                subtitle="Affirmative post-condition verification (missing or stale telemetry fails closed as unknown)"
              >
                <div className="space-y-3 font-mono">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted">Outcome Verdict:</span>
                    <Badge
                      tone={
                        v.result.verification.recovered ? "success" : "danger"
                      }
                    >
                      {v.result.verification.recovered
                        ? "VERIFIED RECOVERY"
                        : "RECOVERY FAILED"}
                    </Badge>
                  </div>
                  <p className="text-xs text-text-muted leading-relaxed font-sans font-medium">
                    {v.result.verification.notes}
                  </p>
                  {(v.result.verification.observed_before !== undefined ||
                    v.result.verification.observed_after !== undefined) && (
                    <div className="grid grid-cols-2 gap-2 border-t border-border pt-2 text-xs">
                      <div>
                        <div className="text-muted">Pre-Action Metric:</div>
                        <div className="font-bold text-text">
                          {v.result.verification.observed_before ?? "—"}
                        </div>
                      </div>
                      <div>
                        <div className="text-muted">Post-Action Metric:</div>
                        <div className="font-bold text-success">
                          {v.result.verification.observed_after ?? "—"}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </Card>
            )}

            {/* Event Timeline Preview */}
            <Card
              title="Event Activity Stream"
              subtitle="Real-time execution log from LangGraph checkpointer"
              actions={
                <button
                  onClick={() => setActiveTab("traces")}
                  className="font-mono text-xs text-accent hover:underline cursor-pointer"
                >
                  Full traces →
                </button>
              }
            >
              <Timeline events={events.data ?? []} selectedEventId={selectedEventId} />
            </Card>

            {/* Tool Calls Summary */}
            <Card
              title={`Tool Calls (${tools.data?.length ?? 0})`}
              subtitle="MCP stdio tool invocations"
            >
              {tools.data?.length ? (
                <ul className="space-y-2 font-mono text-xs">
                  {tools.data.slice(-8).map((t) => (
                    <li
                      key={t.id}
                      className="rounded-[3px] border border-border bg-panel-2 p-2.5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-bold text-accent">
                          {t.tool}
                        </span>
                        <StatusBadge status={t.status} />
                      </div>
                      <div className="mt-1 flex items-center justify-between text-[11px] text-muted">
                        <span>
                          {t.agent} · {t.server}
                        </span>
                        <span className="tabular-nums">
                          {ms(t.latency_ms)}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty>No tools called yet.</Empty>
              )}
            </Card>
          </div>
        </div>
      )}

      {/* Tab 2: Evidence Explorer */}
      {activeTab === "evidence" && (
        <Card
          title={`Collected Evidence Exhibits (${evidence.data?.length ?? 0})`}
          subtitle="Persisted operational evidence gathered from telemetry, git changes, dependency graphs, and hybrid RAG"
        >
          {evidence.data?.length ? (
            <EvidenceList
              evidence={evidence.data}
              highlight={cited}
              selectedEvidenceId={selectedEvidenceId}
              onSelectEvidence={setSelectedEvidenceId}
              activeHypSupportingSet={activeHypSupportingSet}
              activeHypContradictingSet={activeHypContradictingSet}
              selectedHypothesisRank={selectedHypothesisRank}
            />
          ) : (
            <Empty>No evidence gathered yet.</Empty>
          )}
        </Card>
      )}

      {/* Tab 3: Traces & Tool Calls */}
      {activeTab === "traces" && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card
            title="Complete Event Timeline"
            subtitle="Durable checkpoint events from LangGraph"
          >
            <Timeline events={events.data ?? []} selectedEventId={selectedEventId} />
          </Card>

          <Card
            title={`Tool Invocations (${tools.data?.length ?? 0})`}
            subtitle="Protocol transactions across MCP read & action servers"
          >
            {tools.data?.length ? (
              <div className="space-y-2.5 font-mono">
                {tools.data.map((t) => (
                  <div
                    key={t.id}
                    className="rounded-[4px] border border-border bg-panel-2 p-3 text-xs"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <code className="font-bold text-accent">
                          {t.tool}
                        </code>
                        <Badge>{t.server}</Badge>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-muted tabular-nums">
                          {ms(t.latency_ms)}
                        </span>
                        <StatusBadge status={t.status} />
                      </div>
                    </div>
                    <div className="mt-2 text-[11px] text-muted">
                      <span>Agent caller: </span>
                      <strong className="text-text-muted">{t.agent}</strong>
                    </div>
                    {t.result_summary && (
                      <div className="mt-1.5 rounded bg-panel p-2 text-[10px] text-text-muted break-words">
                        {t.result_summary}
                      </div>
                    )}
                    {t.error && (
                      <div className="mt-1.5 rounded bg-danger-soft p-2 text-[10px] text-danger break-words">
                        {t.error}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <Empty>No tool calls executed yet.</Empty>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
