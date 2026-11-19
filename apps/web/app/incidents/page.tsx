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
  const q = useQuery({
    queryKey: ["incidents"],
    queryFn: api.incidents,
    refetchInterval: 5000,
  });
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("all");
  const [status, setStatus] = useState("all");
  const shown = (q.data ?? []).filter(
    (i) =>
      (source === "all" || i.evidence_source === source) &&
      (status === "all" || i.status === status) &&
      `${i.reference} ${i.title} ${i.service}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <div className="space-y-6">
      <PageHeader
        title="Incidents"
        subtitle="Find a case. Follow the evidence."
        actions={
          <div className="flex flex-wrap items-center gap-3">
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
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search reference, service or title"
          />
        </label>
        <label>
          Source
          <select
            aria-label="Source"
            value={source}
            onChange={(e) => setSource(e.target.value)}
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
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="all">All states</option>
            {[...new Set((q.data ?? []).map((i) => i.status))].map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </label>
        <span aria-live="polite">
          {q.data ? `${shown.length} / ${q.data.length} cases` : "— cases"}
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
                    }}
                  >
                    Clear filters
                  </button>
                ) : (
                  <SimulateButton scenario="INC-001" />
                )
              }
            >
              {q.data?.length
                ? "No incidents match these filters."
                : "No incidents yet. Simulate a scenario or analyze your own evidence."}
            </Empty>
          )
        )}
      </Card>
    </div>
  );
}
