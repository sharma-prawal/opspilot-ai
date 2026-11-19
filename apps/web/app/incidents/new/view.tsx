"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState, type DragEvent } from "react";
import { Badge, Button, Card, ErrorNote, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { ModelName } from "@/lib/models";
import { utcTime } from "@/lib/format";
import type { NormalizedRecord, SignalType, UploadPreview, UploadRequest } from "@/lib/types";
import {
  EXAMPLE_FILES,
  EXAMPLE_INCIDENT,
  UPLOAD_LIMITS,
  defaultServiceFor,
  extensionOf,
  fileProblem,
  formatBytes,
  normalizeService,
  parseServices,
  timezoneOptions,
} from "@/lib/uploads";
import { SourceTabs } from "./tabs";

interface Picked {
  key: string;
  name: string;
  size: number;
  content: string | null; // null until read (or unreadable)
  problem: string | null;
  service: string;
}

const SIGNALS: { key: SignalType; label: string }[] = [
  { key: "log", label: "Logs" },
  { key: "metric", label: "Metrics" },
  { key: "span", label: "Trace spans" },
  { key: "event", label: "Change events" },
];

const input =
  "h-9 w-full rounded-lg border border-border bg-panel-2 px-3 text-sm text-text placeholder:text-muted/60 focus:outline-hidden focus:ring-2 focus:ring-accent";

function Field({ label, hint, children, htmlFor }: { label: string; hint?: string; children: React.ReactNode; htmlFor: string }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-semibold text-text">
        {label}
      </label>
      {children}
      {hint && <p className="text-[11px] leading-relaxed text-muted">{hint}</p>}
    </div>
  );
}

function recordText(r: NormalizedRecord): string {
  if (r.message !== undefined) return `${r.level ?? ""}${r.level_inferred ? " (inferred)" : ""} ${r.message}`;
  if (r.metric !== undefined) return `${r.metric} = ${r.value}${r.unit ? ` ${r.unit}` : ""}`;
  if (r.trace_id && r.name !== undefined)
    return `${r.name} · ${r.status}${r.duration_ms != null ? ` · ${Math.round(r.duration_ms)} ms` : ""}`;
  if (r.event_type !== undefined) return `${r.event_type}: ${r.summary ?? ""}`;
  return "";
}

export function UploadView() {
  const router = useRouter();
  const qc = useQueryClient();
  const zones = useMemo(() => timezoneOptions(), []);
  const fileInput = useRef<HTMLInputElement>(null);

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [service, setService] = useState("");
  const [affected, setAffected] = useState("");
  const [severity, setSeverity] = useState("SEV2");
  const [time, setTime] = useState("");
  const [timezone, setTimezone] = useState("UTC");
  const [files, setFiles] = useState<Picked[]>([]);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const [tab, setTab] = useState<SignalType>("log");
  const [stage, setStage] = useState<"idle" | "creating" | "starting">("idle");

  const primary = normalizeService(service);
  const others = parseServices(affected);
  const ready = files.filter((f) => !f.problem && f.content !== null);
  const total = ready.reduce((n, f) => n + f.size, 0);
  const tooMany = ready.length > UPLOAD_LIMITS.maxFiles;
  const tooBig = total > UPLOAD_LIMITS.maxTotalBytes;

  const formProblems: string[] = [];
  if (title.trim().length < 3) formProblems.push("Give the incident a title (3+ characters).");
  if (!primary) formProblems.push("Name the affected service (lower-case letters, digits and dashes, e.g. checkout-api).");
  if (others.invalid.length) formProblems.push(`Not valid service names: ${others.invalid.join(", ")}.`);
  if (!time) formProblems.push("Enter the approximate incident time.");
  if (!ready.length) formProblems.push("Add at least one readable file.");
  if (tooMany) formProblems.push(`At most ${UPLOAD_LIMITS.maxFiles} files per incident.`);
  if (tooBig) formProblems.push(`Total upload is over ${formatBytes(UPLOAD_LIMITS.maxTotalBytes)}.`);
  const fileServiceProblems = ready.filter((f) => f.service.trim() && !normalizeService(f.service));
  if (fileServiceProblems.length) formProblems.push("A per-file service name is not valid.");

  const invalidate = () => setPreview(null);

  function body(): UploadRequest {
    return {
      files: ready.map((f) => ({
        name: f.name,
        content: f.content ?? "",
        service: f.service.trim() ? normalizeService(f.service) : null,
      })),
      timezone,
      incident_time: time || null,
      service: primary,
      affected_services: others.services.filter((s) => s !== primary),
    };
  }

  async function addFiles(list: FileList | File[]) {
    invalidate();
    const incoming = Array.from(list);
    const picked: Picked[] = incoming.map((f) => ({
      key: `${f.name}-${f.size}-${f.lastModified}-${Math.random().toString(36).slice(2, 7)}`,
      name: f.name,
      size: f.size,
      content: null,
      problem: fileProblem(f),
      service: defaultServiceFor(f.name, primary ?? ""),
    }));
    setFiles((prev) => [...prev, ...picked]);
    await Promise.all(
      incoming.map(async (f, i) => {
        if (picked[i].problem) return;
        try {
          const text = await f.text();
          const problem = text.includes("\u0000") ? "Binary content is not supported" : null;
          setFiles((prev) => prev.map((p) => (p.key === picked[i].key ? { ...p, content: text, problem } : p)));
        } catch {
          setFiles((prev) =>
            prev.map((p) => (p.key === picked[i].key ? { ...p, problem: "The browser could not read this file" } : p)),
          );
        }
      }),
    );
  }

  const example = useMutation({
    mutationFn: async () => {
      const loaded = await Promise.all(
        EXAMPLE_FILES.map(async (e) => {
          const res = await fetch(`/examples/uploads/${e.name}`, { cache: "no-store" });
          if (!res.ok) throw new Error(`could not load example ${e.name}`);
          const content = await res.text();
          return { e, content };
        }),
      );
      return loaded;
    },
    onSuccess: (loaded) => {
      setTitle(EXAMPLE_INCIDENT.title);
      setDescription(EXAMPLE_INCIDENT.description);
      setService(EXAMPLE_INCIDENT.service);
      setAffected(EXAMPLE_INCIDENT.affected);
      setSeverity(EXAMPLE_INCIDENT.severity);
      setTime(EXAMPLE_INCIDENT.time);
      setTimezone(EXAMPLE_INCIDENT.timezone);
      setFiles(
        loaded.map(({ e, content }) => ({
          key: `example-${e.name}`,
          name: e.name,
          size: new Blob([content]).size,
          content,
          problem: null,
          service: e.service ?? "",
        })),
      );
      setPreview(null);
    },
  });

  const previewM = useMutation({
    mutationFn: () => api.uploadPreview(body()),
    onSuccess: (p) => {
      setPreview(p);
      const first = SIGNALS.find((s) => (p.summary.records[s.key] ?? 0) > 0);
      if (first) setTab(first.key);
    },
  });

  const create = useMutation({
    mutationFn: async () => {
      setStage("creating");
      const b = body();
      const incident = await api.uploadIncident({
        ...b,
        title: title.trim(),
        description: description.trim(),
        service: primary ?? "",
        severity,
        incident_time: time,
      });
      setStage("starting");
      const inv = await api.startInvestigation(incident.id);
      return { incident, inv };
    },
    onSuccess: ({ inv }) => {
      qc.invalidateQueries({ queryKey: ["incidents"] });
      router.push(`/investigations/${inv.investigation_id}`);
    },
    onError: () => setStage("idle"),
  });

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files?.length) void addFiles(e.dataTransfer.files);
  }

  const busy = create.isPending || previewM.isPending;
  const samples = preview?.samples[tab] ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-xs text-muted">
        <Link href="/incidents" className="hover:text-text transition-colors">
          Incidents
        </Link>
        <span>/</span>
        <span className="text-text-muted">Analyze files</span>
      </div>

      <PageHeader
        title="Analyze your own incident data"
        badge={<Badge tone="purple">Uploaded evidence</Badge>}
        subtitle={
          <span>
            Upload sanitized logs, metrics, traces or change events. OpsPilot normalizes them, shows you what it
            extracted, then investigates with the local model{" "}
            <ModelName kind="llm" className="font-mono text-xs text-text" /> — read-only: it suggests
            remediation but never executes it.
          </span>
        }
      />
      <SourceTabs active="upload" />

      <div role="note" className="rounded-xl border border-warn/30 bg-warn-soft/30 px-4 py-3 text-xs leading-relaxed text-text">
        <strong>Sanitize your files before uploading.</strong> Remove customer data, personal data and secrets.
        Values that look like passwords, tokens or keys are redacted automatically as a safety net, but other
        sensitive data is not detected. Files stay on this machine.
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card title="1. Incident" subtitle="What happened, where and when. The agent treats this text as data, not instructions.">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <Field label="Title" htmlFor="up-title">
                  <input id="up-title" className={input} value={title} maxLength={300}
                    placeholder="e.g. Checkout payments failing"
                    onChange={(e) => { setTitle(e.target.value); invalidate(); }} />
                </Field>
              </div>
              <div className="sm:col-span-2">
                <Field label="Description" htmlFor="up-desc" hint="Symptoms, alert text, what users saw. Optional.">
                  <textarea id="up-desc" rows={3} maxLength={4000} value={description}
                    className={`${input} h-auto py-2`}
                    onChange={(e) => { setDescription(e.target.value); invalidate(); }} />
                </Field>
              </div>
              <Field label="Affected service" htmlFor="up-svc" hint="The service that alerted; the analysis centres on it.">
                <input id="up-svc" className={input} value={service} placeholder="checkout-api"
                  aria-invalid={!!service && !primary}
                  onChange={(e) => {
                    const before = primary ?? "";
                    setService(e.target.value);
                    const next = normalizeService(e.target.value) ?? "";
                    // keep text-log files that still default to the old service in step
                    setFiles((prev) => prev.map((f) =>
                      [".log", ".txt"].includes(extensionOf(f.name)) && f.service === before ? { ...f, service: next } : f));
                    invalidate();
                  }} />
              </Field>
              <Field label="Other affected services" htmlFor="up-other" hint="Comma-separated. Each one is inspected too.">
                <input id="up-other" className={input} value={affected} placeholder="payment-service"
                  onChange={(e) => { setAffected(e.target.value); invalidate(); }} />
              </Field>
              <Field label="Approximate incident time" htmlFor="up-time"
                hint="The analysis looks 3 h before to 30 min after this time (change history further back).">
                <input id="up-time" type="datetime-local" step={60} className={input} value={time}
                  onChange={(e) => { setTime(e.target.value); invalidate(); }} />
              </Field>
              <Field label="Timezone" htmlFor="up-tz"
                hint="Used for the incident time and for file timestamps that have no offset (recorded as assumed).">
                <select id="up-tz" className={input} value={timezone}
                  onChange={(e) => { setTimezone(e.target.value); invalidate(); }}>
                  {zones.map((z) => <option key={z} value={z}>{z}</option>)}
                </select>
              </Field>
              <Field label="Severity" htmlFor="up-sev">
                <select id="up-sev" className={input} value={severity} onChange={(e) => setSeverity(e.target.value)}>
                  {["SEV1", "SEV2", "SEV3", "SEV4"].map((s) => <option key={s}>{s}</option>)}
                </select>
              </Field>
            </div>
          </Card>

          <Card
            title="2. Evidence files"
            subtitle={`Up to ${UPLOAD_LIMITS.maxFiles} files · ${formatBytes(UPLOAD_LIMITS.maxFileBytes)} each · ${formatBytes(UPLOAD_LIMITS.maxTotalBytes)} total · ${UPLOAD_LIMITS.extensions.join(" ")}`}
          >
            <div
              role="button"
              tabIndex={0}
              aria-label="Drop files here or browse"
              onClick={() => fileInput.current?.click()}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") fileInput.current?.click(); }}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors ${
                dragging ? "border-accent bg-accent-soft/40" : "border-border bg-panel-2/40 hover:border-border-strong"
              }`}
            >
              <div className="text-2xl text-muted" aria-hidden>⇪</div>
              <p className="mt-2 text-sm font-semibold text-text">Drag files here, or click to browse</p>
              <p className="mt-1 text-xs text-muted">
                Application logs (.log, .txt), structured logs / events / OTLP traces (.json), metric or event exports (.csv)
              </p>
              <input ref={fileInput} type="file" multiple hidden accept={UPLOAD_LIMITS.extensions.join(",")}
                onChange={(e) => { if (e.target.files) void addFiles(e.target.files); e.target.value = ""; }} />
            </div>

            {files.length > 0 && (
              <ul className="mt-4 divide-y divide-border rounded-lg border border-border" aria-label="Selected files">
                {files.map((f) => (
                  <li key={f.key} className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-xs">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate font-mono font-semibold text-text">{f.name}</span>
                        <Badge>{extensionOf(f.name) || "?"}</Badge>
                        <span className="text-muted tabular-nums">{formatBytes(f.size)}</span>
                      </div>
                      {f.problem ? (
                        <p className="mt-1 text-danger">✕ {f.problem}</p>
                      ) : f.content === null ? (
                        <p className="mt-1 text-muted">Reading…</p>
                      ) : null}
                    </div>
                    {!f.problem && (
                      <label className="flex items-center gap-1.5 text-[11px] text-muted">
                        service if a record names none
                        <input
                          aria-label={`Service for ${f.name}`}
                          value={f.service}
                          placeholder="(reject such records)"
                          onChange={(e) => {
                            const v = e.target.value;
                            setFiles((prev) => prev.map((p) => (p.key === f.key ? { ...p, service: v } : p)));
                            invalidate();
                          }}
                          className={`h-7 w-40 rounded-md border bg-panel-2 px-2 font-mono text-[11px] text-text ${
                            f.service.trim() && !normalizeService(f.service) ? "border-danger" : "border-border"
                          }`}
                        />
                      </label>
                    )}
                    <button
                      onClick={() => { setFiles((prev) => prev.filter((p) => p.key !== f.key)); invalidate(); }}
                      className="rounded px-2 py-1 text-muted hover:bg-panel-2 hover:text-danger cursor-pointer"
                      aria-label={`Remove ${f.name}`}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {formProblems.length > 0 && (files.length > 0 || title) && (
              <ul className="mt-4 space-y-1 text-xs text-warn" aria-live="polite">
                {formProblems.map((p) => <li key={p}>• {p}</li>)}
              </ul>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button variant="primary" size="md" disabled={formProblems.length > 0 || busy}
                onClick={() => previewM.mutate()}>
                {previewM.isPending ? "Validating…" : preview ? "Refresh preview" : "Preview extracted evidence"}
              </Button>
              <span className="text-xs text-muted">Nothing is stored until you create the incident.</span>
            </div>
            <div className="mt-3"><ErrorNote error={previewM.error} /></div>
          </Card>

          {preview && (
            <Card
              title="3. Extracted evidence"
              subtitle="Exactly what the agent will be able to retrieve. Records without a usable timestamp or service were rejected, never filled in."
              actions={<Badge tone={preview.usable ? "success" : "danger"}>{preview.usable ? "ready" : "nothing usable"}</Badge>}
            >
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {SIGNALS.map((s) => (
                  <div key={s.key} className="rounded-lg border border-border bg-panel-2/50 p-3">
                    <div className="text-[11px] uppercase tracking-wider text-muted">{s.label}</div>
                    <div className="mt-1 text-xl font-bold tabular-nums text-text">{preview.summary.records[s.key] ?? 0}</div>
                  </div>
                ))}
              </div>
              <dl className="mt-4 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-xs">
                <dt className="text-muted">Services</dt>
                <dd className="font-mono text-text">{preview.summary.services.join(", ") || "—"}</dd>
                <dt className="text-muted">Time range</dt>
                <dd className="text-text">{utcTime(preview.summary.start)} → {utcTime(preview.summary.end)}</dd>
                <dt className="text-muted">Timezones</dt>
                <dd className="text-text">{preview.summary.timezones.join(", ") || "—"}</dd>
                <dt className="text-muted">Metrics</dt>
                <dd className="text-text">
                  {Object.entries(preview.summary.metrics_by_service).map(([svc, ms]) => (
                    <div key={svc}><span className="font-mono">{svc}</span>: {ms.join(", ")}</div>
                  ))}
                  {!Object.keys(preview.summary.metrics_by_service).length && "—"}
                </dd>
                <dt className="text-muted">Rejected / redacted</dt>
                <dd className="text-text">
                  {preview.summary.rejected} record(s) rejected · {preview.summary.redactions} credential-like value(s) redacted
                </dd>
              </dl>

              {preview.warnings.length > 0 && (
                <div className="mt-4 rounded-lg border border-warn/30 bg-warn-soft/30 p-3">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-warn">Check before analyzing</h4>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-text-muted">
                    {preview.warnings.map((w) => <li key={w}>{w}</li>)}
                  </ul>
                </div>
              )}

              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted">
                    <tr>
                      <th className="py-2 pr-3 font-semibold">File</th>
                      <th className="pr-3 font-semibold">Read as</th>
                      <th className="pr-3 font-semibold">Records</th>
                      <th className="pr-3 font-semibold">Rejected</th>
                      <th className="font-semibold">Issues</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/60">
                    {preview.files.map((f) => (
                      <tr key={f.index} className="align-top">
                        <td className="py-2 pr-3 font-mono text-text">{f.name}</td>
                        <td className="pr-3 text-text-muted">{f.format || "—"}</td>
                        <td className="pr-3 tabular-nums text-text">
                          {Object.entries(f.records).map(([k, n]) => `${n} ${k}`).join(", ") || "0"}
                        </td>
                        <td className={`pr-3 tabular-nums ${f.rejected ? "text-warn" : "text-muted"}`}>{f.rejected}</td>
                        <td className="text-text-muted">
                          {f.issues.length ? (
                            <details>
                              <summary className="cursor-pointer">{f.issues[0]}</summary>
                              <ul className="mt-1 space-y-0.5">{f.issues.slice(1).map((i) => <li key={i}>{i}</li>)}</ul>
                            </details>
                          ) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mt-5">
                <div className="flex flex-wrap gap-1" role="tablist" aria-label="Sample records">
                  {SIGNALS.map((s) => (
                    <button key={s.key} role="tab" aria-selected={tab === s.key} onClick={() => setTab(s.key)}
                      className={`rounded-md border px-2.5 py-1 text-xs font-medium cursor-pointer ${
                        tab === s.key ? "border-accent bg-accent-soft text-accent" : "border-border text-muted hover:text-text"
                      }`}>
                      {s.label} ({preview.summary.records[s.key] ?? 0})
                    </button>
                  ))}
                </div>
                <div className="mt-2 overflow-x-auto rounded-lg border border-border">
                  {samples.length ? (
                    <table className="w-full text-[11px]">
                      <thead className="bg-panel-2/60 text-left text-muted">
                        <tr>
                          <th className="px-2 py-1.5 font-semibold">Time (UTC)</th>
                          <th className="px-2 font-semibold">Service</th>
                          <th className="px-2 font-semibold">Content</th>
                          <th className="px-2 font-semibold">Source</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border/60">
                        {samples.map((r, i) => (
                          <tr key={i} className="align-top">
                            <td className="whitespace-nowrap px-2 py-1.5 tabular-nums text-text-muted" title={`as written: ${r.ts_original} (${r.tz})`}>
                              {utcTime(r.ts)}
                            </td>
                            <td className="px-2 py-1.5 font-mono text-text">
                              {r.service}
                              {r.service_source === "file_default" && <span className="ml-1 text-muted" title="declared for the file">*</span>}
                            </td>
                            <td className="max-w-md px-2 py-1.5 break-words text-text">{recordText(r).slice(0, 220)}</td>
                            <td className="whitespace-nowrap px-2 py-1.5 font-mono text-accent">{r.source}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="p-4 text-center text-xs text-muted">No records of this type.</p>
                  )}
                </div>
                <p className="mt-1 text-[11px] text-muted">* service declared for the file. Hover a time to see it as written.</p>
              </div>

              <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-border pt-4">
                <Button variant="primary" size="md" disabled={!preview.usable || busy || formProblems.length > 0}
                  onClick={() => create.mutate()}>
                  {stage === "creating" ? "Creating incident…" : stage === "starting" ? "Starting investigation…" : "Create incident & start analysis"}
                </Button>
                <span className="text-xs text-muted">
                  Files are stored locally; the investigation runs on your machine with the configured Ollama model.
                </span>
              </div>
              <div className="mt-3"><ErrorNote error={create.error} /></div>
            </Card>
          )}
        </div>

        <div className="space-y-6">
          <Card title="Try the example" subtitle="Synthetic files for a checkout outage after a payment-service deploy">
            <ul className="space-y-2 text-xs">
              {EXAMPLE_FILES.map((e) => (
                <li key={e.name} className="flex items-start justify-between gap-2">
                  <div>
                    <a href={`/examples/uploads/${e.name}`} download className="font-mono font-semibold text-accent hover:underline">
                      {e.name}
                    </a>
                    <p className="text-muted">{e.kind} · {e.description}</p>
                  </div>
                </li>
              ))}
            </ul>
            <Button className="mt-4 w-full" variant="secondary" size="sm" disabled={example.isPending || busy}
              onClick={() => example.mutate()}>
              {example.isPending ? "Loading…" : "Load example into the form"}
            </Button>
            <div className="mt-2"><ErrorNote error={example.error} /></div>
          </Card>

          <Card title="What happens to your data">
            <ul className="space-y-2 text-xs leading-relaxed text-text-muted">
              <li><strong className="text-text">Local only.</strong> Files are kept under the API&apos;s upload directory and in the local database. Inference uses your local Ollama model; nothing is sent to an external AI API.</li>
              <li><strong className="text-text">Untrusted data.</strong> File contents are evidence, never instructions; values that look like passwords, tokens or keys are redacted when parsed.</li>
              <li><strong className="text-text">Read-only.</strong> Uploaded incidents cannot run remediation or claim verified recovery. You get hypotheses, citations, gaps, suggested steps and a report.</li>
              <li><strong className="text-text">Deletable.</strong> Delete an uploaded incident from its page; <code className="font-mono">make uploads-purge</code> removes uploads older than the retention period.</li>
            </ul>
          </Card>

          <Card title="What the agent can read">
            <ul className="space-y-1.5 text-xs text-text-muted">
              <li><strong className="text-text">.log / .txt</strong> — lines starting with a timestamp; level and key=value pairs recognized; stack traces join the entry above.</li>
              <li><strong className="text-text">.json</strong> — arrays, JSON lines or OTLP traces: logs (message), metrics (name + value), spans (trace/span id), events (deployment, rollback, migration, config change, alert).</li>
              <li><strong className="text-text">.csv</strong> — a timestamp column plus metric columns, metric/value rows, or an event-type column.</li>
            </ul>
            <p className="mt-3 text-[11px] text-muted">
              Not available from files: live health, runtime config, datastore and queue state. The report lists them as gaps.
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
}
