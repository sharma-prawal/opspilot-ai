import type { Evidence, Incident } from "./types";

export const SOURCE_LABELS = {
  simulator: "Simulator",
  upload: "Uploaded files",
  connector: "Connected telemetry",
  unknown: "Unknown source",
};
export function sourceCounts(incidents: Incident[]) {
  const counts = { simulator: 0, upload: 0, connector: 0, unknown: 0 };
  for (const incident of incidents) {
    const source = incident.evidence_source;
    if (Object.hasOwn(counts, source)) counts[source]++;
    else counts.unknown++;
  }
  return Object.entries(counts).map(([key, count]) => ({
    key,
    label: SOURCE_LABELS[key as keyof typeof SOURCE_LABELS],
    count,
  }));
}
export function evidenceGroup(e: Evidence) {
  if (e.kind === "tool_error") return "Unavailable";
  if (e.kind.includes("metric") || e.source_tool === "query_metrics")
    return "Metrics";
  if (e.kind.includes("log") || e.source_tool === "search_logs") return "Logs";
  if (e.kind.includes("span") || e.kind.includes("trace")) return "Traces";
  if (["deployment", "config_change"].includes(e.kind)) return "Changes";
  if (e.citation || ["runbook", "knowledge"].includes(e.kind))
    return "Runbooks";
  if (
    [
      "dependency",
      "datastore",
      "queue",
      "service_health",
      "service_config",
    ].includes(e.kind)
  )
    return "Dependencies";
  return "Other";
}
export function metricValues(e: Evidence) {
  const d = e.data;
  return [
    { label: "Baseline", value: d.baseline },
    { label: "Extreme", value: d.extreme ?? d.peak },
    { label: "Current", value: d.current },
    { label: "Mean", value: d.mean },
  ].filter(
    (v): v is { label: string; value: number } =>
      typeof v.value === "number" && Number.isFinite(v.value),
  );
}
export function metricLabel(value: number, unit: string) {
  return unit === "ratio"
    ? `${Number((value * 100).toFixed(2))}%`
    : `${Number(value.toFixed(2))}${unit ? ` ${unit}` : ""}`;
}
export function sourceChronology(evidence: Evidence[]) {
  return evidence
    .filter((e) => e.observed_at && Number.isFinite(Date.parse(e.observed_at)))
    .sort((a, b) => Date.parse(a.observed_at!) - Date.parse(b.observed_at!));
}
