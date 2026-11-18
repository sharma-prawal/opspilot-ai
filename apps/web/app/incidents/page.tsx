"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { SimulateButton } from "@/components/simulate-button";
import { SourceBadge } from "@/components/source-badge";
import {
  Button,
  Card,
  Empty,
  ErrorNote,
  PageHeader,
  SeverityBadge,
  StatusBadge,
} from "@/components/ui";
import { api } from "@/lib/api";
import { utcTime } from "@/lib/format";

export default function IncidentsPage() {
  const q = useQuery({
    queryKey: ["incidents"],
    queryFn: api.incidents,
    refetchInterval: 5000,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Incidents"
        subtitle="Simulated demo incidents and incidents created from your own uploaded files."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <SimulateButton picker />
            <Link href="/incidents/new">
              <Button variant="secondary" size="md">Analyze your files</Button>
            </Link>
          </div>
        }
      />
      <ErrorNote error={q.error} />
      <Card title={`All Recorded Incidents (${q.data?.length ?? 0})`}>
        {q.data?.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="border-b border-border text-left uppercase tracking-wider text-[11px] text-muted">
                <tr>
                  <th className="py-2.5 pr-4 font-semibold">Reference</th>
                  <th className="pr-4 font-semibold">Title</th>
                  <th className="pr-4 font-semibold">Service</th>
                  <th className="pr-4 font-semibold">Evidence</th>
                  <th className="pr-4 font-semibold">Severity</th>
                  <th className="pr-4 font-semibold">Detected (UTC)</th>
                  <th className="font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {q.data.map((i) => (
                  <tr
                    key={i.id}
                    className="hover:bg-panel-2/60 transition-colors"
                  >
                    <td className="py-3 pr-4 font-mono font-semibold text-accent">
                      <Link
                        className="hover:underline"
                        href={`/incidents/${i.id}`}
                      >
                        {i.reference}
                      </Link>
                    </td>
                    <td className="pr-4 font-medium text-text">{i.title}</td>
                    <td className="pr-4 font-mono text-muted">{i.service}</td>
                    <td className="pr-4">
                      <SourceBadge source={i.evidence_source} />
                    </td>
                    <td className="pr-4">
                      <SeverityBadge severity={i.severity} />
                    </td>
                    <td className="pr-4 tabular-nums text-muted">
                      {utcTime(i.detected_at)}
                    </td>
                    <td>
                      <StatusBadge status={i.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : q.isLoading ? (
          <Empty>Loading incidents...</Empty>
        ) : (
          <Empty
            action={<SimulateButton scenario="INC-001" />}
          >
            No incidents recorded yet. Simulate a demo incident, or analyze your own files.
          </Empty>
        )}
      </Card>
    </div>
  );
}
