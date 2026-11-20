"use client";

import { useState } from "react";
import { humanize, utcTime } from "@/lib/format";
import {
  evidenceGroup,
  metricLabel,
  metricValues,
  sourceChronology,
} from "@/lib/visuals";
import { seriesRuns } from "@/lib/connectors";
import type {
  ActionRequest,
  ChartSeries,
  Evidence,
  Hypothesis,
  InvestigationResult,
} from "@/lib/types";
import { Badge, Empty } from "./ui";

export function Composition({
  items,
  label,
  onSelect,
}: {
  items?: { key: string; label: string; count: number }[];
  label: string;
  onSelect?: (key: string) => void;
}) {
  if (!items)
    return <Empty>{label} unavailable. Reconnect to load records.</Empty>;
  const total = items.reduce((n, i) => n + i.count, 0);
  if (!total)
    return (
      <Empty>No records yet. Your first investigation will appear here.</Empty>
    );
  return (
    <figure aria-label={label} className="composition">
      <div className="composition-strip" aria-hidden="true">
        {items.map((i, n) =>
          i.count ? (
            <span
              key={i.key}
              className={`series-${n % 7}`}
              style={{ flex: i.count }}
            />
          ) : null,
        )}
      </div>
      <ul>
        {items.map((i, n) => (
          <li key={i.key}>
            {onSelect ? (
              <button
                onClick={() => onSelect(i.key)}
                className="composition-label"
              >
                <span className={`series-dot series-${n % 7}`} />
                {i.label}
                <strong>{i.count}</strong>
              </button>
            ) : (
              <span className="composition-label">
                <span className={`series-dot series-${n % 7}`} />
                {i.label}
                <strong>{i.count}</strong>
              </span>
            )}
          </li>
        ))}
      </ul>
      <figcaption>{total} records · counts, not signal volume</figcaption>
    </figure>
  );
}

export function MetricComparison({
  evidence,
  onSelect,
}: {
  evidence: Evidence[];
  onSelect: (id: string) => void;
}) {
  const metrics = evidence.filter(
    (e) => metricValues(e).length > 0 && evidenceGroup(e) === "Metrics",
  );
  return (
    <div className="metric-comparison">
      {!metrics.length ? (
        <Empty>
          No numeric metric summaries collected. Inspect available logs, changes
          and runbooks.
        </Empty>
      ) : (
        metrics.map((e) => {
          const values = metricValues(e);
          const low = Math.min(0, ...values.map((v) => v.value));
          const high = Math.max(0, ...values.map((v) => v.value));
          const span = high - low || 1;
          const unit = typeof e.data.unit === "string" ? e.data.unit : "";
          return (
            <figure
              key={e.evidence_id}
              className="metric-row"
              aria-label={`${e.data.metric ?? e.kind}, ${e.service ?? "service unknown"}`}
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <button
                  onClick={() => onSelect(e.evidence_id)}
                  className="text-left text-sm font-semibold hover:underline"
                >
                  {String(e.data.metric ?? "Metric summary")}
                </button>
                <span className="font-mono text-xs text-muted">
                  {e.service ?? "Service unknown"}
                </span>
              </div>
              <div className="metric-bars">
                {values.map((v) => (
                  <div key={v.label} className="metric-bar-row">
                    <span>{v.label}</span>
                    <span className="metric-track">
                      <span
                        style={{
                          left: `${((Math.min(0, v.value) - low) / span) * 100}%`,
                          width: `${(Math.abs(v.value) / span) * 100}%`,
                        }}
                        className={
                          v.label === "Baseline"
                            ? "metric-baseline"
                            : "metric-observed"
                        }
                      />
                    </span>
                    <strong>{metricLabel(v.value, unit)}</strong>
                  </div>
                ))}
              </div>
              <figcaption>
                {unit ? "" : "Unit unavailable · "}Independent scale:{" "}
                {metricLabel(low, unit)} – {metricLabel(high, unit)} ·{" "}
                {e.evidence_id}
                {e.observed_at
                  ? ` · ${utcTime(e.observed_at)}`
                  : " · Time unavailable"}
              </figcaption>
            </figure>
          );
        })
      )}
      <p className="text-xs text-muted">
        Persisted summaries · baseline, extreme and current are not a time
        series.
      </p>
    </div>
  );
}

export function SourceTimeline({
  evidence,
  onSelect,
}: {
  evidence: Evidence[];
  onSelect: (id: string) => void;
}) {
  const rows = sourceChronology(evidence);
  return (
    <div>
      <ol className="source-timeline" aria-label="Source evidence chronology">
        {rows.map((e) => (
          <li key={e.evidence_id}>
            <button onClick={() => onSelect(e.evidence_id)}>
              <time title={e.observed_at!} dateTime={e.observed_at!}>
                {utcTime(e.observed_at)}
              </time>
              <span className="timeline-pin" aria-hidden="true" />
              <span>
                <strong>{evidenceGroup(e)}</strong> ·{" "}
                {e.service ?? "Service unknown"}
                <small>{e.summary}</small>
                <code>{e.evidence_id}</code>
              </span>
            </button>
          </li>
        ))}
      </ol>
      {!rows.length && (
        <Empty>
          No source timestamps collected. Workflow timestamps are available in
          the audit tab.
        </Empty>
      )}
      <p className="mt-3 text-xs text-muted">
        Source observation times · proximity does not establish causality.{" "}
        {evidence.length - rows.length} records without a valid source
        timestamp.
      </p>
    </div>
  );
}

export function HypothesisComparison({
  hypotheses,
  evidence,
  selected,
  onSelect,
  onEvidence,
}: {
  hypotheses: Hypothesis[];
  evidence: Evidence[];
  selected?: number;
  onSelect: (rank: number) => void;
  onEvidence: (id: string) => void;
}) {
  const existing = new Set(evidence.map((e) => e.evidence_id));
  const sorted = [...hypotheses].sort((a, b) => a.rank - b.rank);
  return (
    <div className="hypothesis-comparison">
      <p className="mb-4 text-xs text-muted">
        Model-estimated confidence, not a calibrated statistical probability
        (uncalibrated). Select a hypothesis to inspect its evidence.
      </p>
      <ol>
        {sorted.map((h) => {
          const supporting = [...new Set(h.supporting_evidence_ids)].filter(
            (id) => existing.has(id),
          );
          const contradicting = [
            ...new Set(h.contradicting_evidence_ids),
          ].filter((id) => existing.has(id));
          return (
            <li
              key={h.rank}
              className={h.rank === selected ? "hypothesis-selected" : ""}
            >
              <button
                className="hypothesis-pick"
                onClick={() => onSelect(h.rank)}
                aria-pressed={h.rank === selected}
              >
                <span className="hypothesis-rank">{h.rank}</span>
                <span>
                  <strong>{h.title}</strong>
                  <small>{humanize(h.category)}</small>
                </span>
                <span
                  aria-label={`confidence ${Math.round(h.confidence * 100)} percent (model-estimated, uncalibrated)`}
                  className="hypothesis-confidence"
                >
                  {Number.isFinite(h.confidence)
                    ? `${Math.round(h.confidence * 100)}%`
                    : "Unknown"}
                  <small>model estimate</small>
                </span>
              </button>
              <div className="hypothesis-links">
                <span className="text-success">
                  {supporting.length} supporting
                </span>
                <span className="text-danger">
                  {contradicting.length} contradicting
                </span>
                {!!h.evidence_warnings?.length && (
                  <span className="text-warn">unsupported claim</span>
                )}
              </div>
              {h.rank === selected && (
                <div className="hypothesis-detail">
                  <p>{h.description}</p>
                  {h.evidence_warnings?.map((w) => (
                    <p key={w} role="note" className="mt-1 text-xs text-warn">
                      ⚠ {w}
                    </p>
                  ))}
                  <div className="flex flex-wrap gap-2">
                    {supporting.map((id) => (
                      <button
                        key={`support-${id}`}
                        onClick={() => onEvidence(id)}
                        className="evidence-chip evidence-support"
                      >
                        {id} · supports
                      </button>
                    ))}
                    {contradicting.map((id) => (
                      <button
                        key={`against-${id}`}
                        onClick={() => onEvidence(id)}
                        className="evidence-chip evidence-against"
                      >
                        {id} · contradicts
                      </button>
                    ))}
                  </div>
                  {!supporting.length && !contradicting.length && (
                    <p>No persisted evidence links for this hypothesis.</p>
                  )}
                  {[
                    ...h.supporting_evidence_ids,
                    ...h.contradicting_evidence_ids,
                  ].some((id) => !existing.has(id)) && (
                    <p className="text-warn">
                      Some referenced evidence is unavailable. Inspect the
                      report for citation validation.
                    </p>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function EvidenceMap({
  hypothesis,
  evidence,
  onSelect,
}: {
  hypothesis?: Hypothesis;
  evidence: Evidence[];
  onSelect: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!hypothesis)
    return (
      <Empty>Evidence associations appear after hypothesis generation.</Empty>
    );
  const linked = evidence.filter(
    (e) =>
      hypothesis.supporting_evidence_ids.includes(e.evidence_id) ||
      hypothesis.contradicting_evidence_ids.includes(e.evidence_id),
  );
  const rows = expanded ? linked : linked.slice(0, 5);
  const dependencies = evidence.flatMap((e) => {
    const edge = e.data.edge;
    if (
      e.kind !== "dependency" ||
      !edge ||
      typeof edge !== "object" ||
      Array.isArray(edge)
    )
      return [];
    const d = edge as Record<string, unknown>;
    return typeof d.service === "string" && typeof d.depends_on === "string"
      ? [
          {
            id: e.evidence_id,
            from: d.service,
            to: d.depends_on,
            kind: typeof d.kind === "string" ? d.kind : "dependency",
          },
        ]
      : [];
  });
  const height = Math.max(130, rows.length * 84 + 16);
  return (
    <div>
      {dependencies.length > 0 && (
        <div
          className="dependency-links"
          aria-label="Observed service relationships"
        >
          {dependencies.map((d) => (
            <button key={d.id} onClick={() => onSelect(d.id)}>
              <strong>{d.from}</strong>
              <span>→ {humanize(d.kind)} →</span>
              <strong>{d.to}</strong>
              <small>
                {d.id} · observed dependency, not a causal conclusion
              </small>
            </button>
          ))}
        </div>
      )}
      <p className="mb-4 text-xs text-muted">
        Model evidence associations · lines indicate support or contradiction,
        not causal proof.
      </p>
      {linked.length ? (
        <div
          className="evidence-map-scroll"
          tabIndex={0}
          aria-label="Scrollable hypothesis evidence map"
        >
          <div className="evidence-map" style={{ height }}>
            <svg
              viewBox={`0 0 620 ${height}`}
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              {rows.map((e, i) => (
                <path
                  key={e.evidence_id}
                  d={`M180 ${height / 2} C270 ${height / 2}, 270 ${i * 84 + 42}, 340 ${i * 84 + 42}`}
                  className={
                    hypothesis.contradicting_evidence_ids.includes(
                      e.evidence_id,
                    )
                      ? "edge-contradicts"
                      : "edge-supports"
                  }
                />
              ))}
            </svg>
            <div className="map-hypothesis" style={{ top: height / 2 - 42 }}>
              <span>Hypothesis {hypothesis.rank}</span>
              <strong>{hypothesis.title}</strong>
            </div>
            {rows.map((e, i) => (
              <button
                key={e.evidence_id}
                className="map-evidence"
                style={{ top: i * 84 + 10 }}
                onClick={() => onSelect(e.evidence_id)}
              >
                <span>
                  {evidenceGroup(e)} ·{" "}
                  {hypothesis.contradicting_evidence_ids.includes(e.evidence_id)
                    ? "Contradicts"
                    : "Supports"}
                </span>
                <strong>{e.service ?? "Service unknown"}</strong>
                <code>{e.evidence_id}</code>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <Empty>No persisted evidence associations for this hypothesis.</Empty>
      )}
      {linked.length > 0 && (
        <p className="evidence-map-hint">
          Scroll horizontally to inspect linked evidence. Each node opens its
          source record.
        </p>
      )}
      {linked.length > 5 && (
        <button
          className="text-link mt-3"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Show fewer links" : `Show all ${linked.length} links`}
        </button>
      )}
    </div>
  );
}

export function DecisionFlow({
  result,
  actions = [],
  readOnly = false,
}: {
  result?: InvestigationResult | null;
  actions?: ActionRequest[];
  readOnly?: boolean;
}) {
  if (readOnly)
    return (
      <div className="decision-readonly">
        <Badge tone="info">Read-only analysis</Badge>
        <span>Evidence → hypotheses → advisory report</span>
        <strong>Nothing executed</strong>
      </div>
    );
  const plan = result?.remediation_plan ?? [];
  const execution = result?.executions ?? [];
  const stages = [
    {
      label: "Proposed",
      detail: plan.length
        ? `${plan.length} plan steps`
        : result?.rejected_proposals?.length
          ? "Blocked proposals only"
          : "No plan",
    },
    {
      label: "Safety checked",
      detail: plan.length
        ? "Plan admitted"
        : result?.rejected_proposals?.length
          ? "Blocked"
          : "No admitted plan",
    },
    {
      label: "Approval",
      detail: actions.some((a) => a.status === "pending")
        ? "Pending review"
        : actions.some((a) => a.status === "approved")
          ? "Approved action recorded"
          : actions.some((a) => a.status === "rejected")
            ? "Rejected"
            : "No approval recorded",
    },
    {
      label: "Execution",
      detail: execution.length
        ? `${execution.length} simulator results`
        : actions.some((a) => a.executed_at)
          ? "Simulator execution recorded"
          : "Not executed",
    },
    {
      label: "Verification",
      detail: result?.verification
        ? result.verification.recovered
          ? "Simulator recovery verified"
          : "Recovery not verified"
        : "Not verified",
    },
  ];
  return (
    <ol className="decision-flow" aria-label="Remediation decision sequence">
      {stages.map((s) => (
        <li key={s.label}>
          <span>{s.label}</span>
          <strong>{s.detail}</strong>
        </li>
      ))}
    </ol>
  );
}

/**
 * v0.9: metric points exactly as the provider returned them (preview of a connected snapshot). Native SVG, one
 * independent scale per series; a missing interval is drawn as a break, never bridged or filled in.
 */
export function SeriesChart({ series }: { series: ChartSeries }) {
  const runs = seriesRuns(series);
  const pts = runs.flat();
  const label = `${series.metric}, ${series.service}`;
  if (!pts.length)
    return (
      <figure className="metric-row" aria-label={label}>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-sm font-semibold">{series.metric}</span>
          <span className="font-mono text-xs text-muted">{series.service}</span>
        </div>
        <p className="text-xs text-muted">
          {series.count} point(s) · not charted: {series.omitted ?? "no finite values"}.
        </p>
      </figure>
    );
  const W = 320, H = 72, pad = 4;
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
  const lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]));
  const x = (t: number) => pad + ((t - t0) / (t1 - t0 || 1)) * (W - 2 * pad);
  const y = (v: number) => H - pad - ((v - lo) / (hi - lo || 1)) * (H - 2 * pad);
  const gaps = runs.length - 1;
  return (
    <figure className="metric-row" aria-label={label}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-semibold">{series.metric}</span>
        <span className="font-mono text-xs text-muted">{series.service}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-[72px] w-full" role="img"
        aria-label={`${label}: ${series.count} returned points from ${metricLabel(lo, series.unit)} to ${metricLabel(hi, series.unit)}`}>
        <line x1={pad} x2={W - pad} y1={H - pad} y2={H - pad} stroke="var(--border)" strokeWidth={1} />
        {runs.map((run, i) =>
          run.length === 1 ? (
            <circle key={i} cx={x(run[0][0])} cy={y(run[0][1])} r={1.6} fill="var(--accent)" />
          ) : (
            <polyline key={i} fill="none" stroke="var(--accent)" strokeWidth={1.5} strokeLinejoin="round"
              points={run.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} />
          ),
        )}
      </svg>
      <figcaption>
        {series.count} returned point(s){series.step_seconds ? ` · ${series.step_seconds} s rollups` : ""} ·{" "}
        {metricLabel(lo, series.unit)} – {metricLabel(hi, series.unit)}
        {series.unit ? "" : " · unit unavailable"} · {utcTime(new Date(t0).toISOString())} →{" "}
        {utcTime(new Date(t1).toISOString())}
        {gaps > 0 ? ` · ${gaps} gap(s) with no returned value, not filled in` : ""} ·{" "}
        <span className="font-mono">{series.query}</span>
      </figcaption>
    </figure>
  );
}
