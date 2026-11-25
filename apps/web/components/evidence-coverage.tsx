"use client";

import type { Evidence, EvidenceSource, QueryProvenance, UploadedDataset } from "@/lib/types";
import { queryStatusLabel } from "@/lib/connectors";
import { utcTime } from "@/lib/format";

export function coverageState(q: QueryProvenance): string {
  if (q.aws?.not_queried) return "Not attempted";
  if (q.status === "error") return "Unavailable";
  if (q.status === "empty") return q.connector === "azure_monitor" ? "No accessible matching records" : "No matching records returned";
  if (q.truncated || q.aws?.partial || q.rejected > 0 || q.issues.length > 0) return "Partial / limited";
  return "Collected";
}

export function EvidenceCoverage({ evidence, dataset, source, gaps = [], pending, error }: {
  evidence?: Evidence[]; dataset?: UploadedDataset; source?: EvidenceSource | null;
  gaps?: string[]; pending?: boolean; error?: boolean;
}) {
  const counts = new Map<string, number>();
  for (const q of dataset?.queries ?? []) counts.set(coverageState(q), (counts.get(coverageState(q)) ?? 0) + 1);
  return <section id="evidence-coverage" tabIndex={-1} className="coverage-summary" aria-label="Evidence coverage and uncertainty">
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
      <h2 className="font-serif-heading text-base font-bold">Evidence coverage</h2>
      <span>{evidence ? `${evidence.length} collected investigation records` : "Collected record count unavailable"}</span>
      {[...counts].map(([state, n]) => <span key={state} className={state === "Collected" ? "text-success" : "text-warn"}>{n} queries · {state}</span>)}
      {!!gaps.length && <span className="text-warn">{gaps.length} reported gaps</span>}
    </div>
    <p className="mt-2 text-xs text-muted">{source === "connector" ? "Frozen telemetry snapshot. Missing deployment/change history stays unknown; empty results do not establish healthy services." : source === "upload" ? "Coverage is limited to the uploaded snapshot. Missing deployment/change history stays unknown." : source === "simulator" ? "Collected observations and post-action simulator verification are separate records." : "Evidence source unavailable. Collection coverage and execution authority cannot be established."}</p>
    <details className="compact-disclosure mt-3">
      <summary>Coverage details and provider provenance</summary>
      <div className="mt-3 space-y-4">
        {pending && <p>Loading snapshot provenance…</p>}
        {error && <p className="text-warn">Snapshot provenance unavailable. Collection completeness cannot be checked.</p>}
        {source !== "simulator" && !pending && !error && !dataset && <p className="text-warn">Snapshot provenance not returned. Coverage remains unknown.</p>}
        {dataset && <p>{Object.entries(dataset.summary.records).map(([kind, count]) => `${count} ${kind}`).join(" · ")} · {dataset.summary.rejected} rejected · {dataset.summary.redactions} redacted. Counts describe the snapshot, not investigation citations.</p>}
        {!!gaps.length && <div><h3 className="font-semibold">Reported evidence gaps</h3><ul className="list-disc pl-5 mt-2 space-y-1">{gaps.map(gap => <li key={gap}>{gap}</li>)}</ul></div>}
        {dataset?.summary.warnings?.map(w => <p key={w} role="note" className="text-warn">{w}</p>)}
        {dataset?.files?.map(f => <div key={f.name}><strong>{f.name}</strong> · {Object.values(f.records).reduce((sum, n) => sum + (n ?? 0), 0)} accepted · {f.rejected} rejected{f.issues.map(w => <p key={w} className="text-warn">{w}</p>)}</div>)}
        <ul className="coverage-queries" aria-label="Provider collection details">{dataset?.queries?.map(q => <li key={q.id}>
          <div className="flex flex-wrap justify-between gap-2"><strong>{q.connector_name} · {q.template_label} · {q.service}</strong><span>{coverageState(q)} · {queryStatusLabel(q)}</span></div>
          {q.connector === "azure_monitor" && q.status === "empty" && <p className="text-warn">No accessible matching records — access/coverage not independently verified.</p>}
          <p className="font-mono mt-1">{q.id} · {utcTime(q.start)} → {utcTime(q.end)} · fetched {utcTime(q.fetched_at)}</p>
          {q.error && <p className="text-warn">{q.error.kind}: {q.error.message}</p>}
          {q.truncated && <p className="text-warn">Truncated collection</p>}
          {q.issues.map(issue => <p key={issue} className="text-warn">{issue}</p>)}
          <details className="compact-disclosure mt-2"><summary>Exact query and provenance</summary><pre className="inspector-payload mt-2">{JSON.stringify(q, null, 2)}</pre></details>
        </li>)}</ul>
        {!dataset?.queries?.length && <p className="text-muted">No provider query ledger recorded for this source.</p>}
        <p className="text-muted">Sampling, correlation and access limits apply where recorded above. Evidence counts alone do not prove complete coverage or causality.</p>
      </div>
    </details>
  </section>;
}
