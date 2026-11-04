"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Badge, Button, Card, Empty, ErrorNote, KV, PageHeader, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { utcTime } from "@/lib/format";

export function IncidentView() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const incident = useQuery({ queryKey: ["incident", id], queryFn: () => api.incident(id), refetchInterval: 5000 });
  const invs = useQuery({ queryKey: ["incident-investigations", id], queryFn: () => api.incidentInvestigations(id), refetchInterval: 4000 });
  const start = useMutation({
    mutationFn: () => api.startInvestigation(id),
    onSuccess: (r) => { qc.invalidateQueries(); router.push(`/investigations/${r.investigation_id}`); },
  });
  const i = incident.data;
  const active = invs.data?.some((v) => ["queued", "running", "awaiting_approval"].includes(v.status));
  return (
    <>
      <PageHeader
        title={i ? i.title : "Incident"}
        subtitle={i ? `${i.reference} · ${i.service}` : undefined}
        actions={<Button variant="primary" disabled={!i || active || start.isPending} onClick={() => start.mutate()}>
          {active ? "Investigation in progress" : start.isPending ? "Starting…" : "Start investigation"}</Button>}
      />
      <ErrorNote error={incident.error ?? start.error} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Details" className="lg:col-span-2">
          {i && <>
            <p className="mb-4 text-sm leading-relaxed">{i.description}</p>
            <KV items={[["Status", <StatusBadge key="s" status={i.status} />], ["Severity", <Badge key="v">{i.severity}</Badge>],
              ["Service", <code key="c" className="font-mono text-xs">{i.service}</code>], ["Detected", utcTime(i.detected_at)],
              ["Environment", <code key="e" className="font-mono text-xs">{i.environment_id}</code>]]} />
          </>}
        </Card>
        <Card title="Investigations">
          {invs.data?.length ? (
            <ul className="divide-y divide-border">
              {invs.data.map((v) => (
                <li key={v.id} className="py-2">
                  <Link href={`/investigations/${v.id}`} className="flex items-center justify-between gap-2 text-sm hover:underline">
                    <span className="font-mono text-xs">{v.id.slice(0, 8)}</span><StatusBadge status={v.status} />
                  </Link>
                  <div className="text-xs text-muted">{utcTime(v.created_at)} · {v.model}</div>
                </li>
              ))}
            </ul>
          ) : <Empty>Not investigated yet.</Empty>}
        </Card>
      </div>
    </>
  );
}
