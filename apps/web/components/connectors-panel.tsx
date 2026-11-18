"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, ErrorNote } from "./ui";
import { api } from "@/lib/api";
import { STATE_LABEL } from "@/lib/connectors";
import type { ConnectionStatus, ConnectorId } from "@/lib/types";

/** Live state of the configured read-only connectors (v0.6), with a connection test per connector. */
export function ConnectorsPanel() {
  const q = useQuery({ queryKey: ["connectors"], queryFn: api.connectors });
  const [statuses, setStatuses] = useState<Partial<Record<ConnectorId, ConnectionStatus>>>({});
  const test = useMutation({
    mutationFn: (id: ConnectorId) => api.testConnector(id),
    onSuccess: (st, id) => setStatuses((p) => ({ ...p, [id]: st })),
  });

  return (
    <Card
      title="Connected observability (v0.6)"
      subtitle="Read-only connectors configured on this OpsPilot API. Only these destinations are ever contacted."
      actions={
        <Link href="/incidents/new?source=connected">
          <Button size="sm" variant="primary">Investigate with telemetry →</Button>
        </Link>
      }
    >
      {q.isLoading ? (
        <p className="text-xs text-muted">Loading connectors…</p>
      ) : q.error ? (
        <ErrorNote error={q.error} />
      ) : (
        <div className="space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            {q.data?.connectors.map((c) => {
              const st = statuses[c.id];
              const label = st ? STATE_LABEL[st.status] : null;
              return (
                <div key={c.id} className="rounded-lg border border-border bg-panel-2/40 p-3 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-bold text-text">{c.name}</span>
                    <Badge tone="success">Implemented</Badge>
                    <Badge tone={c.configured ? "info" : "neutral"}>{c.configured ? "Configured" : "Not configured"}</Badge>
                    {label && <Badge tone={label.tone}>{label.label}</Badge>}
                    <span className="flex-1" />
                    {c.configured && (
                      <Button size="sm" variant="secondary" disabled={test.isPending && test.variables === c.id}
                        onClick={() => test.mutate(c.id)}>
                        {test.isPending && test.variables === c.id ? "Testing…" : "Test connection"}
                      </Button>
                    )}
                  </div>
                  {c.configured ? (
                    <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-text-muted">
                      <dt>Endpoint</dt><dd className="font-mono text-text">{c.endpoint}</dd>
                      <dt>Auth</dt><dd>{c.auth}{c.tenant ? ` · tenant ${c.tenant}` : ""}</dd>
                      <dt>Service label</dt><dd className="font-mono">{c.service_label}</dd>
                      <dt>Templates</dt><dd>{c.templates?.map((t) => t.label).join(", ")}</dd>
                      <dt>Limits</dt>
                      <dd>
                        {c.limits?.max_window_hours} h window · {c.signal === "log" ? `${c.limits?.max_log_lines_per_query} lines` : `${c.limits?.max_series_per_query} series`}/query · {c.limits?.timeout_seconds} s timeout
                      </dd>
                    </dl>
                  ) : (
                    <p className="mt-2 text-text-muted">
                      {c.problem ? <span className="text-warn">{c.problem}. </span> : null}To enable: {c.hint}, then restart the API.
                    </p>
                  )}
                  {st && <p className={`mt-2 ${st.status === "ok" ? "text-success" : "text-danger"}`} role="status">{st.message}</p>}
                </div>
              );
            })}
          </div>
          {!!q.data?.template_problems.length && (
            <ul className="list-disc pl-4 text-xs text-warn">{q.data.template_problems.map((p) => <li key={p}>{p}</li>)}</ul>
          )}
          <p className="text-[11px] text-muted">
            Planned, not implemented: {q.data?.planned.join(", ")}. New providers implement the{" "}
            <code className="font-mono">TelemetryConnector</code> contract (docs/integrations/CONNECTORS.md).
          </p>
          <ErrorNote error={test.error} />
        </div>
      )}
    </Card>
  );
}
