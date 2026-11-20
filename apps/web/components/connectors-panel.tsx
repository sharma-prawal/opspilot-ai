"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, ErrorNote } from "./ui";
import { api } from "@/lib/api";
import { SIGNAL_STATE, STATE_LABEL, TABLE_STATE, signalLabel, signalsOf } from "@/lib/connectors";
import type { ConnectionStatus, ConnectorId, TelemetrySignal } from "@/lib/types";

/** Live state of the configured read-only connectors (v0.6; Datadog v0.9; Azure Monitor v0.10), with a connection
 * test per connector. */
export function ConnectorsPanel() {
  const q = useQuery({ queryKey: ["connectors"], queryFn: api.connectors });
  const [statuses, setStatuses] = useState<
    Partial<Record<ConnectorId, ConnectionStatus>>
  >({});
  const test = useMutation({
    mutationFn: (id: ConnectorId) => api.testConnector(id),
    onSuccess: (st, id) => setStatuses((p) => ({ ...p, [id]: st })),
  });

  return (
    <Card
      title="Implemented sources"
      subtitle="Configured does not mean reachable. Test each connector to check its current health."
      actions={
        <Link href="/incidents/new?source=connected">
          <Button size="sm" variant="primary">
            Investigate with telemetry →
          </Button>
        </Link>
      }
    >
      {q.isLoading ? (
        <p className="text-xs text-muted">Loading connectors…</p>
      ) : q.error ? (
        <ErrorNote error={q.error} />
      ) : (
        <div className="space-y-3">
          <div className="builtin-source-rows">
            <Link href="/">
              <strong>Simulator</strong>
              <span>Synthetic logs, metrics and changes</span>
              <Badge>Approved sandbox actions</Badge>
            </Link>
            <Link href="/incidents/new">
              <strong>Uploaded files</strong>
              <span>Logs, metrics, traces and events</span>
              <Badge tone="info">Read-only</Badge>
            </Link>
          </div>
          <div className="connector-provider-list">
            {q.data?.connectors.map((c) => {
              const st = statuses[c.id];
              const label = st ? STATE_LABEL[st.status] : null;
              return (
                <details key={c.id} className="connector-provider">
                  <summary>
                    <span className="connector-provider-name">
                      <strong>{c.name}</strong>
                      <small>
                        {signalsOf(c).map((sig) => signalLabel(sig, c.id)).join(" · ")} · Read-only
                      </small>
                    </span>
                    {c.fixture && <Badge tone="warn">Synthetic fixture</Badge>}
                    <Badge tone={c.configured ? "info" : "neutral"}>
                      {c.configured ? "Configured" : "Not configured"}
                    </Badge>
                    {label ? (
                      <Badge tone={label.tone}>{label.label}</Badge>
                    ) : (
                      <Badge>Not tested</Badge>
                    )}
                  </summary>
                  <div className="connector-provider-detail">
                    {c.configured && (
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={test.isPending && test.variables === c.id}
                        onClick={() => test.mutate(c.id)}
                      >
                        {test.isPending && test.variables === c.id
                          ? "Testing…"
                          : "Test connection"}
                      </Button>
                    )}
                    {c.configured ? (
                      <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-text-muted">
                        <dt>Endpoint</dt>
                        <dd className="font-mono text-text">{c.endpoint}</dd>
                        {c.workspace_id && (
                          <>
                            <dt>Workspace</dt>
                            <dd className="font-mono">
                              {c.workspace_id}
                              {c.fixture ? " (requests go to the local synthetic fixture)" : ""}
                            </dd>
                            <dt>Cloud</dt>
                            <dd>{c.cloud}</dd>
                            <dt>Tables</dt>
                            <dd className="font-mono">{c.tables?.join(", ")}</dd>
                            <dt>Minimum role</dt>
                            <dd>{c.permissions?.role}</dd>
                            <dt>Read-only calls</dt>
                            <dd className="font-mono">{c.read_only_endpoints?.join(" · ")}</dd>
                          </>
                        )}
                        {c.site && (
                          <>
                            <dt>Site</dt>
                            <dd className="font-mono">
                              {c.site}
                              {c.fixture ? " (requests go to the local synthetic fixture)" : ""}
                            </dd>
                            <dt>Permissions</dt>
                            <dd className="font-mono">
                              {Object.values(c.permissions ?? {}).join(", ")}
                            </dd>
                            <dt>Read-only calls</dt>
                            <dd className="font-mono">{c.read_only_endpoints?.join(" · ")}</dd>
                          </>
                        )}
                        <dt>Auth</dt>
                        <dd>
                          {c.auth}
                          {c.tenant ? ` · tenant ${c.tenant}` : ""}
                        </dd>
                        <dt>Service label</dt>
                        <dd className="font-mono">{c.service_label}</dd>
                        <dt>Templates</dt>
                        <dd>{c.templates?.map((t) => t.label).join(", ")}</dd>
                        <dt>Limits</dt>
                        <dd>
                          {c.limits ? (
                            <>
                              {c.limits.max_window_hours} h window ·{" "}
                              {signalsOf(c)
                                .map((sig) =>
                                  sig === "log"
                                    ? `${c.limits!.max_log_lines_per_query} lines`
                                    : sig === "metric"
                                      ? c.workspace_id
                                        ? "1 series"
                                        : `${c.limits!.max_series_per_query} series`
                                      : c.workspace_id
                                        ? `${c.limits_extra?.max_records_per_query ?? "?"} records`
                                        : `${c.limits_extra?.max_spans_per_query ?? "?"} spans`,
                                )
                                .join(" · ")}
                              /query · {c.limits.timeout_seconds} s timeout
                            </>
                          ) : (
                            "Not reported"
                          )}
                        </dd>
                      </dl>
                    ) : (
                      <p className="mt-2 text-text-muted">
                        {c.problem ? (
                          <span className="text-warn">{c.problem}. </span>
                        ) : null}
                        To enable: {c.hint}, then restart the API.
                      </p>
                    )}
                    {st?.checked_at && (
                      <p className="mt-2 font-mono text-[10px] text-muted">
                        Checked: {st.checked_at}
                      </p>
                    )}
                    {st && (
                      <p
                        className={`mt-2 ${st.status === "ok" ? "text-success" : st.status === "partial" ? "text-warn" : "text-danger"}`}
                        role="status"
                      >
                        {st.message}
                      </p>
                    )}
                    {st?.signals && (
                      <ul className="mt-2 flex flex-wrap gap-1.5">
                        {Object.entries(st.signals).map(
                          ([sig, v]) =>
                            v && (
                              <li key={sig} title={v.message}>
                                <Badge tone={SIGNAL_STATE[v.status].tone}>
                                  {signalLabel(sig as TelemetrySignal, c.id)}: {SIGNAL_STATE[v.status].label}
                                </Badge>
                              </li>
                            ),
                        )}
                      </ul>
                    )}
                    {st?.tables && (
                      <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label={`${c.name} tables`}>
                        {Object.entries(st.tables).map(([table, v]) => (
                          <li key={table} title={v.message}>
                            <Badge tone={TABLE_STATE[v.status].tone}>
                              {table}: {TABLE_STATE[v.status].label}
                            </Badge>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </details>
              );
            })}
          </div>
          <details className="rounded-lg border border-border bg-panel-2/30 p-3 text-xs text-text-muted">
            <summary className="cursor-pointer font-semibold text-text">
              Set up and try the connectors (first run)
            </summary>
            <ol className="mt-2 list-decimal space-y-1 pl-4">
              <li>
                Apply migration 0011 with the normal workflow:{" "}
                <code className="font-mono">
                  make infra-up &amp;&amp; make migrate
                </code>{" "}
                (additive; existing incidents are kept).
              </li>
              <li>
                Start the local demo stack:{" "}
                <code className="font-mono">make telemetry-up</code> (Loki
                127.0.0.1:3310, tenant{" "}
                <code className="font-mono">opspilot-demo</code>; Prometheus
                127.0.0.1:9390; synthetic incident).
              </li>
              <li>
                In <code className="font-mono">.env</code>:{" "}
                <code className="font-mono">
                  LOKI_URL=http://127.0.0.1:3310
                </code>
                ,{" "}
                <code className="font-mono">LOKI_TENANT_ID=opspilot-demo</code>,{" "}
                <code className="font-mono">
                  PROMETHEUS_URL=http://127.0.0.1:9390
                </code>
                ,{" "}
                <code className="font-mono">
                  TELEMETRY_TEMPLATES_FILE=infra/telemetry/query-templates.json
                </code>
                . For your own backends add read-only credentials (
                <code className="font-mono">*_BEARER_TOKEN</code>, or{" "}
                <code className="font-mono">*_USERNAME</code> +{" "}
                <code className="font-mono">*_PASSWORD</code>; https unless
                loopback).
              </li>
              <li>
                Restart the API (
                <code className="font-mono">make stop &amp;&amp; make dev</code>
                ); settings are read at start-up.
              </li>
              <li>
                Click <strong className="text-text">Test connection</strong>{" "}
                above, then{" "}
                <strong className="text-text">
                  Investigate with telemetry
                </strong>
                : use the demo incident, choose templates, preview, create and
                start the analysis.
              </li>
              <li>
                Different applications: set{" "}
                <code className="font-mono">LOKI_SERVICE_LABEL</code> /{" "}
                <code className="font-mono">PROMETHEUS_SERVICE_LABEL</code> to
                the label holding service names, and describe your metric names
                in the templates file; restart the API.
              </li>
              <li>
                Stop the demo stack with{" "}
                <code className="font-mono">make telemetry-down</code> and
                remove the connector lines from{" "}
                <code className="font-mono">.env</code>.
              </li>
            </ol>
            <p className="mt-3 font-semibold text-text">Datadog (v0.9)</p>
            <ol className="mt-1 list-decimal space-y-1 pl-4">
              <li>
                Create a Datadog application key with only{" "}
                <code className="font-mono">logs_read_data</code>,{" "}
                <code className="font-mono">timeseries_query</code> and{" "}
                <code className="font-mono">apm_read</code> (scoped key), plus an API key.
              </li>
              <li>
                In <code className="font-mono">.env</code> (backend only, never{" "}
                <code className="font-mono">NEXT_PUBLIC_*</code>):{" "}
                <code className="font-mono">DATADOG_ENABLED=true</code>,{" "}
                <code className="font-mono">DATADOG_SITE</code> (e.g.{" "}
                <code className="font-mono">datadoghq.eu</code>),{" "}
                <code className="font-mono">DATADOG_API_KEY</code>,{" "}
                <code className="font-mono">DATADOG_APP_KEY</code>; optionally{" "}
                <code className="font-mono">DATADOG_ENV</code>. Restart the API.
              </li>
              <li>
                Test connection: it validates the API key and probes each product, so a missing
                permission shows per signal.
              </li>
              <li>
                Without an account: <code className="font-mono">make datadog-fixture</code> serves
                synthetic Datadog API responses on 127.0.0.1 (see docs/integrations/DATADOG.md).
              </li>
            </ol>
            <p className="mt-3 font-semibold text-text">Azure Monitor / Application Insights (v0.10)</p>
            <ol className="mt-1 list-decimal space-y-1 pl-4">
              <li>
                Use a workspace-based Application Insights resource and note its Log Analytics{" "}
                <strong className="text-text">workspace ID</strong> (a GUID). Assign the identity{" "}
                <code className="font-mono">Log Analytics Data Reader</code> on that workspace only.
              </li>
              <li>
                In <code className="font-mono">.env</code> (backend only):{" "}
                <code className="font-mono">AZURE_MONITOR_ENABLED=true</code>,{" "}
                <code className="font-mono">AZURE_MONITOR_WORKSPACE_ID</code> and{" "}
                <code className="font-mono">AZURE_MONITOR_AUTH_MODE</code>:{" "}
                <code className="font-mono">service_principal</code> (with{" "}
                <code className="font-mono">AZURE_TENANT_ID</code>,{" "}
                <code className="font-mono">AZURE_CLIENT_ID</code>,{" "}
                <code className="font-mono">AZURE_CLIENT_SECRET</code>),{" "}
                <code className="font-mono">managed_identity</code> or{" "}
                <code className="font-mono">azure_cli</code> (development). Restart the API.
              </li>
              <li>
                Test connection: it obtains a token, runs one workspace query and probes the four
                Application Insights tables, so a missing table or role shows separately.
              </li>
              <li>
                Without a subscription: <code className="font-mono">make azure-fixture</code> serves
                synthetic Logs API responses on 127.0.0.1 (see docs/integrations/AZURE_MONITOR.md).
              </li>
            </ol>
            <p className="mt-2">
              <strong className="text-text">Verified:</strong> local Loki 3.5.0
              and Prometheus 3.5.0 containers with synthetic data; Datadog and
              Azure Monitor only against their synthetic contract fixtures.{" "}
              <strong className="text-text">Not verified:</strong> remote or
              cloud endpoints (Grafana Cloud, https deployments, Mimir, Thanos,
              managed Prometheus); only bearer and basic auth are supported; a
              live Datadog organization or Azure workspace (not yet tested).
              Details: docs/integrations/CONNECTORS.md.
            </p>
          </details>
          {!!q.data?.template_problems.length && (
            <ul className="list-disc pl-4 text-xs text-warn">
              {q.data.template_problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          <details className="compact-disclosure">
            <summary>Adapter implementation reference</summary>
            <p className="mt-2 text-xs text-muted">
              Planned, not implemented: {q.data?.planned.join(", ")}. New
              providers implement the{" "}
              <code className="font-mono">TelemetryConnector</code> contract
              (docs/integrations/CONNECTORS.md).
            </p>
          </details>
          <ErrorNote error={test.error} />
        </div>
      )}
    </Card>
  );
}
