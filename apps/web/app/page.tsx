"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { SignalIcon } from "@/components/brand";
import { Composition } from "@/components/visuals";
import { SourceBadge } from "@/components/source-badge";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  PageHeader,
  SeverityBadge,
  StatusBadge,
} from "@/components/ui";
import { api } from "@/lib/api";
import { ModelName } from "@/lib/models";
import { humanize, utcTime } from "@/lib/format";
import { sourceCounts } from "@/lib/visuals";

const SCENARIOS = [
  ["INC-001", "Incompatible schema migration"],
  ["INC-002", "Connection pool exhaustion"],
  ["INC-003", "Invalid settlement payloads"],
  ["NEG-001", "Transient latency blip"],
  ["NEG-002", "External provider outage"],
  ["NEG-003", "Ambiguous changes & log outage"],
];
const MODES = [
  {
    id: "simulator",
    label: "Simulator",
    detail: "Synthetic faults · approved sandbox actions",
    icon: "simulator",
  },
  {
    id: "upload",
    label: "Uploaded files",
    detail: "Logs, metrics, traces · read-only",
    icon: "upload",
  },
  {
    id: "connector",
    label: "Connected telemetry",
    detail: "Loki & Prometheus · read-only",
    icon: "connector",
  },
] as const;

export default function OverviewPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [scenario, setScenario] = useState("INC-001");
  const [mode, setMode] = useState<(typeof MODES)[number]["id"]>("simulator");
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 5000,
  });
  const deps = useQuery({
    queryKey: ["deps"],
    queryFn: api.dependencies,
    refetchInterval: 15000,
  });
  const incidents = useQuery({
    queryKey: ["incidents"],
    queryFn: api.incidents,
    refetchInterval: 5000,
  });
  const simulate = useMutation({
    mutationFn: () => api.simulate(scenario),
    onSuccess: (inc) => {
      qc.invalidateQueries({ queryKey: ["incidents"] });
      router.push(`/incidents/${inc.id}`);
    },
  });
  const o = overview.data;
  const open = o
    ? ["open", "investigating", "awaiting_approval"].reduce(
        (n, key) => n + (o.incidents[key] ?? 0),
        0,
      )
    : "—";
  const checks = Object.entries(deps.data?.checks ?? {});

  return (
    <div className="space-y-7">
      <PageHeader
        title="System overview"
        subtitle="Trace the incident. Weigh the evidence. Decide with context."
        actions={
          <Link href="/guide" className="text-link">
            Open field guide →
          </Link>
        }
      />
      <ErrorNote error={overview.error ?? simulate.error} />

      <div className="status-strip" aria-label="Operational status">
        <span>
          <span
            className="status-light"
            data-ok={checks.length ? checks.every(([, c]) => c.ok) : undefined}
          />
          Runtime:{" "}
          <strong>
            {deps.isLoading
              ? "Checking…"
              : deps.error || !checks.length
                ? "Unavailable"
                : checks.every(([, c]) => c.ok)
                  ? "Healthy"
                  : "Degraded"}
          </strong>
        </span>
        <span>
          Open cases <strong>{open}</strong>
        </span>
        <Link href="/approvals">
          Awaiting approval{" "}
          <strong className="text-warn">
            {o ? (o.actions.pending ?? 0) : "—"}
          </strong>
        </Link>
        <span>
          Local model <ModelName className="font-mono text-xs text-text" />
        </span>
      </div>

      <section className="intake-desk" aria-labelledby="intake-title">
        <div className="intake-intro">
          <h2
            id="intake-title"
            className="font-serif-heading text-3xl font-bold"
          >
            Open an investigation.
          </h2>
          <p>Start with the evidence you have.</p>
          <Link href="/safety" className="text-link">
            Explore the approval boundary →
          </Link>
        </div>
        <div className="intake-controls">
          <div
            className="mode-selector"
            role="group"
            aria-label="Investigation source"
          >
            {MODES.map((m) => (
              <button
                key={m.id}
                onClick={() => setMode(m.id)}
                aria-pressed={mode === m.id}
              >
                <SignalIcon name={m.icon} />
                <span>
                  <strong>{m.label}</strong>
                  <small>{m.detail}</small>
                </span>
                <span className="mode-radio" aria-hidden="true" />
              </button>
            ))}
          </div>
          <div className="intake-action">
            {mode === "simulator" ? (
              <>
                <label htmlFor="scenario-select">Synthetic scenario</label>
                <div className="intake-action-row">
                  <select
                    id="scenario-select"
                    aria-label="Scenario"
                    value={scenario}
                    onChange={(e) => setScenario(e.target.value)}
                  >
                    {SCENARIOS.map(([key, title]) => (
                      <option key={key} value={key}>
                        {key}: {title}
                      </option>
                    ))}
                  </select>
                  <Button
                    variant="primary"
                    disabled={simulate.isPending}
                    onClick={() => simulate.mutate()}
                  >
                    {simulate.isPending ? "Simulating…" : "Simulate"}
                  </Button>
                </div>
                <p>
                  Sandbox only. Each remediation step requires operator
                  approval.
                </p>
                <details className="compact-disclosure">
                  <summary>Explore the six scenarios</summary>
                  <ul className="scenario-list">
                    {SCENARIOS.map(([key, title]) => (
                      <li key={key}>
                        <button
                          onClick={() => setScenario(key)}
                          aria-pressed={scenario === key}
                        >
                          <code>{key}</code>
                          <span>{title}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </details>
              </>
            ) : mode === "upload" ? (
              <>
                <h3>Analyze your files</h3>
                <p>
                  Upload sanitized logs, CSV metrics, JSON traces or events.
                  Source file and line references stay with the findings.
                </p>
                <Link href="/incidents/new" className="action-link">
                  Analyze your files →
                </Link>
                <Badge tone="info">Read-only · no execution</Badge>
              </>
            ) : (
              <>
                <h3>Use connected telemetry</h3>
                <p>
                  Choose configured connectors, preview the snapshot, then
                  investigate. Connection health is checked in the intake flow.
                </p>
                <Link
                  href="/incidents/new?source=connected"
                  className="action-link"
                >
                  Use Loki / Prometheus / Datadog / Azure / CloudWatch →
                </Link>
                <Badge tone="info">Read-only · no execution</Badge>
              </>
            )}
          </div>
        </div>
      </section>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Card
          title="Recent investigations"
          actions={
            <Link href="/incidents" className="text-link">
              All incidents →
            </Link>
          }
        >
          <ErrorNote error={incidents.error} />
          {incidents.isLoading ? (
            <div
              className="loading-lines"
              role="status"
              aria-label="Loading recent incidents"
            >
              <span />
              <span />
              <span />
            </div>
          ) : incidents.data?.length ? (
            <ul className="case-list">
              {incidents.data.slice(0, 6).map((i) => (
                <li key={i.id}>
                  <Link href={`/incidents/${i.id}`}>
                    <div className="case-reference">
                      <code>{i.reference}</code>
                      <SeverityBadge severity={i.severity} />
                    </div>
                    <strong>{i.title}</strong>
                    <div className="case-meta">
                      <span>{i.service}</span>
                      <SourceBadge source={i.evidence_source} />
                      <time dateTime={i.detected_at}>
                        {utcTime(i.detected_at)}
                      </time>
                    </div>
                  </Link>
                  <div>
                    {i.evidence_source === "simulator" ? (
                      <StatusBadge status={i.status} />
                    ) : (
                      <Badge>External: {humanize(i.status)} · unverified</Badge>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            !incidents.error && (
              <Empty>
                No investigations yet. Select a source above to open your first
                case.
              </Empty>
            )
          )}
        </Card>
        <div className="space-y-6">
          <Card title="Investigation sources">
            <Composition
              label="Incident source distribution"
              items={incidents.data ? sourceCounts(incidents.data) : undefined}
            />
            <p className="mt-3 text-xs text-muted">
              All incidents returned by the API.
            </p>
          </Card>
          <Card title="Runtime health">
            <ErrorNote error={deps.error} />
            {checks.length ? (
              <ul className="health-list">
                {checks.map(([key, c]) => (
                  <li key={key}>
                    <span className="status-light" data-ok={c.ok} />
                    <span>{humanize(key.replace(/_/g, " "))}</span>
                    <strong className={c.ok ? "text-success" : "text-danger"}>
                      {c.ok ? "Ready" : "Unavailable"}
                    </strong>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">
                {deps.isLoading
                  ? "Checking runtime dependencies…"
                  : "Health checks unavailable."}
              </p>
            )}
            <Link href="/architecture" className="text-link mt-4 inline-block">
              Inspect architecture →
            </Link>
          </Card>
        </div>
      </div>
    </div>
  );
}
