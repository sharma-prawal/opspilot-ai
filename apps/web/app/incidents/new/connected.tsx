"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader } from "@/components/ui";
import { SeriesChart } from "@/components/visuals";
import { api } from "@/lib/api";
import {
  DEMO_AZURE, DEMO_CONNECTED, DEMO_DATADOG, TABLE_STATE, connectedService, parseConnectedServices, SIGNAL_STATE, STATE_LABEL, defaultWindow, queryErrorHint,
  signalLabel, signalsOf, templateSignal, utcIso, windowProblem,
} from "@/lib/connectors";
import { utcTime } from "@/lib/format";
import { ModelName } from "@/lib/models";
import type {
  ConnectedPreview, ConnectedRequest, ConnectionStatus, ConnectorId, ConnectorInfo, NormalizedRecord, TelemetrySignal,
} from "@/lib/types";
import { SourceTabs } from "./tabs";

const input =
  "h-9 w-full rounded-lg border border-border bg-panel-2 px-3 text-sm text-text placeholder:text-muted/60 focus:outline-hidden focus:ring-2 focus:ring-accent";

function Field({ label, hint, children, htmlFor }: { label: string; hint?: string; children: React.ReactNode; htmlFor: string }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-semibold text-text">{label}</label>
      {children}
      {hint && <p className="text-[11px] leading-relaxed text-muted">{hint}</p>}
    </div>
  );
}

function recordText(r: NormalizedRecord): string {
  if (r.message !== undefined) return `${r.level ?? ""}${r.level_inferred ? " (inferred)" : ""} ${r.message}`;
  if (r.metric !== undefined) return `${r.metric} = ${Number(r.value).toPrecision(4)}${r.unit ? ` ${r.unit}` : ""}`;
  if (r.trace_id !== undefined && r.name !== undefined) {
    const dur = typeof r.duration_ms === "number" ? ` · ${Math.round(r.duration_ms)} ms` : "";
    const parent = r.parent_span_id ? "" : " · root";
    const partial = r.attributes?.parent_missing ? " · parent not in snapshot (partial trace)" : "";
    const sampled = typeof r.attributes?.["azure.item_count"] === "number" ? ` · represents ${r.attributes["azure.item_count"]} sampled items` : "";
    return `${r.status === "error" ? "ERROR " : ""}${r.name}${dur}${parent}${partial}${sampled}${r.status_message ? ` — ${r.status_message}` : ""}`;
  }
  return "";
}

const TABS: { key: TelemetrySignal; label: string }[] = [
  { key: "log", label: "Logs" }, { key: "metric", label: "Metrics" }, { key: "span", label: "Spans / requests" },
];

function ConnectorCard({
  c, enabled, onEnabled, chosen, onChosen, status, onTest, testing,
}: {
  c: ConnectorInfo; enabled: boolean; onEnabled: (v: boolean) => void; chosen: string[]; onChosen: (t: string[]) => void;
  status: ConnectionStatus | undefined; onTest: () => void; testing: boolean;
}) {
  const state = status ? STATE_LABEL[status.status] : null;
  const signals = signalsOf(c);
  const groups = signals.map((sig) => ({ sig, items: (c.templates ?? []).filter((t) => templateSignal(t) === sig) }));
  return (
    <div className={`rounded-xl border p-4 ${enabled ? "border-accent/50 bg-accent-soft/10" : "border-border bg-panel-2/30"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm font-bold text-text">
          <input type="checkbox" checked={enabled} disabled={!c.configured} onChange={(e) => onEnabled(e.target.checked)}
            aria-label={`Use ${c.name}`} />
          {c.name}
        </label>
        {signals.map((sig) => <Badge key={sig}>{signalLabel(sig, c.id).toLowerCase()}</Badge>)}
        {c.fixture && <Badge tone="warn" className="text-[10px]">synthetic fixture</Badge>}
        {!c.configured ? (
          <Badge tone="neutral">Not configured</Badge>
        ) : state ? (
          <span title={status?.message}><Badge tone={state.tone}>{state.label}</Badge></span>
        ) : null}
        <span className="flex-1" />
        {c.configured && (
          <Button size="sm" variant="secondary" onClick={onTest} disabled={testing}>
            {testing ? "Testing…" : "Test connection"}
          </Button>
        )}
      </div>
      {!c.configured ? (
        <p className="mt-2 text-xs text-muted">
          {c.problem ? <span className="text-warn">{c.problem}. </span> : null}
          To enable it, {c.hint ?? "configure it in the API environment"} and restart the API. See{" "}
          <Link className="text-accent hover:underline" href="/integrations">Integrations</Link>.
        </p>
      ) : (
        <>
          {c.workspace_id ? (
            <p className="mt-1 text-[11px] text-muted">
              workspace <span className="font-mono">{c.workspace_id}</span> · <span className="font-mono">{c.endpoint}</span>
              {" "}· auth: {c.auth} · service = <span className="font-mono">{c.service_label}</span> (case-insensitive)
              {c.permissions?.role ? <> · needs {c.permissions.role}</> : null}
            </p>
          ) : (
          <p className="mt-1 text-[11px] text-muted">
            <span className="font-mono">{c.endpoint}</span>{c.site ? <> · site <span className="font-mono">{c.site}</span></> : null}
            {" "}· auth: {c.auth}
            {c.tenant ? <> · tenant <span className="font-mono">{c.tenant}</span></> : null} · service {c.site ? "tag" : "label"}{" "}
            <span className="font-mono">{c.service_label}</span>{c.env ? <> · env <span className="font-mono">{c.env}</span></> : null}
          </p>
          )}
          {status && status.status !== "ok" && (
            <p role="alert" className={`mt-2 text-xs ${status.status === "partial" ? "text-warn" : "text-danger"}`}>{status.message}</p>
          )}
          {status?.status === "ok" && <p className="mt-2 text-xs text-success">{status.message}{status.latency_ms ? ` · ${status.latency_ms} ms` : ""}</p>}
          {status?.signals && (
            <ul className="mt-2 flex flex-wrap gap-1.5" aria-label={`${c.name} signal availability`}>
              {Object.entries(status.signals).map(([sig, st]) => st && (
                <li key={sig} title={st.message}>
                  <Badge tone={SIGNAL_STATE[st.status].tone}>{signalLabel(sig as TelemetrySignal, c.id)}: {SIGNAL_STATE[st.status].label}</Badge>
                </li>
              ))}
            </ul>
          )}
          {status?.tables && (
            <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label={`${c.name} table availability`}>
              {Object.entries(status.tables).map(([table, st]) => (
                <li key={table} title={st.message}>
                  <Badge tone={TABLE_STATE[st.status].tone} className="font-mono text-[10px]">{table}: {TABLE_STATE[st.status].label}</Badge>
                </li>
              ))}
            </ul>
          )}
          <fieldset className="mt-3 space-y-1.5" disabled={!enabled}>
            <legend className="text-[11px] font-semibold uppercase tracking-wider text-muted">Approved query templates</legend>
            {groups.map(({ sig, items }) => (
              <div key={sig} className="space-y-1.5">
                {groups.length > 1 && (
                  <p className="pt-1 text-[11px] font-semibold text-text-muted">
                    {signalLabel(sig, c.id)}{c.permissions?.[sig] ? <span className="font-normal text-muted"> · needs <span className="font-mono">{c.permissions[sig]}</span></span> : null}
                  </p>
                )}
            {items.map((t) => (
              <label key={t.id} className="flex items-start gap-2 text-xs">
                <input type="checkbox" className="mt-0.5" checked={chosen.includes(t.id)}
                  onChange={(e) => onChosen(e.target.checked ? [...chosen, t.id] : chosen.filter((x) => x !== t.id))} />
                <span>
                  <span className="font-semibold text-text">{t.label}</span>
                  {t.unit && <span className="text-muted"> ({t.unit})</span>}
                  {t.source === "file" && <Badge className="ml-1 text-[10px]">from templates file</Badge>}
                  <span className="block text-muted">{t.description}</span>
                  <code className="block break-all font-mono text-[10px] text-text-muted" title="The service selector is filled in per service">{t.query}</code>
                </span>
              </label>
            ))}
              </div>
            ))}
          </fieldset>
        </>
      )}
    </div>
  );
}

export function ConnectedView() {
  const router = useRouter();
  const qc = useQueryClient();
  const connectors = useQuery({ queryKey: ["connectors"], queryFn: api.connectors });

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [service, setService] = useState("");
  const [affected, setAffected] = useState("");
  const [severity, setSeverity] = useState("SEV2");
  const [time, setTime] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [enabled, setEnabled] = useState<Partial<Record<ConnectorId, boolean>>>({});
  const [chosen, setChosen] = useState<Partial<Record<ConnectorId, string[]>>>({});
  const [statuses, setStatuses] = useState<Partial<Record<ConnectorId, ConnectionStatus>>>({});
  const [preview, setPreview] = useState<ConnectedPreview | null>(null);
  const [tab, setTab] = useState<TelemetrySignal>("log");
  const [stage, setStage] = useState<"idle" | "creating" | "starting">("idle");

  const list = connectors.data?.connectors ?? [];
  const configured = list.filter((c) => c.configured);
  const maxHours = configured[0]?.limits?.max_window_hours ?? 6;
  const isOn = (c: ConnectorInfo) => c.configured && (enabled[c.id] ?? true);
  const templatesOf = (c: ConnectorInfo) => chosen[c.id] ?? (c.templates ?? []).filter((t) => t.default).map((t) => t.id);
  const primary = connectedService(service);
  const others = parseConnectedServices(affected);
  const invalidate = () => setPreview(null);

  const problems: string[] = [];
  if (title.trim().length < 3) problems.push("Give the incident a title (3+ characters).");
  if (!primary) problems.push("Name the affected service as it appears in the service label (e.g. checkout-api).");
  if (others.invalid.length) problems.push(`Not valid service names: ${others.invalid.join(", ")}.`);
  if (!utcIso(time)) problems.push("Enter the incident time (UTC).");
  const wp = windowProblem(start, end, maxHours);
  if (wp) problems.push(wp);
  const sources = configured.filter(isOn).map((c) => ({ connector: c.id, templates: templatesOf(c) }));
  if (!sources.length) problems.push("Select at least one configured connector.");
  if (sources.some((s) => !s.templates.length)) problems.push("Choose at least one template for each selected connector.");

  function body(): ConnectedRequest {
    return {
      sources,
      service: primary ?? "",
      affected_services: others.services.filter((s) => s !== primary).slice(0, 3),
      start: utcIso(start) ?? "",
      end: utcIso(end) ?? "",
      incident_time: utcIso(time),
    };
  }

  const test = useMutation({
    mutationFn: (id: ConnectorId) => api.testConnector(id),
    onSuccess: (st, id) => setStatuses((prev) => ({ ...prev, [id]: st })),
  });

  const discover = useMutation({
    mutationFn: async () => {
      const w = { start: utcIso(start) ?? "", end: utcIso(end) ?? "" };
      const found = await Promise.all(configured.filter(isOn).map((c) => api.connectorServices(c.id, w)));
      return found;
    },
  });
  const discovered = Array.from(new Set((discover.data ?? []).flatMap((d) => d.services))).sort();

  const previewM = useMutation({
    mutationFn: () => api.connectedPreview(body()),
    onSuccess: (p) => { setPreview(p); setTab(p.summary.records.log ? "log" : p.summary.records.metric ? "metric" : "span"); },
  });

  const create = useMutation({
    mutationFn: async () => {
      setStage("creating");
      const incident = await api.connectedIncident({
        ...body(), title: title.trim(), description: description.trim(), severity, incident_time: utcIso(time) ?? "",
      });
      setStage("starting");
      const inv = await api.startInvestigation(incident.id);
      return inv;
    },
    onSuccess: (inv) => {
      qc.invalidateQueries({ queryKey: ["incidents"] });
      router.push(`/investigations/${inv.investigation_id}`);
    },
    onError: () => setStage("idle"),
  });

  function setIncidentTime(v: string) {
    setTime(v);
    if (utcIso(v)) {
      const w = defaultWindow(v);
      setStart(w.start);
      setEnd(w.end);
    }
    invalidate();
  }

  function loadDemo(demo: typeof DEMO_CONNECTED = DEMO_CONNECTED) {
    setTitle(demo.title);
    setDescription(demo.description);
    setService(demo.service);
    setAffected(demo.affected);
    setSeverity(demo.severity);
    setIncidentTime(demo.time);
  }
  // The local demo incidents only exist in the local test setups: Loki/Prometheus (`make telemetry-up`) and the
  // synthetic Datadog/Azure Monitor fixtures (loopback only). Never offered against a real Datadog site or workspace.
  const ddFixture = configured.some((c) => c.id === "datadog" && c.fixture);
  const azFixture = configured.some((c) => c.id === "azure_monitor" && c.fixture);
  const v06Demo = configured.some((c) => c.id === "loki" || c.id === "prometheus");

  const busy = previewM.isPending || create.isPending;
  const samples = preview?.samples[tab] ?? [];
  const failed = preview?.queries.filter((q) => q.status === "error") ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-xs text-muted">
        <Link href="/incidents" className="hover:text-text transition-colors">Incidents</Link>
        <span>/</span>
        <span className="text-text-muted">Connected telemetry</span>
      </div>

      <PageHeader
        title="Investigate with connected telemetry"
        badge={<Badge tone="cyan">Connected telemetry</Badge>}
        subtitle={
          <span>
            Query your configured Grafana Loki, Prometheus, Datadog or Azure Monitor for one incident window with approved templates,
            check what came back, then investigate with the local model{" "}
            <ModelName kind="llm" className="font-mono text-xs text-text" /> — read-only: it suggests
            remediation but never executes it.
          </span>
        }
      />
      <SourceTabs active="connected" />

      <div role="note" className="rounded-xl border border-border bg-panel-2/50 px-4 py-3 text-xs leading-relaxed text-text-muted">
        <strong className="text-text">Read-only snapshot.</strong> OpsPilot runs only the approved templates against
        the connector URLs configured on the API (never another address), with bounded windows, line and series limits,
        and no redirects. The results are stored as a snapshot with this incident; the investigation reads only that
        snapshot. Values that look like credentials are redacted. Historical data cannot verify the current state.
      </div>

      {connectors.isLoading ? (
        <Card><p className="text-sm text-muted">Loading connectors…</p></Card>
      ) : connectors.error ? (
        <Card><ErrorNote error={connectors.error} /></Card>
      ) : !configured.length ? (
        <Card>
          <Empty
            action={
              <div className="flex justify-center gap-2">
                <Link href="/integrations"><Button size="sm" variant="secondary">Integrations</Button></Link>
                <Link href="/incidents/new"><Button size="sm" variant="secondary">Upload files instead</Button></Link>
              </div>
            }
          >
            <strong className="text-text">No connector is configured.</strong> Set <code className="font-mono">LOKI_URL</code>,{" "}
            <code className="font-mono">PROMETHEUS_URL</code>, <code className="font-mono">DATADOG_ENABLED</code> with
            the Datadog site and keys, and/or <code className="font-mono">AZURE_MONITOR_ENABLED</code> with a workspace ID
            and credentials in the API environment (see .env.example) and restart the API. For local test setups
            with synthetic data run <code className="font-mono">make telemetry-up</code>,{" "}
            <code className="font-mono">make datadog-fixture</code> or <code className="font-mono">make azure-fixture</code>.
          </Empty>
        </Card>
      ) : (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-6 lg:col-span-2">
            <Card title="1. Incident and window" subtitle="Times are UTC. The agent treats this text as data, not instructions."
              actions={
                <div className="flex max-w-[16rem] flex-wrap justify-end gap-2 sm:max-w-none">
                  {v06Demo && <Button size="sm" variant="secondary" onClick={() => loadDemo()}>Use the local demo incident</Button>}
                  {ddFixture && <Button size="sm" variant="secondary" onClick={() => loadDemo(DEMO_DATADOG)}>Use the Datadog fixture incident</Button>}
                  {azFixture && <Button size="sm" variant="secondary" onClick={() => loadDemo(DEMO_AZURE)}>Use the Azure fixture incident</Button>}
                </div>
              }>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <Field label="Title" htmlFor="cn-title">
                    <input id="cn-title" className={input} value={title} maxLength={300} placeholder="e.g. Checkout payments failing"
                      onChange={(e) => { setTitle(e.target.value); invalidate(); }} />
                  </Field>
                </div>
                <div className="sm:col-span-2">
                  <Field label="Description" htmlFor="cn-desc" hint="Symptoms, alert text. Optional.">
                    <textarea id="cn-desc" rows={2} maxLength={4000} value={description} className={`${input} h-auto py-2`}
                      onChange={(e) => { setDescription(e.target.value); invalidate(); }} />
                  </Field>
                </div>
                <Field label="Affected service" htmlFor="cn-svc" hint="Exact value of the service label (Datadog: service tag; Azure: AppRoleName, case-insensitive; '.' and '_' allowed). Loki/Prometheus: slugs only.">
                  <input id="cn-svc" className={input} value={service} placeholder="checkout-api" list="cn-services"
                    aria-invalid={!!service && !primary} onChange={(e) => { setService(e.target.value); invalidate(); }} />
                </Field>
                <Field label="Other affected services" htmlFor="cn-other" hint="Comma-separated, up to 3. Each one is queried too.">
                  <input id="cn-other" className={input} value={affected} placeholder="payment-service"
                    onChange={(e) => { setAffected(e.target.value); invalidate(); }} />
                </Field>
                <Field label="Incident time (UTC)" htmlFor="cn-time" hint="Sets the window to 3 h before and 30 min after, which is what the investigation examines.">
                  <input id="cn-time" type="datetime-local" step={60} className={input} value={time}
                    onChange={(e) => setIncidentTime(e.target.value)} />
                </Field>
                <Field label="Severity" htmlFor="cn-sev">
                  <select id="cn-sev" className={input} value={severity} onChange={(e) => setSeverity(e.target.value)}>
                    {["SEV1", "SEV2", "SEV3", "SEV4"].map((s) => <option key={s}>{s}</option>)}
                  </select>
                </Field>
                <Field label="Window start (UTC)" htmlFor="cn-start">
                  <input id="cn-start" type="datetime-local" step={60} className={input} value={start}
                    onChange={(e) => { setStart(e.target.value); invalidate(); }} />
                </Field>
                <Field label="Window end (UTC)" htmlFor="cn-end" hint={`At most ${maxHours} h.`}>
                  <input id="cn-end" type="datetime-local" step={60} className={input} value={end}
                    onChange={(e) => { setEnd(e.target.value); invalidate(); }} />
                </Field>
              </div>
              <datalist id="cn-services">{discovered.map((s) => <option key={s} value={s} />)}</datalist>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                <Button size="sm" variant="secondary" disabled={!!windowProblem(start, end, maxHours) || discover.isPending}
                  onClick={() => discover.mutate()}>
                  {discover.isPending ? "Looking up services…" : "Find services in this window"}
                </Button>
                {discover.data && (discovered.length ? (
                  discovered.map((s) => (
                    <button key={s} type="button" onClick={() => { if (!primary) setService(s); else if (s !== primary) setAffected((a) => (a ? `${a}, ${s}` : s)); invalidate(); }}
                      className="rounded-md border border-border px-2 py-0.5 font-mono text-[11px] text-text hover:border-accent cursor-pointer">
                      {s}
                    </button>
                  ))
                ) : <span className="text-muted">No services found in this window.</span>)}
                {discover.data?.filter((d) => d.error).map((d) => (
                  <span key={d.connector} className="text-danger">{d.connector}: {d.error?.message}</span>
                ))}
                {discover.data?.flatMap((d) => (d.notes ?? []).map((n) => (
                  <span key={`${d.connector}-${n}`} className="w-full text-muted">{d.connector}: {n}</span>
                )))}
              </div>
              <div className="mt-2"><ErrorNote error={discover.error} /></div>
            </Card>

            <Card title="2. Sources and templates" subtitle="Only approved templates can run; you cannot type a query.">
              <div className="space-y-3">
                {list.map((c) => (
                  <ConnectorCard key={c.id} c={c} enabled={isOn(c)} chosen={templatesOf(c)}
                    onEnabled={(v) => { setEnabled((p) => ({ ...p, [c.id]: v })); invalidate(); }}
                    onChosen={(t) => { setChosen((p) => ({ ...p, [c.id]: t })); invalidate(); }}
                    status={statuses[c.id]} testing={test.isPending && test.variables === c.id}
                    onTest={() => test.mutate(c.id)} />
                ))}
              </div>
              <ErrorNote error={test.error} />
              {problems.length > 0 && (title || service || time) && (
                <ul className="mt-4 space-y-1 text-xs text-warn" aria-live="polite">{problems.map((p) => <li key={p}>• {p}</li>)}</ul>
              )}
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button variant="primary" size="md" disabled={problems.length > 0 || busy} onClick={() => previewM.mutate()}>
                  {previewM.isPending ? "Querying…" : preview ? "Refresh preview" : "Preview returned evidence"}
                </Button>
                <span className="text-xs text-muted">Nothing is stored until you create the incident.</span>
              </div>
              <div className="mt-3"><ErrorNote error={previewM.error} /></div>
            </Card>

            {preview && (
              <Card title="3. Returned evidence" subtitle="Exactly what the agent will be able to read. Signals that were not collected stay unknown."
                actions={<Badge tone={preview.usable ? "success" : "danger"}>{preview.usable ? "ready" : "no data"}</Badge>}>
                {!preview.usable && (
                  <div role="status" className="mb-4 rounded-lg border border-danger/30 bg-danger-soft/30 p-3 text-xs text-text">
                    {failed.length
                      ? "The queries failed — see the errors below. Fix the connector, then refresh the preview."
                      : "The queries succeeded but returned no data for this window and these services. Check the window and the service name."}
                  </div>
                )}
                <div className={`grid grid-cols-2 gap-3 ${preview.collected.span ? "sm:grid-cols-5" : "sm:grid-cols-4"}`}>
                  {[
                    ["Log lines", preview.summary.records.log],
                    ["Metric points", preview.summary.records.metric],
                    ...(preview.collected.span ? [["Spans", preview.summary.records.span ?? 0]] : []),
                    ["Queries", preview.queries.length],
                    ["Failed queries", failed.length],
                  ].map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-border bg-panel-2/50 p-3">
                      <div className="text-[11px] uppercase tracking-wider text-muted">{k}</div>
                      <div className={`mt-1 text-xl font-bold tabular-nums ${k === "Failed queries" && Number(v) > 0 ? "text-danger" : "text-text"}`}>{v}</div>
                    </div>
                  ))}
                </div>
                <dl className="mt-4 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-xs">
                  <dt className="text-muted">Logs collected for</dt>
                  <dd className="font-mono text-text">{preview.collected.log.join(", ") || "— (unknown)"}</dd>
                  <dt className="text-muted">Metrics collected for</dt>
                  <dd className="font-mono text-text">{preview.collected.metric.join(", ") || "— (unknown)"}</dd>
                  {preview.collected.span && (
                    <>
                      <dt className="text-muted">Spans collected for</dt>
                      <dd className="font-mono text-text">{preview.collected.span.join(", ") || "— (unknown)"}</dd>
                    </>
                  )}
                  <dt className="text-muted">Time range</dt>
                  <dd className="text-text">{utcTime(preview.summary.start)} → {utcTime(preview.summary.end)}</dd>
                  <dt className="text-muted">Redacted</dt>
                  <dd className="text-text">{preview.summary.redactions} credential-like value(s)</dd>
                </dl>
                {preview.warnings.length > 0 && (
                  <div className="mt-4 rounded-lg border border-warn/30 bg-warn-soft/30 p-3">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-warn">Check before analyzing</h4>
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-text-muted">{preview.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
                  </div>
                )}
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full text-xs" aria-label="Queries">
                    <thead className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted">
                      <tr><th className="py-2 pr-3 font-semibold">Query</th><th className="pr-3 font-semibold">Result</th><th className="pr-3 font-semibold">Resolution</th><th className="font-semibold">Details</th></tr>
                    </thead>
                    <tbody className="divide-y divide-border/60">
                      {preview.queries.map((q) => (
                        <tr key={q.id} className="align-top">
                          <td className="py-2 pr-3"><span className="font-mono text-text">{q.id}</span>
                            {q.tables?.length ? <span className="block text-[10px] text-muted">tables: {q.tables.join(", ")}</span> : null}
                            <code className="mt-0.5 block max-w-sm break-all font-mono text-[10px] text-muted">{q.query}</code>
                            {q.link?.startsWith("https://") && (
                              <a href={q.link} target="_blank" rel="noopener noreferrer" className="text-[10px] text-accent hover:underline">Open in Datadog ↗</a>
                            )}</td>
                          <td className="pr-3">
                            <Badge tone={q.status === "ok" ? "success" : q.status === "empty" ? "neutral" : "danger"}>
                              {q.status === "error" ? q.error?.kind.replace("_", " ") : q.status === "empty" ? "no data" : `${q.returned} records`}
                            </Badge>
                            {q.truncated && <Badge tone="warn" className="ml-1">truncated</Badge>}
                          </td>
                          <td className="pr-3 text-text-muted">{q.step_seconds ? `step ${q.step_seconds} s` : `limit ${q.limit}`}{q.pages ? ` · ${q.pages} page(s)` : ""} · {Math.round(q.duration_ms)} ms</td>
                          <td className="text-text-muted">{q.status === "error" ? <span className="text-danger">{queryErrorHint(q)} <span className="text-muted">({q.error?.message})</span></span> : q.issues.join("; ") || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="mt-5">
                  <div className="flex gap-1" role="tablist" aria-label="Sample records">
                    {TABS.filter((t) => t.key !== "span" || preview.collected.span).map(({ key: k, label }) => (
                      <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                        className={`rounded-md border px-2.5 py-1 text-xs font-medium cursor-pointer ${tab === k ? "border-accent bg-accent-soft text-accent" : "border-border text-muted hover:text-text"}`}>
                        {label} ({preview.summary.records[k] ?? 0})
                      </button>
                    ))}
                  </div>
                  <div className="mt-2 overflow-x-auto rounded-lg border border-border">
                    {samples.length ? (
                      <table className="w-full text-[11px]">
                        <thead className="bg-panel-2/60 text-left text-muted">
                          <tr><th className="px-2 py-1.5 font-semibold">Time (UTC)</th><th className="px-2 font-semibold">Service</th><th className="px-2 font-semibold">Content</th><th className="px-2 font-semibold">Source</th></tr>
                        </thead>
                        <tbody className="divide-y divide-border/60">
                          {samples.map((r, i) => (
                            <tr key={i} className="align-top">
                              <td className="whitespace-nowrap px-2 py-1.5 tabular-nums text-text-muted" title={`as returned: ${r.ts_original} (${r.tz})`}>{utcTime(r.ts)}</td>
                              <td className="px-2 py-1.5 font-mono text-text">{r.service}{r.service_source === "query" && <span className="ml-1 text-muted" title="from the query's service selector">*</span>}</td>
                              <td className="max-w-md px-2 py-1.5 break-words text-text">{recordText(r).slice(0, 220)}</td>
                              <td className="whitespace-nowrap px-2 py-1.5 font-mono text-accent">{r.source}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : <p className="p-4 text-center text-xs text-muted">No records of this type.</p>}
                  </div>
                  <p className="mt-1 text-[11px] text-muted">* service from the query&apos;s selector (aggregated series). Hover a time to see it as returned.</p>
                </div>
                {!!preview.series?.length && (
                  <div className="mt-5">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-muted">Returned metric series</h4>
                    <p className="mt-0.5 text-[11px] text-muted">Every point as the backend returned it; intervals without a value are breaks, never filled in.</p>
                    <div className="mt-2 grid gap-3 sm:grid-cols-2">
                      {preview.series.map((s) => <SeriesChart key={`${s.service}/${s.metric}`} series={s} />)}
                    </div>
                  </div>
                )}
                <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-border pt-4">
                  <Button variant="primary" size="md" disabled={!preview.usable || busy || problems.length > 0} onClick={() => create.mutate()}>
                    {stage === "creating" ? "Taking snapshot…" : stage === "starting" ? "Starting investigation…" : "Create incident & start analysis"}
                  </Button>
                  <span className="text-xs text-muted">The queries run again and their results are stored with the incident.</span>
                </div>
                <div className="mt-3"><ErrorNote error={create.error} /></div>
              </Card>
            )}
          </div>

          <div className="space-y-6">
            <Card title="How it works">
              <ol className="list-decimal space-y-2 pl-4 text-xs leading-relaxed text-text-muted">
                <li>Each selected template runs for the affected service and each other service, over the window.</li>
                <li>Lines and samples become the same normalized evidence as uploads, keeping the original timestamp, unit, labels and the query that returned them.</li>
                <li>The snapshot is stored with the incident; the LangGraph investigation reads only the snapshot. Runbooks still come from the knowledge base.</li>
                <li>Results are read-only: no approval, no execution, no claim of verified recovery.</li>
              </ol>
            </Card>
            <Card title="Not available from connected telemetry">
              <p className="text-xs leading-relaxed text-text-muted">
                Deployment and config-change history, live health, runtime configuration, datastore and queue state;
                traces too, unless Datadog APM spans or Application Insights requests/dependencies are collected (a
                bounded, possibly sampled set, so a trace can be partial). The agent treats what is missing as unknown
                and the report lists it as a gap. Connectors for CloudWatch and custom sources are planned, not
                implemented.
              </p>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
