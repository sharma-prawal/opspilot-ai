// Client helpers for connected observability (v0.6; Datadog v0.9; Azure Monitor v0.10; AWS CloudWatch v0.11). The API validates everything
// again.
import type {
  ChartSeries, ConnectionState, ConnectorId, ConnectorInfo, QueryProvenance, QueryTemplate, SignalState, TelemetrySignal,
} from "./types";

/** The synthetic incident served by `make telemetry-up` (scripts/generate_telemetry.py). */
export const DEMO_CONNECTED = {
  title: "Checkout payments failing",
  description:
    "Checkout error-rate alert fired at 09:16 UTC; customers report payment errors. (Synthetic telemetry from the local Loki/Prometheus test setup.)",
  service: "checkout-api",
  affected: "payment-service",
  severity: "SEV2",
  time: "2026-11-12T09:16",
};

/** The incident of the synthetic Datadog fixture (scripts/datadog_fixture.py, `make datadog-fixture`). */
export const DEMO_DATADOG = {
  title: "Orders failing with 504s",
  description:
    "orders-api 5xx alert fired at 14:05 UTC; customers cannot place orders. (Synthetic Datadog fixture data, not a real organization.)",
  service: "orders-api",
  affected: "inventory-service",
  severity: "SEV2",
  time: "2026-11-15T14:05",
};

/** The incident of the synthetic Azure Monitor fixture (scripts/azure_monitor_fixture.py, `make azure-fixture`). */
export const DEMO_AZURE = {
  title: "Orders failing with 502s",
  description:
    "orders-api failed-request alert fired at 10:35 UTC; checkout cannot complete payments. (Synthetic Azure Monitor fixture data, not a real workspace.)",
  service: "orders-api",
  affected: "payment-service, inventory-service",
  severity: "SEV2",
  time: "2026-11-16T10:35",
};

/** The incident of the synthetic AWS CloudWatch fixture (scripts/cloudwatch_fixture.py, `make cloudwatch-fixture`). */
export const DEMO_CLOUDWATCH = {
  title: "Checkout failing: inventory timeouts",
  description:
    "api-gateway 5xx alarm fired at 14:12 UTC; checkout cannot reserve stock. (Synthetic AWS CloudWatch fixture data, not a real AWS account.)",
  service: "inventory-service",
  affected: "checkout-service, api-gateway",
  severity: "SEV2",
  time: "2026-11-18T14:12",
};

/**
 * v0.9: service names for connected telemetry are kept exactly (trimmed, lower-cased), never rewritten into another
 * name: Datadog service tags may contain '.' and '_' (billing.worker_v2). Loki/Prometheus still accept slugs only and
 * the API says so. The API validates and escapes again.
 */
export const CONNECTED_SERVICE_PATTERN = /^[a-z][a-z0-9._-]{1,62}$/;

export function connectedService(raw: string): string | null {
  const s = raw.trim().toLowerCase();
  return CONNECTED_SERVICE_PATTERN.test(s) ? s : null;
}

export function parseConnectedServices(raw: string): { services: string[]; invalid: string[] } {
  const services: string[] = [];
  const invalid: string[] = [];
  for (const p of raw.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean)) {
    const s = connectedService(p);
    if (!s) invalid.push(p);
    else if (!services.includes(s)) services.push(s);
  }
  return { services, invalid };
}

export const SIGNAL_LABEL: Record<TelemetrySignal, string> = { log: "Logs", metric: "Metrics", span: "APM spans" };

/** Signal names per provider: Azure Monitor's span signal is Application Insights requests and dependencies. */
export function signalLabel(sig: TelemetrySignal, connector?: ConnectorId | string): string {
  if (connector === "azure_monitor") {
    return { log: "Traces & exceptions", metric: "KQL metrics", span: "Requests & dependencies" }[sig];
  }
  if (connector === "cloudwatch") {
    return { log: "Logs Insights events", metric: "CloudWatch metrics", span: "Traces" }[sig];
  }
  return SIGNAL_LABEL[sig];
}

/** Table availability from a connection test (v0.10 Azure Monitor). */
export const TABLE_STATE: Record<SignalState, { label: string; tone: "success" | "danger" | "warn" | "neutral" }> = {
  ok: { label: "present", tone: "success" },
  permission_denied: { label: "access denied", tone: "danger" },
  unsupported: { label: "not in workspace", tone: "neutral" },
  rate_limited: { label: "throttled", tone: "warn" },
  unavailable: { label: "unavailable", tone: "warn" },
  error: { label: "error", tone: "danger" },
};

/** Signals a connector can return (v0.6 connectors have exactly one). */
export function signalsOf(c: ConnectorInfo): TelemetrySignal[] {
  return c.signals?.length ? c.signals : [c.signal];
}

/** The signal a template returns. */
export function templateSignal(t: QueryTemplate): TelemetrySignal {
  return t.signal ?? (t.connector === "loki" ? "log" : "metric");
}

export const SIGNAL_STATE: Record<SignalState, { label: string; tone: "success" | "danger" | "warn" | "neutral" }> = {
  ok: { label: "readable", tone: "success" },
  permission_denied: { label: "permission missing", tone: "danger" },
  unsupported: { label: "not available", tone: "neutral" },
  rate_limited: { label: "rate-limited", tone: "warn" },
  unavailable: { label: "unavailable", tone: "warn" },
  error: { label: "error", tone: "danger" },
};

/**
 * Splits a series into runs of consecutive points: a gap longer than 1.5 steps (a missing value the provider did not
 * return) ends a run, so a chart draws a break there instead of a line across missing data.
 */
export function seriesRuns(s: ChartSeries): [number, number][][] {
  const step = (s.step_seconds ?? 60) * 1000;
  const runs: [number, number][][] = [];
  let last = -Infinity;
  for (const [ts, v] of s.points) {
    const t = Date.parse(ts);
    if (!Number.isFinite(t) || !Number.isFinite(v)) continue;
    if (t - last > step * 1.5 || !runs.length) runs.push([]);
    runs[runs.length - 1].push([t, v]);
    last = t;
  }
  return runs;
}

/** A datetime-local value (read as UTC) as an ISO timestamp, or null. */
export function utcIso(local: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(local)) return null;
  return `${local.length === 16 ? `${local}:00` : local}Z`;
}

/** datetime-local value (UTC) shifted by minutes. */
export function shiftLocal(local: string, minutes: number): string {
  const iso = utcIso(local);
  if (!iso) return "";
  return new Date(Date.parse(iso) + minutes * 60_000).toISOString().slice(0, 16);
}

/** The analysis window for an incident time: 3 h before to 30 min after (what the investigation examines). */
export function defaultWindow(local: string): { start: string; end: string } {
  return { start: shiftLocal(local, -180), end: shiftLocal(local, 30) };
}

export function windowProblem(start: string, end: string, maxHours: number): string | null {
  const s = utcIso(start), e = utcIso(end);
  if (!s || !e) return "Enter the window start and end.";
  const hours = (Date.parse(e) - Date.parse(s)) / 3_600_000;
  if (hours <= 0) return "The window end must be after its start.";
  if (hours > maxHours) return `The window is ${hours.toFixed(1)} h; at most ${maxHours} h.`;
  if (Date.parse(e) > Date.now() + 5 * 60_000) return "The window ends in the future.";
  return null;
}

export const STATE_LABEL: Record<ConnectionState, { label: string; tone: "success" | "danger" | "warn" | "neutral" }> = {
  ok: { label: "Connected", tone: "success" },
  partial: { label: "Partly readable", tone: "warn" },
  auth_error: { label: "Authentication failed", tone: "danger" },
  permission_denied: { label: "Permission missing", tone: "danger" },
  rate_limited: { label: "Rate-limited", tone: "warn" },
  unavailable: { label: "Unavailable", tone: "warn" },
  error: { label: "Error", tone: "danger" },
  not_configured: { label: "Not configured", tone: "neutral" },
};

/** User-facing explanation for a failed query, by error kind. */
/** v0.10: an empty Azure Monitor answer cannot be told apart from data the identity may not read (restricted tables
 * answer with zero rows), so it is never shown as "no data". */
export const AZURE_EMPTY_LABEL = "no accessible records";

/** v0.11: a CloudWatch template selected for a service without that resource mapped is never sent to AWS. */
export const NOT_QUERIED_LABEL = "not queried (no mapping)";

export function queryStatusLabel(
  q: Pick<QueryProvenance, "status" | "connector" | "returned" | "error"> & Partial<Pick<QueryProvenance, "aws" | "truncated">>,
): string {
  if (q.status === "error" && q.aws?.not_queried) return NOT_QUERIED_LABEL;
  if (q.status === "error") return q.error?.kind.replace("_", " ") ?? "error";
  if (q.connector === "cloudwatch" && q.aws?.partial) return `${q.returned} records (partial)`;
  if (q.status === "empty") return q.connector === "azure_monitor" ? AZURE_EMPTY_LABEL : "no data";
  return `${q.returned} records`;
}

export function queryErrorHint(q: QueryProvenance): string {
  switch (q.error?.kind) {
    case "auth_error": return "Authentication failed: check the read-only credentials or tenant in the API settings.";
    case "permission_denied": return q.connector === "azure_monitor"
      ? "The identity may not query this workspace: assign Log Analytics Data Reader on it."
      : q.connector === "cloudwatch"
        ? "AWS denied the read: grant the action shown (logs:StartQuery/GetQueryResults on the log group, or cloudwatch:GetMetricData) to the read-only role."
        : "The credentials were accepted but may not read this product: grant the read permission shown.";
    case "not_configured": return q.connector === "cloudwatch"
      ? "Not sent to AWS: map this resource for the service in CLOUDWATCH_RESOURCES_FILE to collect it."
      : q.error?.message ?? "";
    case "unsupported": return q.connector === "azure_monitor"
      ? "This table is not in the workspace, so this signal stays unknown for the service."
      : "This product is not available for the account or site.";
    case "not_found": return q.connector === "cloudwatch"
      ? "The log group does not exist in this region and account: check the mapping and CLOUDWATCH_REGION."
      : "The workspace or API path was not found: check the configured identifier.";
    case "rate_limited": return "The provider rate-limited the query; retry later or select fewer templates or services.";
    case "unavailable": case "timeout": return q.connector === "cloudwatch"
      ? "The Logs Insights query did not complete (timed out, cancelled or AWS unavailable); OpsPilot stopped its own query. Narrow the window."
      : "The backend is unavailable or did not answer in time.";
    case "query_error": return "The backend rejected the template's query: it may not fit this backend's metric names.";
    case "redirect_refused": return "The backend redirected; point the URL at the API itself.";
    case "response_too_large": return "The answer was too large: narrow the window.";
    default: return q.error?.message ?? "";
  }
}
