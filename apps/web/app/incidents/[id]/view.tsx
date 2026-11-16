"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  Button,
  Card,
  Empty,
  ErrorNote,
  KV,
  PageHeader,
  SeverityBadge,
  StatusBadge,
} from "@/components/ui";
import { api } from "@/lib/api";
import { utcTime } from "@/lib/format";

export function IncidentView() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();

  const incident = useQuery({
    queryKey: ["incident", id],
    queryFn: () => api.incident(id),
    refetchInterval: 5000,
  });
  const invs = useQuery({
    queryKey: ["incident-investigations", id],
    queryFn: () => api.incidentInvestigations(id),
    refetchInterval: 4000,
  });

  const start = useMutation({
    mutationFn: () => api.startInvestigation(id),
    onSuccess: (r) => {
      qc.invalidateQueries();
      router.push(`/investigations/${r.investigation_id}`);
    },
  });

  const i = incident.data;
  const active = invs.data?.some((v) =>
    ["queued", "running", "awaiting_approval"].includes(v.status)
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-xs text-muted">
        <Link href="/incidents" className="hover:text-text transition-colors">
          Incidents
        </Link>
        <span>/</span>
        <span className="font-mono text-text-muted">{i?.reference ?? id.slice(0, 8)}</span>
      </div>

      <PageHeader
        title={i ? i.title : "Incident Details"}
        subtitle={
          i ? (
            <div className="flex items-center gap-2 mt-1 text-xs text-muted">
              <span className="font-mono font-bold text-accent">{i.reference}</span>
              <span>·</span>
              <span>service: <strong className="text-text">{i.service}</strong></span>
              <span>·</span>
              <span>detected {utcTime(i.detected_at)}</span>
            </div>
          ) : undefined
        }
        actions={
          <div className="flex items-center gap-2">
            {i && <SeverityBadge severity={i.severity} />}
            {i && <StatusBadge status={i.status} />}
            <Button
              variant="primary"
              size="md"
              disabled={!i || active || start.isPending}
              onClick={() => start.mutate()}
            >
              {active
                ? "Investigation in progress"
                : start.isPending
                ? "Starting investigation…"
                : "Start investigation"}
            </Button>
          </div>
        }
      />

      <ErrorNote error={incident.error ?? start.error} />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Incident Details &amp; Telemetry Scope" className="lg:col-span-2">
          {i && (
            <div className="space-y-4">
              <div className="rounded-lg border border-border bg-panel-2/50 p-4 text-xs text-text leading-relaxed font-medium">
                {i.description}
              </div>

              <div className="border-t border-border pt-3">
                <KV
                  items={[
                    ["Reference", <code key="r" className="font-mono font-bold text-accent">{i.reference}</code>],
                    ["Status", <StatusBadge key="s" status={i.status} />],
                    ["Severity", <SeverityBadge key="v" severity={i.severity} />],
                    ["Service", <code key="c" className="font-mono text-xs">{i.service}</code>],
                    ["Detected At", utcTime(i.detected_at)],
                    ["Created At", utcTime(i.created_at)],
                    ["Environment", <code key="e" className="font-mono text-xs">{i.environment_id}</code>],
                  ]}
                />
              </div>
            </div>
          )}
        </Card>

        <Card
          title={`Investigations (${invs.data?.length ?? 0})`}
          subtitle="Autonomous agent runs linked to this incident"
        >
          {invs.data?.length ? (
            <ul className="divide-y divide-border/60">
              {invs.data.map((v) => (
                <li key={v.id} className="py-3">
                  <div className="flex items-center justify-between gap-2">
                    <Link
                      href={`/investigations/${v.id}`}
                      className="font-mono text-xs font-semibold text-accent hover:underline"
                    >
                      {v.id.slice(0, 8)}
                    </Link>
                    <StatusBadge status={v.status} />
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[11px] text-muted">
                    <span>{utcTime(v.created_at)}</span>
                    <span className="font-mono">{v.model}</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Empty
              action={
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!i || start.isPending}
                  onClick={() => start.mutate()}
                >
                  Start investigation
                </Button>
              }
            >
              No investigations started yet.
            </Empty>
          )}
        </Card>
      </div>
    </div>
  );
}
