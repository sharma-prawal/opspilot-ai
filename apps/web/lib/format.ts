// Pure presentation helpers (unit-tested in lib/format.test.ts).

export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function utcTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toISOString().replace("T", " ").slice(0, 19) + "Z";
}

export function ms(value: number): string {
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

export type Tone = "neutral" | "info" | "warn" | "danger" | "success";

const STATUS_TONE: Record<string, Tone> = {
  open: "warn", investigating: "info", awaiting_approval: "warn", mitigated: "success", resolved: "success",
  queued: "neutral", running: "info", completed: "success", failed: "danger", cancelled: "neutral", interrupted: "warn",
  pending: "warn", approved: "info", rejected: "neutral", executing: "info", succeeded: "success",
  ok: "success", error: "danger", timeout: "danger", healthy: "success", degraded: "warn", unhealthy: "danger",
};

export function statusTone(status: string | null | undefined): Tone {
  return (status && STATUS_TONE[status]) || "neutral";
}

export function confidenceLabel(c: number): "high" | "medium" | "low" {
  return c >= 0.75 ? "high" : c >= 0.5 ? "medium" : "low";
}

export const ACTIVE_STATUSES = new Set(["queued", "running"]);

/** Ordered stages shown in the workflow stepper. */
export const STAGES = [
  { key: "intake", label: "Intake" },
  { key: "plan", label: "Plan" },
  { key: "evidence", label: "Gather evidence", nodes: ["dispatch", "telemetry", "dependencies", "changes", "knowledge", "followup"] },
  { key: "rca", label: "Root cause" },
  { key: "approval", label: "Approval", nodes: ["propose", "await_approval"] },
  { key: "remediate", label: "Remediate", nodes: ["execute", "verify"] },
  { key: "report", label: "Report", nodes: ["report", "failed"] },
] as const;

export function stageIndex(node: string | null | undefined): number {
  if (!node) return -1;
  return STAGES.findIndex((s) => s.key === node || ("nodes" in s && (s.nodes as readonly string[]).includes(node)));
}

export function humanize(s: string): string {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
