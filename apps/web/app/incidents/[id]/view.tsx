"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { SourceBadge } from "@/components/source-badge";
import {
  Badge,
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
import { humanize, utcTime } from "@/lib/format";
import { queryStatusLabel } from "@/lib/connectors";
import { formatBytes } from "@/lib/uploads";

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
  const connected = i?.evidence_source === "connector"; // v0.6 Loki/Prometheus, v0.9 Datadog, v0.10 Azure, v0.11 CloudWatch snapshot
  const uploaded = i?.evidence_source === "upload" || connected; // read-only, stored evidence
  const active = invs.data?.some((v) =>
    ["queued", "running", "awaiting_approval"].includes(v.status)
  );
  const dataset = useQuery({
    queryKey: ["dataset", id],
    queryFn: () => api.dataset(id),
    enabled: uploaded,
  });
  const [confirmDelete, setConfirmDelete] = useState(false);
  const discard = useMutation({
    mutationFn: () => api.discardUpload(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["incidents"] });
      router.push("/incidents");
    },
  });

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
              <SourceBadge source={i.evidence_source} />
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
            {i &&
              (uploaded ? (
                <div className="flex items-center gap-1.5">
                  {invs.data?.some((v) => v.status === "completed") ? (
                    <Badge tone="info">Analysis complete (read-only)</Badge>
                  ) : active ? (
                    <Badge tone="info">Investigating (read-only)</Badge>
                  ) : null}
                  <span title="Historical status recorded in external telemetry; not independently verified by OpsPilot">
                    <Badge tone="neutral">External: {humanize(i.status)}</Badge>
                  </span>
                </div>
              ) : (
                <StatusBadge status={i.status} />
              ))}
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
                : uploaded
                ? "Start read-only analysis"
                : "Start investigation"}
            </Button>
          </div>
        }
      />

      <ErrorNote error={incident.error ?? start.error ?? discard.error} />

      {connected && (
        <div className="rounded-xl border border-info/30 bg-info-soft/30 px-4 py-3 text-xs leading-relaxed text-text">
          <strong>Connected telemetry — read-only analysis.</strong> The agent investigates only the telemetry
          snapshot (Loki, Prometheus, Datadog, Azure Monitor or AWS CloudWatch) stored with this incident (plus the runbook knowledge base). It can suggest remediation but cannot
          execute it, and it never claims verified recovery from historical data.
        </div>
      )}
      {uploaded && !connected && (
        <div className="rounded-xl border border-purple/30 bg-purple-soft/30 px-4 py-3 text-xs leading-relaxed text-text">
          <strong>Uploaded evidence — read-only analysis.</strong> The agent investigates only the files uploaded for this
          incident (plus the runbook knowledge base). It can suggest remediation but cannot execute it, and it never
          claims verified recovery.
        </div>
      )}

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
                    uploaded
                      ? [
                          "Status",
                          <span key="s" className="flex items-center gap-1.5 font-mono text-xs">
                            <Badge tone="neutral">External: {humanize(i.status)}</Badge>
                            <span className="text-[11px] text-muted">(unverified by OpsPilot)</span>
                          </span>,
                        ]
                      : ["Status", <StatusBadge key="s" status={i.status} />],
                    ["Severity", <SeverityBadge key="v" severity={i.severity} />],
                    ["Service", <code key="c" className="font-mono text-xs">{i.service}</code>],
                    ["Detected At", utcTime(i.detected_at)],
                    ["Created At", utcTime(i.created_at)],
                    uploaded
                      ? ["Evidence Scope", <span key="e" className="flex items-center gap-1.5"><SourceBadge source={i.evidence_source} /><span className="text-[11px] text-muted">Read-only audit</span></span>]
                      : ["Environment", <code key="e" className="font-mono text-xs">{i.environment_id}</code>],
                  ]}
                />
              </div>
            </div>
          )}
        </Card>

        {uploaded && (
          <Card
            className="lg:col-span-2 lg:order-3"
            title={connected ? "Connected telemetry snapshot" : "Uploaded evidence"}
            subtitle={
              dataset.data
                ? connected
                  ? `Snapshot taken ${utcTime(dataset.data.created_at)} · window ${utcTime(dataset.data.summary.window?.start)} → ${utcTime(dataset.data.summary.window?.end)}`
                  : `Uploaded ${utcTime(dataset.data.created_at)} · timestamps without an offset read as ${dataset.data.timezone}`
                : undefined
            }
            actions={
              confirmDelete ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-danger">{connected ? "Delete the snapshot and analyses?" : "Delete files, records and analyses?"}</span>
                  <Button size="sm" variant="danger" disabled={discard.isPending} onClick={() => discard.mutate()}>
                    {discard.isPending ? "Deleting…" : "Delete"}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
                    Cancel
                  </Button>
                </div>
              ) : (
                <Button size="sm" variant="outline" disabled={active} onClick={() => setConfirmDelete(true)}>
                  {connected ? "Delete snapshot" : "Delete uploaded data"}
                </Button>
              )
            }
          >
            {dataset.data ? (
              <div className="space-y-4 text-xs">
                <div className="flex flex-wrap gap-2">
                  {Object.entries(dataset.data.summary.records).map(([k, n]) => (
                    <Badge key={k}>
                      {n} {k}
                      {n === 1 ? "" : "s"}
                    </Badge>
                  ))}
                  <Badge tone={dataset.data.summary.rejected ? "warn" : "neutral"}>
                    {dataset.data.summary.rejected} rejected
                  </Badge>
                  {dataset.data.summary.redactions > 0 && (
                    <Badge tone="info">{dataset.data.summary.redactions} redacted</Badge>
                  )}
                </div>
                <KV
                  dense
                  items={[
                    ["Services", <span key="s" className="font-mono">{dataset.data.summary.services.join(", ")}</span>],
                    ["Declared affected", <span key="a" className="font-mono">{dataset.data.affected_services.join(", ")}</span>],
                    ["Data covers", `${utcTime(dataset.data.summary.start)} → ${utcTime(dataset.data.summary.end)}`],
                    ["Retention", `purged by \`make uploads-purge\` after ${dataset.data.retention_days} days`],
                  ]}
                />
                {connected && (
                  <ul className="divide-y divide-border rounded-lg border border-border" aria-label="Telemetry queries">
                    {dataset.data.queries.map((q) => (
                      <li key={q.id} className="px-3 py-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-mono font-semibold text-text">{q.id}</span>
                          <span className={q.status === "error" ? "text-danger" : "text-muted"}>
                            {q.status === "error" && !q.aws?.not_queried ? `failed: ${q.error?.kind}` : queryStatusLabel(q)}
                            {q.truncated ? " · truncated" : ""}
                          </span>
                        </div>
                        {q.workspace && (
                          <span className="block text-[10px] text-muted">
                            workspace <span className="font-mono">{q.workspace}</span>
                            {q.tables?.length ? ` · ${q.tables.join(", ")}` : ""}
                          </span>
                        )}
                        {q.aws && (
                          <span className="block text-[10px] text-muted">
                            AWS {q.aws.region}{q.aws.account ? <> · account <span className="font-mono">{q.aws.account}</span></> : null}
                            {q.aws.log_groups?.length ? <> · <span className="font-mono">{q.aws.log_groups.join(", ")}</span></> : null}
                            {q.aws.query_id ? <> · query <span className="font-mono">{q.aws.query_id}</span> ({q.aws.query_status})</> : null}
                            {q.aws.period_seconds ? ` · period ${q.aws.period_seconds} s` : ""}
                          </span>
                        )}
                        <code className="block break-all font-mono text-[10px] text-muted">{q.query}</code>
                        {q.link?.startsWith("https://") && (
                          <a href={q.link} target="_blank" rel="noopener noreferrer" className="text-[10px] text-accent hover:underline">
                            Open in Datadog ({q.site}) ↗
                          </a>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                <ul className="divide-y divide-border rounded-lg border border-border">
                  {dataset.data.files.map((f) => (
                    <li key={f.index} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                      <span className="font-mono font-semibold text-text">{f.name}</span>
                      <span className="text-muted">
                        {f.format} · {formatBytes(f.bytes)} ·{" "}
                        {Object.entries(f.records).map(([k, n]) => `${n} ${k}`).join(", ") || "no records"}
                        {f.rejected ? ` · ${f.rejected} rejected` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
                {!!dataset.data.summary.warnings?.length && (
                  <ul className="list-disc space-y-0.5 pl-4 text-warn">
                    {dataset.data.summary.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <ErrorNote error={dataset.error} />
            )}
          </Card>
        )}

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
