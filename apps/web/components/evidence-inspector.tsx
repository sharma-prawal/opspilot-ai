"use client";

import { useEffect, useRef } from "react";
import type { Evidence, Hypothesis } from "@/lib/types";
import { humanize, utcTime } from "@/lib/format";
import { Badge } from "./ui";
import { SourceTimeline } from "./visuals";

/** Preserve source references verbatim; these are not evidence IDs. */
export function evidenceSourceRef(e: Evidence): string | null {
  const d = e.data as { attributes?: { source_ref?: unknown }; sources?: unknown; metadata?: { source_ref?: unknown } };
  const value = d?.attributes?.source_ref ?? d?.sources ?? d?.metadata?.source_ref;
  return value == null ? null : typeof value === "string" ? value : JSON.stringify(value);
}

export function EvidenceInspector({ evidence, selectedId, hypothesis, pending, error, onDismiss, onSelect }: {
  evidence: Evidence[]; selectedId: string | null; hypothesis?: Hypothesis;
  pending?: boolean; error?: boolean; onDismiss: () => void; onSelect?: (id: string) => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (selectedId) {
      heading.current?.focus({ preventScroll: true });
      heading.current?.scrollIntoView?.({ block: "nearest" });
    }
  }, [selectedId]);
  const record = evidence.find(e => e.evidence_id === selectedId);
  const supports = !!selectedId && hypothesis?.supporting_evidence_ids.includes(selectedId);
  const contradicts = !!selectedId && hypothesis?.contradicting_evidence_ids.includes(selectedId);
  const relation = supports && contradicts ? "Supports and contradicts" : supports ? "Supports" : contradicts ? "Contradicts" : "No relationship recorded to";
  const d = record?.data;
  const recordedTimes = [
    ["Event timestamp (UTC)", d?.ts ?? d?.timestamp],
    ["First recorded occurrence (UTC)", d?.first_seen],
    ["Last recorded occurrence (UTC)", d?.last_seen],
    ["Metric anomaly onset (UTC)", d?.onset],
    ["Deployment started (UTC)", d?.started_at],
    ["Deployment finished (UTC)", d?.finished_at],
    ["Configuration changed (UTC)", d?.changed_at],
  ].filter((row): row is [string, string] => typeof row[1] === "string");
  const message = d?.message ?? d?.msg ?? d?.sample;
  return (
    <section id="evidence-inspector" className="evidence-inspector" aria-label="Contextual evidence inspector"
      onKeyDown={event => { if (event.key === "Escape" && selectedId) { event.preventDefault(); event.stopPropagation(); onDismiss(); } }}>
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 ref={heading} tabIndex={-1} className="font-serif-heading text-lg font-bold">Evidence inspector</h3>
        {selectedId && <button className="text-link inspector-dismiss" onClick={onDismiss}>Close inspector</button>}
      </header>
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {selectedId ? `${selectedId} selected. ${record ? `${relation} hypothesis ${hypothesis?.rank ?? "unavailable"}.` : pending ? "Loading evidence." : "Evidence unavailable."}` : "Select evidence to inspect its source."}
      </p>
      {!selectedId ? <div className="mt-4 space-y-5"><p className="text-sm text-muted">Select a supporting or contradicting citation, a source observation or a collected record. Its details appear here alongside the hypothesis.</p>
        {onSelect && <div><h4 className="font-semibold text-sm mb-3">Source chronology</h4><SourceTimeline evidence={evidence} onSelect={onSelect} /></div>}
      </div>
        : !record ? <div className="mt-4 space-y-2 text-sm"><code>{selectedId}</code><p>{pending ? "Loading evidence…" : error ? "Evidence collection unavailable. This citation cannot be checked." : "Evidence unavailable. No corresponding record was returned for this exact citation."}</p></div>
        : <div className="mt-4 space-y-4">
          <div className="flex flex-wrap gap-2"><Badge tone={contradicts ? "danger" : supports ? "success" : "neutral"}>{relation} hypothesis {hypothesis?.rank ?? "unavailable"}</Badge><Badge>{humanize(record.kind)}</Badge></div>
          <p className="text-sm leading-relaxed">{record.summary}</p>
          <dl className="inspector-facts">
            <div><dt>Evidence ID</dt><dd><code>{record.evidence_id}</code></dd></div>
            <div><dt>Source / collector</dt><dd>{record.source_tool} / {record.collected_by}</dd></div>
            <div><dt>Source reference</dt><dd>{evidenceSourceRef(record) ?? record.citation?.source_uri ?? "Not recorded"}</dd></div>
            {typeof d?.id === "string" && <div><dt>Source record ID</dt><dd><code>{d.id}</code></dd></div>}
            <div><dt>Service / resource</dt><dd>{record.service ?? "Not recorded"}</dd></div>
            {recordedTimes.length ? recordedTimes.map(([label, time]) => <div key={label}><dt>{label}</dt><dd>{utcTime(time) === "—" ? "Unavailable (invalid recorded timestamp)" : utcTime(time)}</dd></div>) : <div><dt>Event timestamp (UTC)</dt><dd>Not recorded in this evidence item</dd></div>}
            <div><dt>Evidence observation (UTC)</dt><dd>{utcTime(record.observed_at) === "—" ? "Unavailable" : utcTime(record.observed_at)}</dd></div>
          </dl>
          {d?.search_truncated === true && <p role="note" className="claim-notes">Log search truncated. Earlier occurrences may exist; recorded first occurrence is limited to returned records.</p>}
          {typeof message === "string" && <div><h4 className="text-xs font-semibold text-muted">Recorded message / sample</h4><pre className="inspector-payload mt-2">{message}</pre></div>}
          <p role="note" className="text-xs leading-relaxed text-muted">Relationships are model-selected associations, not independently proven causes. Observation time is not necessarily the event or latest sample time. <a className="text-link" href="#evidence-coverage">Inspect coverage and provenance limits</a>.</p>
          <details className="compact-disclosure"><summary>Raw evidence and citation details</summary><pre className="inspector-payload mt-3">{JSON.stringify({ data: record.data, citation: record.citation, relevance: record.relevance }, null, 2)}</pre></details>
        </div>}
    </section>
  );
}

export function HypothesisReview({ hypotheses, evidence, selectedRank, selectedEvidenceId, onHypothesis, onEvidence }: {
  hypotheses: Hypothesis[]; evidence: Evidence[]; selectedRank?: number; selectedEvidenceId: string | null;
  onHypothesis: (rank: number) => void; onEvidence: (id: string) => void;
}) {
  const accessibleIds = new Set(evidence.map(record => record.evidence_id));
  return <section aria-label="Hypotheses and citations" className="hypothesis-review">
    <h2 className="font-serif-heading text-lg font-bold">Leading hypothesis &amp; evidence</h2>
    <p className="mt-1 mb-4 text-xs text-muted">Model-assigned confidence is uncalibrated. Associations do not establish causality.</p>
    {!hypotheses.length && <p className="text-sm text-muted">No hypothesis available yet. Inspect collected evidence and the report for gaps.</p>}
    <ol className="space-y-3">{hypotheses.map((h, index) => {
      const selected = h.rank === selectedRank;
      const support = [...new Set(h.supporting_evidence_ids)];
      const against = [...new Set(h.contradicting_evidence_ids)];
      const accessibleSupports = support.filter(id => accessibleIds.has(id)).length;
      const accessibleContradictions = against.filter(id => accessibleIds.has(id)).length;
      return <li key={h.rank} className={selected ? "review-hypothesis is-selected" : "review-hypothesis"}>
        <button className="review-hypothesis-pick" aria-pressed={selected} onClick={() => onHypothesis(h.rank)}>
          <span className="text-xs text-muted">{index === 0 ? "Leading explanation" : `Alternative · rank ${h.rank}`} · <span aria-label={`confidence ${Math.round(h.confidence * 100)} percent (model-assigned, uncalibrated)`}>{Number.isFinite(h.confidence) ? `${Math.round(h.confidence * 100)}%` : "Unknown confidence"} · uncalibrated</span></span>
          <strong className="block mt-1 text-base leading-snug">{h.title}</strong>
          <span className="block mt-2 text-xs text-muted">{support.length} cited support{support.length === 1 ? "" : "s"} ({accessibleSupports} accessible · {support.length - accessibleSupports} unavailable) · {against.length} cited contradiction{against.length === 1 ? "" : "s"} ({accessibleContradictions} accessible · {against.length - accessibleContradictions} unavailable)</span>
        </button>
        {selected && <div className="px-3 pb-3 space-y-3">
          <p className="text-sm leading-relaxed">{h.description}</p>
          {!!h.evidence_warnings?.length && <div role="note" className="claim-notes"><strong>Claim limitations</strong><ul>{h.evidence_warnings.map(w => <li key={w}>{w}</li>)}</ul></div>}
          <div className="space-y-2">{[["supports", support], ["contradicts", against]].map(([relationship, ids]) => (ids as string[]).map(id => {
            const e = evidence.find(item => item.evidence_id === id);
            return <button key={`${relationship}-${id}`} className={`citation-record ${selectedEvidenceId === id ? "is-selected" : ""}`} aria-pressed={selectedEvidenceId === id} aria-controls="evidence-inspector" onClick={() => onEvidence(id)}>
              <span className={relationship === "supports" ? "text-success" : "text-danger"}>{relationship as string}</span><code>{id}</code>
              <span>{e?.summary ?? "Corresponding evidence unavailable"}</span>
            </button>;
          }))}</div>
          {!support.length && !against.length && <p className="text-xs text-muted">No evidence relationships recorded.</p>}
        </div>}
      </li>;
    })}</ol>
  </section>;
}
