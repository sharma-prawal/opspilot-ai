"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { SimulateButton } from "@/components/simulate-button";
import { Badge, Card, Empty, ErrorNote, PageHeader, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { utcTime } from "@/lib/format";

export default function IncidentsPage() {
  const q = useQuery({ queryKey: ["incidents"], queryFn: api.incidents, refetchInterval: 5000 });
  return (
    <>
      <PageHeader title="Incidents" subtitle="Incidents raised in simulated environments." actions={<SimulateButton />} />
      <ErrorNote error={q.error} />
      <Card>
        {q.data?.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted">
                <tr><th className="py-2 pr-3 font-medium">Reference</th><th className="pr-3 font-medium">Title</th>
                  <th className="pr-3 font-medium">Service</th><th className="pr-3 font-medium">Severity</th>
                  <th className="pr-3 font-medium">Detected (UTC)</th><th className="font-medium">Status</th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {q.data.map((i) => (
                  <tr key={i.id} className="hover:bg-panel-2">
                    <td className="py-2 pr-3 font-mono text-xs"><Link className="text-accent hover:underline" href={`/incidents/${i.id}`}>{i.reference}</Link></td>
                    <td className="pr-3">{i.title}</td>
                    <td className="pr-3 font-mono text-xs">{i.service}</td>
                    <td className="pr-3"><Badge>{i.severity}</Badge></td>
                    <td className="pr-3 tabular-nums text-muted">{utcTime(i.detected_at)}</td>
                    <td><StatusBadge status={i.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : q.isLoading ? <Empty>Loading…</Empty> : <Empty>No incidents yet.</Empty>}
      </Card>
    </>
  );
}
