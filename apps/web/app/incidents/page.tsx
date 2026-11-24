"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { SimulateButton } from "@/components/simulate-button";
import { SourceBadge } from "@/components/source-badge";
import {
  Badge,
  Card,
  Empty,
  ErrorNote,
  PageHeader,
  SeverityBadge,
  StatusBadge,
} from "@/components/ui";
import { api } from "@/lib/api";
import { humanize, utcTime } from "@/lib/format";

export default function IncidentsPage() {
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("all");
  const [status, setStatus] = useState("all");
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const q = useQuery({
    queryKey: ["incidents", "search", search, source, status, offset],
    queryFn: () => api.searchIncidents({ q: search, source, status, limit, offset }),
    refetchInterval: 5000,
  });
  const shown = q.data?.items ?? [];
  return (
    <div className="space-y-6">
      <PageHeader
        title="Incidents"
        subtitle="Find a case. Follow the evidence."
        actions={
          <div className="flex min-w-0 max-w-full flex-wrap items-center gap-3">
            <SimulateButton picker />
            <Link className="action-link" href="/incidents/new">
              Analyze data →
            </Link>
          </div>
        }
      />
      <ErrorNote error={q.error} />
      <div className="filter-toolbar">
        <label className="filter-search">
          <span className="sr-only">Search incidents</span>
          <input
            type="search"
            maxLength={200}
            value={search}
            onChange={(e) => { setSearch(e.target.value); setOffset(0); }}
            placeholder="Search reference, service or title"
          />
        </label>
        <label>
          Source
          <select
            aria-label="Source"
            value={source}
            onChange={(e) => { setSource(e.target.value); setOffset(0); }}
          >
            <option value="all">All sources</option>
            <option value="simulator">Simulator</option>
            <option value="upload">Uploaded files</option>
            <option value="connector">Connected telemetry</option>
          </select>
        </label>
        <label>
          State
          <select
            aria-label="State"
            value={status}
            onChange={(e) => { setStatus(e.target.value); setOffset(0); }}
          >
            <option value="all">All states</option>
            {["open", "investigating", "awaiting_approval", "mitigated", "resolved"].map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </label>
        <span aria-live="polite">
          {q.data ? `${q.data.total} matching cases · complete history` : "— cases"}
        </span>
      </div>
      <Card title="Incident roster">
        {q.isLoading ? (
          <Empty>Loading incidents…</Empty>
        ) : shown.length ? (
          <div
            className="overflow-x-auto"
            tabIndex={0}
            aria-label="Scrollable incident roster"
          >
            <table className="incident-roster">
              <thead>
                <tr>
                  <th scope="col">Incident / service</th>
                  <th scope="col">Source</th>
                  <th scope="col">Severity</th>
                  <th scope="col">Detected (UTC)</th>
                  <th scope="col">State</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((i) => (
                  <tr key={i.id}>
                    <td>
                      <Link href={`/incidents/${i.id}`}>
                        <code>{i.reference}</code>
                        <strong>{i.title}</strong>
                      </Link>
                      <small>{i.service}</small>
                    </td>
                    <td>
                      <SourceBadge source={i.evidence_source} />
                    </td>
                    <td>
                      <SeverityBadge severity={i.severity} />
                    </td>
                    <td>
                      <time dateTime={i.detected_at}>
                        {utcTime(i.detected_at)}
                      </time>
                    </td>
                    <td>
                      {i.evidence_source === "simulator" ? (
                        <StatusBadge status={i.status} />
                      ) : (
                        <Badge>
                          External: {humanize(i.status)} · unverified
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          !q.error && (
            <Empty
              action={
                search || source !== "all" || status !== "all" ? (
                  <button
                    className="text-link"
                    onClick={() => {
                      setSearch("");
                      setSource("all");
                      setStatus("all");
                      setOffset(0);
                    }}
                  >
                    Clear filters
                  </button>
                ) : (
                  <SimulateButton scenario="INC-001" />
                )
              }
            >
              {search || source !== "all" || status !== "all" || offset
                ? "No incidents match these filters."
                : "No incidents yet. Simulate a scenario or analyze your own evidence."}
            </Empty>
          )
        )}
      </Card>
      <div className="flex flex-wrap items-center justify-between gap-3" aria-label="Incident pagination">
        <button className="action-link" disabled={!offset || q.isFetching}
          onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
        <span aria-live="polite">{q.data ? (shown.length ? `${offset + 1}–${offset + shown.length} of ${q.data.total}` : `0 on this page · ${q.data.total} matching cases`) : "Loading page…"}</span>
        <button className="action-link" disabled={!q.data || offset + limit >= q.data.total || offset + limit > 100000 || q.isFetching}
          onClick={() => setOffset(offset + limit)}>Next</button>
      </div>
    </div>
  );
}
