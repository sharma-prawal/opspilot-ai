"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import { api } from "@/lib/api";
import { humanize } from "@/lib/format";

const MODES = ["hybrid", "vector", "keyword"] as const;

export default function KnowledgePage() {
  const [query, setQuery] = useState(
    'column "amount" does not exist after migration'
  );
  const [mode, setMode] = useState<(typeof MODES)[number]>("hybrid");
  const search = useMutation({
    mutationFn: () => api.search(query, mode),
  });
  const docs = useQuery({
    queryKey: ["documents"],
    queryFn: api.documents,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Knowledge Base &amp; RAG Search"
        subtitle="Hybrid retrieval combining pgvector cosine distance and PostgreSQL tsvector full-text search, fused with Reciprocal Rank Fusion (RRF k=60)."
      />

      <Card title="Operational Knowledge Retrieval Explorer">
        <form
          className="flex flex-col gap-2.5 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            search.mutate();
          }}
        >
          <label className="sr-only" htmlFor="q">
            Query
          </label>
          <input
            id="q"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            minLength={2}
            maxLength={500}
            placeholder="Search runbooks, postmortems, and architectural docs..."
            className="h-9 min-w-64 flex-1 rounded-lg border border-border bg-panel-2 px-3 text-xs text-text placeholder:text-muted/60 focus:border-accent focus:outline-hidden"
          />
          <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor="mode">
              Mode
            </label>
            <select
              id="mode"
              value={mode}
              onChange={(e) =>
                setMode(e.target.value as (typeof MODES)[number])
              }
              className="h-9 rounded-lg border border-border bg-panel-2 px-3 text-xs font-medium text-text capitalize focus:outline-hidden"
            >
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {m} mode
                </option>
              ))}
            </select>
            <Button
              variant="primary"
              size="md"
              type="submit"
              disabled={search.isPending}
            >
              {search.isPending ? "Searching…" : "Search"}
            </Button>
          </div>
        </form>

        <ErrorNote error={search.error} />

        {search.data && (
          <div className="mt-5 border-t border-border pt-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
              <span>
                <strong className="text-text">{search.data.results.length} results</strong> · {search.data.latency_ms.toFixed(1)} ms
              </span>
              <span className="font-mono text-[11px]">
                trace: <code className="text-accent">{search.data.query_id.slice(0, 8)}</code>
              </span>
            </div>

            <ol className="divide-y divide-border/60">
              {search.data.results.map((r, i) => (
                <li key={r.chunk_id} className="py-3.5 space-y-1.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-accent text-xs">
                        #{i + 1}
                      </span>
                      <span className="font-semibold text-sm text-text">
                        {r.title}
                      </span>
                      <Badge>{humanize(r.doc_type)}</Badge>
                    </div>
                    <div className="flex items-center gap-2 font-mono text-[11px] text-muted">
                      <span>score: {r.score.toFixed(4)}</span>
                      <span>·</span>
                      <span>vec: #{r.vector_rank ?? "—"}</span>
                      <span>·</span>
                      <span>keyw: #{r.keyword_rank ?? "—"}</span>
                    </div>
                  </div>

                  <p className="text-xs text-muted">
                    <span className="font-mono text-accent">{r.source_uri}</span>{" "}
                    › {r.heading_path} · v{r.document_version}
                  </p>

                  <div className="rounded-lg border border-border/60 bg-panel-2/50 p-3 text-xs text-text-muted font-normal leading-relaxed line-clamp-4">
                    {r.snippet}
                  </div>
                </li>
              ))}
            </ol>
          </div>
        )}
      </Card>

      <Card
        title={`Ingested Corpus Documents (${docs.data?.length ?? 0})`}
        subtitle="Operational runbooks, architecture decision records, and past postmortems indexed in PostgreSQL 17"
      >
        {docs.data?.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="border-b border-border text-left uppercase tracking-wider text-[11px] text-muted">
                <tr>
                  <th className="py-2.5 pr-4 font-semibold">Document Title / Path</th>
                  <th className="pr-4 font-semibold">Doc Type</th>
                  <th className="pr-4 font-semibold">Logical Revision</th>
                  <th className="pr-4 font-semibold">Chunk Count</th>
                  <th className="font-semibold">Lifecycle Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {docs.data.map((d) => (
                  <tr key={d.id} className="hover:bg-panel-2/50 transition-colors">
                    <td className="py-2.5 pr-4">
                      <div className="font-medium text-text">{d.title}</div>
                      <div className="font-mono text-[11px] text-muted">
                        {d.source_uri}
                      </div>
                    </td>
                    <td className="pr-4">
                      <Badge>{humanize(d.doc_type)}</Badge>
                    </td>
                    <td className="pr-4 font-mono tabular-nums text-text">
                      v{d.version}
                    </td>
                    <td className="pr-4 font-mono tabular-nums text-text">
                      {d.chunk_count} chunks
                    </td>
                    <td>
                      {d.status === "duplicate" ? (
                        <Badge tone="warn">duplicate</Badge>
                      ) : (
                        <StatusBadge
                          status={d.status === "active" ? "ok" : d.status}
                        />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No documents ingested in knowledge base.</Empty>
        )}
      </Card>
    </div>
  );
}
