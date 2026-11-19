// Client helpers for connected observability (v0.6). The API validates everything again.
import type { ConnectionState, QueryProvenance } from "./types";

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
  auth_error: { label: "Authentication failed", tone: "danger" },
  unavailable: { label: "Unavailable", tone: "warn" },
  error: { label: "Error", tone: "danger" },
  not_configured: { label: "Not configured", tone: "neutral" },
};

/** User-facing explanation for a failed query, by error kind. */
export function queryErrorHint(q: QueryProvenance): string {
  switch (q.error?.kind) {
    case "auth_error": return "Authentication failed: check the read-only credentials or tenant in the API settings.";
    case "unavailable": case "timeout": return "The backend is unavailable or did not answer in time.";
    case "query_error": return "The backend rejected the template's query: it may not fit this backend's metric names.";
    case "redirect_refused": return "The backend redirected; point the URL at the API itself.";
    case "response_too_large": return "The answer was too large: narrow the window.";
    default: return q.error?.message ?? "";
  }
}
