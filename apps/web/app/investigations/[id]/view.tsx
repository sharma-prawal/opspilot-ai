"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { type MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApprovalCard } from "@/components/approval-card";
import { SourceBadge } from "@/components/source-badge";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  PageHeader,
  SeverityBadge,
  StatusBadge,
} from "@/components/ui";
import {
  Composition,
  DecisionFlow,
  EvidenceMap,
  HypothesisComparison,
  MetricComparison,
  SourceTimeline,
} from "@/components/visuals";
import { evidenceGroup } from "@/lib/visuals";
import { api } from "@/lib/api";
import { humanize, ms, STAGES, stageIndex, utcTime } from "@/lib/format";
import type { Evidence, WorkflowEvent } from "@/lib/types";
import { downloadText } from "@/lib/uploads";

/** Where stored evidence came from (file and line/row, or connector query and entry/point) */
function sourceRef(e: Evidence): string | null {
  const d = e.data as {
    attributes?: { source_ref?: string };
    sources?: string;
    metadata?: { source_ref?: string };
  };
  const value =
    d?.attributes?.source_ref ?? d?.sources ?? d?.metadata?.source_ref;
  return value == null
    ? null
    : typeof value === "string"
      ? value
      : JSON.stringify(value);
}

const TERMINAL = new Set(["completed", "failed", "cancelled", "interrupted"]);

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
    events.filter((e) => e.node).map((e) => stageIndex(e.node)),
  );
  const activeIdx = TERMINAL.has(status) ? -1 : stageIndex(current);

  return (
    <ol
      className="flex flex-wrap items-center gap-2"
      aria-label="Workflow progress"
    >
      {STAGES.map((s, i) => {
        const isActive = i === activeIdx;
        const disabled = readOnly && s.key === "remediate";
        const isDone = !disabled && visited.has(i);
        const label =
          readOnly && s.key === "approval"
            ? "Suggestions"
            : disabled
              ? "Remediate (read-only: off)"
              : s.label;

        let style = "border border-dashed border-border bg-panel-2 text-muted";
        if (isActive) {
          style =
            "border-accent bg-accent-soft text-accent font-semibold shadow-2xs ring-1 ring-accent/30";
        } else if (isDone) {
          style = "border-border bg-panel text-text font-medium";
        }
        if (disabled)
          style =
            "border-dashed border-border bg-panel-2/40 text-muted/60 line-through";

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
  const startTimeMs = startedAt
    ? new Date(startedAt).getTime()
    : events[0]?.created_at
      ? new Date(events[0].created_at).getTime()
      : 0;

  // Format delta offset e.g. "T+00:00", "T+00:24" — never fabricates timestamps
  const getOffset = (created: string) => {
    if (!startTimeMs || !created) return "—";
    const curMs = new Date(created).getTime();
    if (isNaN(curMs) || isNaN(startTimeMs)) return "—";
    const diffSec = Math.max(0, Math.round((curMs - startTimeMs) / 1000));
    const m = Math.floor(diffSec / 60);
    const s = diffSec % 60;
    return `T+${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  };

  const keyEvents = events.filter(
    (e) => e.event_type !== "node_started" || e.node === "triage",
  );

  return (
    <div className="dossier-paper p-3.5 space-y-2 min-w-0 overflow-hidden">
      <div className="flex items-center justify-between font-mono text-[11px] text-muted border-b border-border pb-1.5">
        <div className="flex items-center gap-2">
          <span className="font-bold text-accent">Workflow chronology</span>
          <span>·</span>
          <span>Execution offsets</span>
        </div>
        <span className="text-text-muted">
          Workflow events ({events.length})
        </span>
      </div>

      <div className="flex items-center gap-2 overflow-x-auto py-1 scrollbar-thin min-w-0 pr-4">
        {keyEvents.length === 0 ? (
          <span className="text-muted text-xs italic py-1 font-mono">
            Awaiting agent execution events…
          </span>
        ) : (
          keyEvents.map((ev) => {
            const isSelected = selectedEventId === ev.id;
            const isApproval =
              ev.event_type === "approval_requested" ||
              ev.node === "human_approval" ||
              ev.node === "await_approval";
            const isDone =
              ev.node === "verify_recovery" ||
              ev.event_type === "workflow_completed" ||
              ev.node === "report";
            const offset = getOffset(ev.created_at);

            return (
              <button
                key={ev.id}
                aria-pressed={isSelected}
                title={utcTime(ev.created_at)}
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
                <span className="font-bold tabular-nums text-[11px] text-muted">
                  {offset}
                </span>
                <time className="sr-only" dateTime={ev.created_at}>
                  {utcTime(ev.created_at)}
                </time>
                <span className="font-semibold text-text truncate max-w-[150px]">
                  {ev.node ? humanize(ev.node) : humanize(ev.event_type)}
                </span>
              </button>
            );
          })
        )}
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
            tabIndex={-1}
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
                <span className="text-text-muted font-medium">
                  Task dispatch:
                </span>{" "}
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
                <span className="text-purple font-semibold">
                  LLM {c.purpose}
                </span>
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
  initialGroup = "all",
}: {
  initialGroup?: string;
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
    [evidence],
  );
  const [kind, setKind] = useState<string>("all");
  const [group, setGroup] = useState(initialGroup);
  const [search, setSearch] = useState("");
  const [onlyCited, setOnlyCited] = useState(false);

  const shown = evidence.filter((e) => {
    if (group !== "all" && evidenceGroup(e) !== group) return false;
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
      {group !== "all" && (
        <div className="flex items-center gap-3 text-xs">
          <Badge>{group}</Badge>
          <button className="text-link" onClick={() => setGroup("all")}>
            Show all categories
          </button>
        </div>
      )}
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
                (
                {k === "all"
                  ? evidence.length
                  : evidence.filter((e) => e.kind === k).length}
                )
              </span>
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search evidence"
            placeholder="Search evidence…"
            className="h-7 w-40 rounded-[3px] border border-border bg-panel-2 px-2 text-xs text-text placeholder:text-muted/60 focus:outline-hidden"
          />
          <button
            aria-pressed={onlyCited}
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
            const isSupportingActive = activeHypSupportingSet?.has(
              e.evidence_id,
            );
            const isContradictingActive = activeHypContradictingSet?.has(
              e.evidence_id,
            );

            return (
              <div
                key={e.evidence_id}
                id={e.evidence_id}
                tabIndex={0}
                role="button"
                aria-label={`Inspect ${e.evidence_id}`}
                aria-expanded={isSelected}
                onKeyDown={(event) => {
                  if (event.target !== event.currentTarget) return;
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelectEvidence?.(isSelected ? "" : e.evidence_id);
                  }
                }}
                onClick={() =>
                  onSelectEvidence?.(isSelected ? "" : e.evidence_id)
                }
                className={`p-3.5 transition-colors cursor-pointer ${
                  isSelected
                    ? "bg-accent-soft/30 outline outline-accent"
                    : isSupportingActive
                      ? "bg-success-soft/30"
                      : isContradictingActive
                        ? "bg-danger-soft/30"
                        : isCited
                          ? "bg-accent-soft/10"
                          : "hover:bg-panel-2/50"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="exhibit-tag">{e.evidence_id}</span>
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
                    {!isSupportingActive && isCited && (
                      <span className="text-[10px] font-bold text-accent uppercase">
                        ★ Cited in RCA
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-[11px] text-muted">
                    <span>tool: {e.source_tool}</span>
                    <span>·</span>
                    <span>rel: {e.relevance.toFixed(2)}</span>
                    {e.observed_at && (
                      <time dateTime={e.observed_at}>
                        {utcTime(e.observed_at)}
                      </time>
                    )}
                  </div>
                </div>

                <p className="mt-2 text-xs text-text leading-relaxed font-sans font-medium">
                  {e.summary}
                </p>

                {sourceRef(e) && (
                  <div className="mt-2 rounded border border-purple/30 bg-purple-soft/20 px-2.5 py-1.5 text-[11px] text-muted font-mono">
                    <span className="font-semibold text-text-muted">
                      Source reference coordinate:
                    </span>{" "}
                    <span className="text-purple font-bold">
                      {sourceRef(e)}
                    </span>
                  </div>
                )}

                {e.citation && (
                  <div className="mt-2 rounded border border-border bg-panel-2 px-2.5 py-1.5 text-[11px] text-muted font-mono">
                    <span className="font-semibold text-text-muted">
                      Runbook citation:
                    </span>{" "}
                    <span className="text-accent font-bold">
                      {e.citation.source_uri}
                    </span>{" "}
                    › {e.citation.heading_path} · chunk{" "}
                    <code className="text-[10px]">
                      {e.citation.chunk_id.slice(0, 8)}
                    </code>
                  </div>
                )}

                {isSelected && e.data && (
                  <div className="mt-3 rounded border border-border bg-panel-2 p-3 font-mono text-[11px]">
                    <div className="mb-1 font-bold text-text-muted uppercase text-[10px]">
                      Underlying Forensic Payload
                    </div>
                    <pre className="max-h-60 overflow-auto whitespace-pre-wrap text-text">
                      {JSON.stringify(e.data, null, 2)}
                    </pre>
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
  // Keying by id guarantees that switching investigations completely resets all local state
  return <InvestigationWorkspace key={id} id={id} />;
}

function InvestigationWorkspace({ id }: { id: string }) {
  const qc = useQueryClient();

  const inv = useQuery({
    queryKey: ["investigation", id],
    queryFn: () => api.investigation(id),
    refetchInterval: (q) =>
      q.state.data && TERMINAL.has(q.state.data.status) ? false : 2000,
  });

  const live =
    !inv.data ||
    !TERMINAL.has(inv.data.status) ||
    inv.data.executing_in_process;
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
    enabled: inv.data?.status === "completed" || inv.data?.status === "failed",
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

  const [showReport, setShowReport] = useState(false);
  const [activeTab, setActiveTab] = useState<
    "analysis" | "evidence" | "traces"
  >("analysis");
  const [selectedHypothesisRank, setSelectedHypothesisRank] =
    useState<number>(1);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(
    null,
  );
  const [evidenceGroupFilter, setEvidenceGroupFilter] = useState("all");
  const [remediationRequest, setRemediationRequest] = useState(0);
  const handledRemediation = useRef(0);
  const openRemediation = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    setActiveTab("analysis");
    setRemediationRequest((n) => n + 1);
  };
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);

  const status = inv.data?.status;
  useEffect(() => {
    if (status && TERMINAL.has(status)) {
      for (const key of ["events", "evidence", "actions", "tools", "report"]) {
        qc.invalidateQueries({ queryKey: [key, id] });
      }
    }
  }, [status, id, qc]);

  useEffect(() => {
    const target =
      activeTab === "evidence"
        ? selectedEvidenceId
        : activeTab === "traces" && selectedEventId
          ? `event-${selectedEventId}`
          : null;
    if (target) {
      const element = document.getElementById(target);
      element?.focus({ preventScroll: true });
      element?.scrollIntoView({ block: "nearest", behavior: "instant" });
    }
  }, [activeTab, selectedEvidenceId, selectedEventId]);

  useEffect(() => {
    if (
      activeTab !== "analysis" ||
      handledRemediation.current === remediationRequest
    )
      return;
    if (actions.isPending) return;
    const element =
      document.querySelector<HTMLElement>(
        '[data-pending-approval="true"] [data-approval-primary]:not(:disabled)',
      ) ??
      document.querySelector<HTMLElement>(
        '[data-pending-approval="true"] form',
      ) ??
      document.getElementById("remediation-section");
    if (element) {
      handledRemediation.current = remediationRequest;
      element.focus({ preventScroll: true });
      element.scrollIntoView({ block: "start", behavior: "instant" });
    }
  }, [activeTab, remediationRequest, actions.isPending, actions.data]);

  const v = inv.data;
  const rca = v?.result?.rca;
  const hyps = useMemo(
    () => [...(rca?.hypotheses ?? [])].sort((a, b) => a.rank - b.rank),
    [rca],
  );
  const cited = useMemo(
    () => new Set(hyps.flatMap((h) => h.supporting_evidence_ids)),
    [hyps],
  );

  const canResume =
    v &&
    (v.status === "interrupted" || v.status === "failed") &&
    !v.executing_in_process;

  const outcome = v?.result?.outcome;
  const isAwaitingApproval = v?.status === "awaiting_approval";
  const source = incident.data?.evidence_source;
  const readOnly = source === "upload" || source === "connector";
  const suggested = v?.result?.suggested_remediation ?? [];

  // Active selected hypothesis for interactive highlighting
  const activeHypothesis =
    hyps.find((h) => h.rank === selectedHypothesisRank) ?? hyps[0];
  const activeHypSupportingSet = useMemo(
    () => new Set(activeHypothesis?.supporting_evidence_ids ?? []),
    [activeHypothesis],
  );
  const activeHypContradictingSet = useMemo(
    () => new Set(activeHypothesis?.contradicting_evidence_ids ?? []),
    [activeHypothesis],
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
                {incident.data && (
                  <SourceBadge source={incident.data.evidence_source} />
                )}
                <span>
                  Dossier ID:{" "}
                  <code className="font-bold text-text">
                    {v.id.slice(0, 8)}
                  </code>
                </span>
                <span>·</span>
                <span>
                  Model:{" "}
                  <strong className="text-text font-semibold">{v.model}</strong>
                </span>
                <span>·</span>
                <span>Started: {utcTime(v.started_at)}</span>
                {v.incident_id && (
                  <>
                    <span>·</span>
                    <Link
                      className="text-accent hover:underline font-semibold"
                      href={`/incidents/${v.incident_id}`}
                      aria-label="incident view"
                    >
                      incident view
                    </Link>
                  </>
                )}
              </div>
            )
          }
          actions={
            <div className="flex flex-wrap items-center gap-2">
              {incident.data && (
                <SeverityBadge severity={incident.data.severity} />
              )}
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

      {v?.error && (
        <div
          role="alert"
          className="dossier-paper border-l-4 border-l-danger p-4 text-xs font-mono text-danger"
        >
          <div className="flex items-center gap-2 font-bold">
            <span className="stamp-blocked">INVESTIGATION FAILED</span>
            <span>{v.error_class ?? "ExecutionError"}</span>
          </div>
          <p className="mt-1 font-sans text-text-muted leading-relaxed">
            {v.error}
          </p>
        </div>
      )}

      <ErrorNote
        error={
          incident.error ??
          evidence.error ??
          events.error ??
          actions.error ??
          tools.error
        }
      />
      <dl className="incident-facts">
        <div>
          <dt>Affected service</dt>
          <dd>{incident.data?.service ?? "Unavailable"}</dd>
        </div>
        <div>
          <dt>Detected (UTC)</dt>
          <dd>{utcTime(incident.data?.detected_at)}</dd>
        </div>
        <div>
          <dt>Evidence source</dt>
          <dd>
            <SourceBadge source={source} />
          </dd>
        </div>
        <div>
          <dt>Investigation state</dt>
          <dd>{v ? <StatusBadge status={v.status} /> : "Loading…"}</dd>
        </div>
      </dl>

      <section className="case-conclusion" aria-label="Leading conclusion">
        <div>
          <h2>
            {hyps[0]?.title ??
              (v && TERMINAL.has(v.status)
                ? "No primary hypothesis available"
                : "Following the evidence…")}
          </h2>
          <p>
            {outcome?.summary ??
              (isAwaitingApproval
                ? "Analysis is ready. Review the proposed action before simulator execution."
                : rca?.summary
                  ? "Compare the explanations and inspect their source evidence below."
                  : "Findings will appear as the investigation progresses.")}
          </p>
          {rca?.summary && (
            <details className="compact-disclosure mt-3">
              <summary>Full analysis summary</summary>
              <p className="mt-2">{rca.summary}</p>
            </details>
          )}
        </div>
        {outcome ? (
          <div>
            <StatusBadge status={outcome.code} />
            {outcome.escalate && (
              <p className="mt-2 text-warn">
                Escalate
                {outcome.escalate_to
                  ? ` to ${outcome.escalate_to}`
                  : " to an operator"}
              </p>
            )}
          </div>
        ) : isAwaitingApproval && source === "simulator" ? (
          <a
            href="#remediation-section"
            onClick={openRemediation}
            className="action-link"
          >
            Review proposed action ↓
          </a>
        ) : null}
      </section>

      {readOnly && (
        <div className="rounded border border-info/30 bg-info-soft p-3 text-sm text-info">
          <strong>
            Read-only analysis of{" "}
            {source === "connector"
              ? "connected telemetry"
              : "uploaded evidence"}
            .
          </strong>{" "}
          Suggestions only. Nothing executed; external recovery is unverified.
        </div>
      )}
      {isAwaitingApproval && source === "simulator" && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded border border-warn/40 bg-warn-soft p-3 text-sm"
        >
          <strong className="text-warn">OPERATOR ACTION REQUIRED</strong>
          <span>Simulator execution is paused for your review.</span>
          <a
            href="#remediation-section"
            onClick={openRemediation}
            className="text-link"
          >
            Review Proposed Action ↓
          </a>
        </div>
      )}
      {outcome && (
        <details className="compact-disclosure">
          <summary>
            Outcome details ·{" "}
            {outcome.read_only
              ? "read-only · nothing executed"
              : `${outcome.actions_executed} of ${outcome.steps_planned} planned actions executed`}
          </summary>
          <p className="mt-2 text-sm text-text-muted">{outcome.reason}</p>
        </details>
      )}

      {/* Workspace Navigation Tabs */}
      <div
        role="group"
        aria-label="Investigation workspace"
        className="workbench-tabs flex items-center gap-2 border-b border-border text-xs"
      >
        <button
          aria-pressed={activeTab === "analysis"}
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
          aria-pressed={activeTab === "evidence"}
          onClick={() => setActiveTab("evidence")}
          className={`flex items-center gap-2 border-b-2 px-4 py-2.5 font-bold transition-all cursor-pointer ${
            activeTab === "evidence"
              ? "border-accent text-accent"
              : "border-transparent text-muted hover:text-text"
          }`}
        >
          <span>Collected Evidence</span>
          <span className="rounded bg-panel-2 px-1.5 py-0.2 text-[10px]">
            {evidence.data?.length ?? 0}
          </span>
        </button>
        <button
          aria-pressed={activeTab === "traces"}
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
            {/* Mutating Mode: Remediation Plan & Safety Gates */}
            {source === "simulator" && (
              <Card
                id="remediation-section"
                title="Remediation Plan & Safety Gates"
                subtitle="Deterministic validation against invariant safety gates prior to human approval"
              >
                {/* Action Requests & Approval Card */}
                {actions.data?.length ? (
                  <div className="space-y-4">
                    {[...actions.data]
                      .sort(
                        (a, b) =>
                          Number(b.status === "pending") -
                          Number(a.status === "pending"),
                      )
                      .map((a) => (
                        <div
                          key={a.id}
                          data-pending-approval={
                            a.status === "pending" ? "true" : undefined
                          }
                        >
                          <ApprovalCard action={a} />
                        </div>
                      ))}
                  </div>
                ) : v?.result?.rejected_proposals?.length ? null : (
                  <Empty>
                    {actions.isPending
                      ? "Loading action requests…"
                      : actions.error
                        ? "Action requests unavailable."
                        : "No remediation action proposed."}
                  </Empty>
                )}
                <div className="mt-5">
                  <DecisionFlow result={v?.result} actions={actions.data} />
                </div>
                {!!v?.result?.remediation_plan?.length && (
                  <details className="compact-disclosure mb-4">
                    <summary>
                      Plan steps ({v.result.remediation_plan.length})
                    </summary>
                    <div className="mt-3">
                      <h4 className="mb-2 font-mono text-xs font-bold uppercase tracking-wider text-muted">
                        Execution Plan Steps ({v.result.remediation_plan.length}
                        )
                      </h4>
                      <ol
                        className="flex flex-wrap gap-2 font-mono"
                        aria-label="Remediation plan"
                      >
                        {v.result.remediation_plan.map((p) => {
                          const done = v.result?.executions?.find(
                            (x) => x.step === p.step,
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
                                <span className="text-muted text-[11px]">
                                  pending
                                </span>
                              )}
                            </li>
                          );
                        })}
                      </ol>
                    </div>
                  </details>
                )}

                {/* Blocked Proposals Demonstration */}
                {!!v?.result?.rejected_proposals?.length && (
                  <details className="compact-disclosure blocked-proposals">
                    <summary>
                      Blocked proposals ({v.result.rejected_proposals.length}) ·
                      safety gate reasons
                    </summary>
                    <div className="mt-3">
                      <div className="flex items-center gap-2">
                        <span className="text-danger font-bold">🛡</span>
                        <h4 className="text-xs font-bold uppercase tracking-wider text-danger">
                          Proposals Blocked By Deterministic Safety Gates (
                          {v.result.rejected_proposals.length})
                        </h4>
                      </div>
                      <p className="mt-1 text-[11px] text-text-muted font-sans">
                        The model proposed the following state changes, but
                        deterministic safety gates blocked them before any human
                        approval request was issued:
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
                  </details>
                )}
              </Card>
            )}

            <Card title="Root Cause Hypotheses">
              {hyps.length ? (
                <HypothesisComparison
                  hypotheses={hyps}
                  evidence={evidence.data ?? []}
                  selected={activeHypothesis?.rank}
                  onSelect={setSelectedHypothesisRank}
                  onEvidence={(eid) => {
                    setEvidenceGroupFilter("all");
                    setSelectedEvidenceId(eid);
                    setActiveTab("evidence");
                  }}
                />
              ) : (
                <Empty>
                  {v && TERMINAL.has(v.status)
                    ? "No root-cause hypotheses generated. Inspect the evidence and report for gaps."
                    : "Collecting evidence. Hypotheses will appear after analysis."}
                </Empty>
              )}
              {!!rca?.evidence_gaps?.length && (
                <details className="compact-disclosure mt-4">
                  <summary className="text-warn">
                    Evidence gaps ({rca.evidence_gaps.length})
                  </summary>
                  <ul className="mt-2 list-disc space-y-2 pl-4 text-xs text-text-muted">
                    {rca.evidence_gaps.map((gap, i) => (
                      <li key={i}>{gap}</li>
                    ))}
                  </ul>
                </details>
              )}
              {!!rca?.citation_violations?.length && (
                <p className="mt-4 text-xs text-warn">
                  {rca.citation_violations.length} invalid model citations
                  discarded.
                </p>
              )}
            </Card>
            <Card title="Observed signals">
              <MetricComparison
                evidence={evidence.data ?? []}
                onSelect={(eid) => {
                  setEvidenceGroupFilter("all");
                  setSelectedEvidenceId(eid);
                  setActiveTab("evidence");
                }}
              />
            </Card>
            <Card title="Evidence relationships">
              <EvidenceMap
                hypothesis={activeHypothesis}
                evidence={evidence.data ?? []}
                onSelect={(eid) => {
                  setEvidenceGroupFilter("all");
                  setSelectedEvidenceId(eid);
                  setActiveTab("evidence");
                }}
              />
            </Card>

            {/* Read-Only Mode: Advisory Suggestions (Requirement 5) */}
            {readOnly && (
              <Card
                id="remediation-section"
                title="Suggested Remediation (Read-Only Advice)"
                subtitle="Validated against evidence gates as advisory findings. OpsPilot executes no mutating actions in read-only mode."
              >
                <DecisionFlow readOnly result={v?.result} />
                {suggested.length ? (
                  <ol
                    className="space-y-2 font-mono"
                    aria-label="Suggested remediation"
                  >
                    {suggested.map((p) => (
                      <li
                        key={p.step}
                        className="rounded-[4px] border border-border bg-panel-2 p-3 text-xs"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-bold text-muted">
                            {p.step}.
                          </span>
                          <span className="font-semibold text-text">
                            {p.action_type}
                          </span>
                          <Badge>{p.role}</Badge>
                          <Badge tone="purple">suggestion · not executed</Badge>
                        </div>
                        <div className="mt-1 text-[11px] text-text-muted">
                          {Object.entries(p.parameters)
                            .map(([k, val]) => `${k}=${val}`)
                            .join(" · ")}
                        </div>
                        {p.rationale && (
                          <p className="mt-1 text-text-muted font-sans">
                            {p.rationale}
                          </p>
                        )}
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
                      Model proposals not suggested (
                      {v.result.rejected_proposals.length})
                    </h4>
                    <ul className="mt-1.5 space-y-1 text-xs text-text-muted">
                      {v.result.rejected_proposals.map((r, i) => (
                        <li key={i}>
                          <code className="text-text font-bold">
                            {String(r.proposal.action_type)}
                          </code>{" "}
                          — {r.category ? `${r.category}: ` : ""}
                          {r.reason}
                        </li>
                      ))}
                    </ul>
                  </div>
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
            {source === "simulator" && v?.result?.verification && (
              <Card
                title="Simulator recovery verification"
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
                        ? "VERIFIED SIMULATOR RECOVERY"
                        : "RECOVERY NOT VERIFIED"}
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

            <Card title="Evidence composition">
              <Composition
                label="Collected evidence composition"
                items={
                  evidence.data
                    ? Object.entries(
                        evidence.data.reduce<Record<string, number>>(
                          (counts, e) => {
                            const group = evidenceGroup(e);
                            counts[group] = (counts[group] ?? 0) + 1;
                            return counts;
                          },
                          {},
                        ),
                      ).map(([key, count]) => ({ key, label: key, count }))
                    : undefined
                }
                onSelect={(group) => {
                  setEvidenceGroupFilter(group);
                  setActiveTab("evidence");
                }}
              />
              <button
                className="text-link mt-4"
                onClick={() => setActiveTab("evidence")}
              >
                Explore source records →
              </button>
            </Card>
            <Card title="Source chronology">
              <SourceTimeline
                evidence={evidence.data ?? []}
                onSelect={(eid) => {
                  setEvidenceGroupFilter("all");
                  setSelectedEvidenceId(eid);
                  setActiveTab("evidence");
                }}
              />
            </Card>
            <details className="compact-disclosure dossier-paper p-4">
              <summary>
                Workflow chronology · {events.data?.length ?? "—"} events
              </summary>
              <div className="mt-4 space-y-4">
                {v && (
                  <Stepper
                    events={events.data ?? []}
                    current={v.current_step}
                    status={v.status}
                    readOnly={readOnly}
                  />
                )}
                <SynchronizedTimeRibbon
                  startedAt={v?.started_at}
                  events={events.data ?? []}
                  selectedEventId={selectedEventId}
                  onSelectEvent={(eventId) => {
                    setSelectedEventId(eventId);
                    setActiveTab("traces");
                  }}
                />
                <button
                  className="text-link"
                  onClick={() => setActiveTab("traces")}
                >
                  Open full audit →
                </button>
              </div>
            </details>

            <div className="flex items-center justify-between border-t border-border py-4 text-xs text-muted">
              <span>{tools.data?.length ?? "—"} MCP tool calls</span>
              <button
                className="text-link"
                onClick={() => setActiveTab("traces")}
              >
                Inspect transactions →
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: Evidence Explorer */}
      {activeTab === "evidence" && (
        <Card
          title={`Collected Evidence (${evidence.data?.length ?? 0})`}
          subtitle="Persisted operational evidence gathered from telemetry, git changes, dependency graphs, and hybrid RAG"
        >
          <ErrorNote error={evidence.error} />
          {evidence.data?.length ? (
            <EvidenceList
              key={evidenceGroupFilter}
              initialGroup={evidenceGroupFilter}
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
            <Timeline
              events={events.data ?? []}
              selectedEventId={selectedEventId}
            />
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
                        <code className="font-bold text-accent">{t.tool}</code>
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
