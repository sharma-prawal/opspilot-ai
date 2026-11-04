"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { humanize } from "@/lib/format";

const MODES = ["hybrid", "vector", "keyword"] as const;

export default function KnowledgePage() {
  const [query, setQuery] = useState("column \"amount\" does not exist after migration");
  const [mode, setMode] = useState<(typeof MODES)[number]>("hybrid");
  const search = useMutation({ mutationFn: () => api.search(query, mode) });
  const docs = useQuery({ queryKey: ["documents"], queryFn: api.documents });
  return (
    <>
      <PageHeader title="Knowledge search" subtitle="Hybrid retrieval: pgvector cosine + PostgreSQL full-text, fused with reciprocal rank fusion." />
      <Card>
        <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); search.mutate(); }}>
          <label className="sr-only" htmlFor="q">Query</label>
          <input id="q" value={query} onChange={(e) => setQuery(e.target.value)} minLength={2} maxLength={500}
            className="h-8 min-w-64 flex-1 rounded-md border border-border bg-panel px-2 text-sm" />
          <label className="sr-only" htmlFor="mode">Mode</label>
          <select id="mode" value={mode} onChange={(e) => setMode(e.target.value as (typeof MODES)[number])}
            className="h-8 rounded-md border border-border bg-panel px-2 text-sm">
            {MODES.map((m) => <option key={m}>{m}</option>)}
          </select>
          <Button variant="primary" type="submit" disabled={search.isPending}>Search</Button>
        </form>
        <ErrorNote error={search.error} />
        {search.data && (
          <div className="mt-4">
            <p className="mb-2 text-xs text-muted">{search.data.results.length} results · {search.data.latency_ms.toFixed(1)} ms · trace <code className="font-mono">{search.data.query_id.slice(0, 8)}</code></p>
            <ol className="divide-y divide-border">
              {search.data.results.map((r, i) => (
                <li key={r.chunk_id} className="py-2.5">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-semibold tabular-nums">#{i + 1}</span>
                    <span className="font-medium text-sm">{r.title}</span>
                    <Badge>{humanize(r.doc_type)}</Badge>
                    <span className="text-muted">score {r.score.toFixed(4)} · vector #{r.vector_rank ?? "—"} · keyword #{r.keyword_rank ?? "—"}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-muted"><span className="font-mono">{r.source_uri}</span> › {r.heading_path} · v{r.document_version}</p>
                  <p className="mt-1 line-clamp-3 text-sm">{r.snippet}</p>
                </li>
              ))}
            </ol>
          </div>
        )}
      </Card>
      <Card title={`Documents (${docs.data?.length ?? 0})`} className="mt-4">
        {docs.data?.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted"><tr>
                <th className="py-2 pr-3 font-medium">Source</th><th className="pr-3 font-medium">Type</th>
                <th className="pr-3 font-medium">Version</th><th className="pr-3 font-medium">Chunks</th><th className="font-medium">Status</th></tr></thead>
              <tbody className="divide-y divide-border">
                {docs.data.map((d) => (
                  <tr key={d.id}>
                    <td className="py-1.5 pr-3"><div>{d.title}</div><div className="font-mono text-xs text-muted">{d.source_uri}</div></td>
                    <td className="pr-3"><Badge>{humanize(d.doc_type)}</Badge></td>
                    <td className="pr-3 tabular-nums">v{d.version}</td>
                    <td className="pr-3 tabular-nums">{d.chunk_count}</td>
                    <td>{d.status === "duplicate" ? <Badge tone="warn">duplicate</Badge> : <StatusBadge status={d.status === "active" ? "ok" : d.status} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>No documents ingested.</Empty>}
      </Card>
    </>
  );
}
