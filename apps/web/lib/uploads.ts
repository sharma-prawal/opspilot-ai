// Client-side helpers for "Analyze your own incident data" (v0.5). The API validates everything again; these
// checks only give fast feedback before a file is read.

export const UPLOAD_LIMITS = {
  maxFiles: 5,
  maxFileBytes: 5 * 1024 * 1024,
  maxTotalBytes: 8 * 1024 * 1024,
  extensions: [".log", ".txt", ".json", ".csv"],
} as const;

export const SERVICE_PATTERN = /^[a-z][a-z0-9-]{1,62}$/;

export interface ExampleFile { name: string; kind: string; description: string; service: string | null }

export const EXAMPLE_FILES: ExampleFile[] = [
  { name: "checkout-api.log", kind: "Text log", description: "checkout-api application log with payment timeouts and a stack trace", service: "checkout-api" },
  { name: "service-metrics.csv", kind: "CSV metrics", description: "Per-minute 5xx ratio, p95 latency and request rate for two services", service: null },
  { name: "change-events.json", kind: "JSON events", description: "Two deployments (one unrelated) and an alert", service: null },
  { name: "checkout-traces.json", kind: "OTLP/JSON traces", description: "Checkout → payment-service traces, before and after the failure", service: null },
];

export const EXAMPLE_INCIDENT = {
  title: "Checkout payments failing",
  description:
    "Customers report payment errors at checkout. The checkout error-rate alert fired at 09:16 UTC. (Synthetic example data.)",
  service: "checkout-api",
  affected: "payment-service",
  severity: "SEV2",
  time: "2026-11-12T09:16",
  timezone: "UTC",
};

export function extensionOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
}

/** Lower-case slug accepted as a service name, or null. */
export function normalizeService(raw: string): string | null {
  const s = raw.trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/-{2,}/g, "-").replace(/^[-0-9]+|-+$/g, "");
  return SERVICE_PATTERN.test(s) ? s : null;
}

export function parseServices(raw: string): { services: string[]; invalid: string[] } {
  const parts = raw.split(/[,\s]+/).map((p) => p.trim()).filter(Boolean);
  const services: string[] = [];
  const invalid: string[] = [];
  for (const p of parts) {
    const s = normalizeService(p);
    if (s) {
      if (!services.includes(s)) services.push(s);
    } else invalid.push(p);
  }
  return { services, invalid };
}

/** Problem with a picked file before it is read, or null. */
export function fileProblem(file: { name: string; size: number }): string | null {
  const ext = extensionOf(file.name);
  if (!(UPLOAD_LIMITS.extensions as readonly string[]).includes(ext)) {
    return `Unsupported type ${ext || "(none)"}; use ${UPLOAD_LIMITS.extensions.join(", ")}`;
  }
  if (file.size === 0) return "The file is empty";
  if (file.size > UPLOAD_LIMITS.maxFileBytes) {
    return `${formatBytes(file.size)} is over the ${formatBytes(UPLOAD_LIMITS.maxFileBytes)} limit`;
  }
  return null;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Text logs rarely name their service: default them to the incident's service (shown and editable). */
export function defaultServiceFor(name: string, incidentService: string): string {
  return [".log", ".txt"].includes(extensionOf(name)) ? incidentService : "";
}

export function timezoneOptions(): string[] {
  let local = "UTC";
  try {
    local = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch { /* older runtimes */ }
  return Array.from(
    new Set([
      "UTC", local, "Europe/London", "Europe/Berlin", "America/New_York", "America/Chicago", "America/Los_Angeles",
      "Asia/Kolkata", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney",
    ]),
  );
}

export function downloadText(filename: string, text: string, type = "text/markdown"): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
