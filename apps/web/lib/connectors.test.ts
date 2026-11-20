import { describe, expect, it } from "vitest";
import { defaultWindow, shiftLocal, utcIso, windowProblem } from "./connectors";

describe("connected telemetry helpers", () => {
  it("reads datetime-local values as UTC", () => {
    expect(utcIso("2026-11-12T09:16")).toBe("2026-11-12T09:16:00Z");
    expect(utcIso("soon")).toBeNull();
    expect(shiftLocal("2026-11-12T00:10", -30)).toBe("2026-11-11T23:40");
  });

  it("defaults the window to what the investigation examines", () => {
    expect(defaultWindow("2026-11-12T09:16")).toEqual({ start: "2026-11-12T06:16", end: "2026-11-12T09:46" });
  });

  it("checks the window", () => {
    expect(windowProblem("2026-11-12T06:16", "2026-11-12T09:46", 6)).toBeNull();
    expect(windowProblem("2026-11-12T01:00", "2026-11-12T09:46", 6)).toMatch(/at most 6 h/);
    expect(windowProblem("2026-11-12T09:46", "2026-11-12T06:16", 6)).toMatch(/after its start/);
    expect(windowProblem("", "2026-11-12T06:16", 6)).toMatch(/Enter/);
  });
});

describe("v0.9 Datadog helpers", () => {
  it("breaks a series where the provider returned no value, never bridging the gap", async () => {
    const { seriesRuns } = await import("./connectors");
    const s = {
      service: "orders-api", metric: "http_5xx_ratio", unit: "ratio", query: "datadog/http_5xx_ratio/orders-api",
      step_seconds: 60, count: 4, omitted: null,
      points: [["2026-11-15T13:18:00Z", 0.01], ["2026-11-15T13:19:00Z", 0.02], ["2026-11-15T13:23:00Z", 0.01],
        ["2026-11-15T13:24:00Z", 0.03]] as [string, number][],
    };
    const runs = seriesRuns(s);
    expect(runs).toHaveLength(2);
    expect(runs.flat()).toHaveLength(4); // every returned point, none added
  });

  it("reads the signals of a connector and template", async () => {
    const { signalsOf, templateSignal } = await import("./connectors");
    expect(signalsOf({ id: "loki", kind: "loki", name: "Loki", signal: "log", configured: true })).toEqual(["log"]);
    expect(signalsOf({ id: "datadog", kind: "datadog", name: "Datadog", signal: "log", signals: ["log", "metric", "span"], configured: true }))
      .toEqual(["log", "metric", "span"]);
    const base = { id: "x", label: "x", description: "", query: "", metric: null, unit: "", default: true, source: "built-in" as const };
    expect(templateSignal({ ...base, connector: "prometheus" })).toBe("metric");
    expect(templateSignal({ ...base, connector: "datadog", signal: "span" })).toBe("span");
  });
});

describe("v0.9 connected service names", () => {
  it("keeps Datadog service names exactly instead of rewriting them", async () => {
    const { connectedService, parseConnectedServices } = await import("./connectors");
    expect(connectedService(" Billing.Worker_v2 ")).toBe("billing.worker_v2");
    expect(connectedService("orders-api")).toBe("orders-api");
    for (const bad of ["orders-api OR service:*", "svc*", "svc:prod", "a b", "svc/1", "-x", "1x", "a".repeat(64)]) {
      expect(connectedService(bad), bad).toBeNull();
    }
    expect(parseConnectedServices("web_store, api.v2-internal, bad*name")).toEqual({
      services: ["web_store", "api.v2-internal"], invalid: ["bad*name"],
    });
  });
});

describe("v0.10 Azure Monitor helpers", () => {
  it("names Azure signals after Application Insights and keeps other providers unchanged", async () => {
    const { signalLabel, TABLE_STATE, STATE_LABEL, queryErrorHint } = await import("./connectors");
    expect(signalLabel("span", "azure_monitor")).toBe("Requests & dependencies");
    expect(signalLabel("log", "azure_monitor")).toBe("Traces & exceptions");
    expect(signalLabel("span", "datadog")).toBe("APM spans");
    expect(signalLabel("metric", "prometheus")).toBe("Metrics");
    expect(TABLE_STATE.unsupported.label).toBe("not in workspace");
    expect(STATE_LABEL.permission_denied.tone).toBe("danger");
    const q = { connector: "azure_monitor", error: { kind: "permission_denied", message: "HTTP 403" } } as never;
    expect(queryErrorHint(q)).toContain("Log Analytics Data Reader");
    const dd = { connector: "datadog", error: { kind: "permission_denied", message: "HTTP 403" } } as never;
    expect(queryErrorHint(dd)).toContain("read permission shown");
  });

  it("keeps Application Insights role names exactly (lower-cased), refusing names that cannot be queried", async () => {
    const { connectedService, parseConnectedServices } = await import("./connectors");
    expect(connectedService("Billing.Worker")).toBe("billing.worker");
    expect(connectedService("Notification Worker")).toBeNull();
    expect(parseConnectedServices("payment-service, inventory-service").services).toEqual(["payment-service", "inventory-service"]);
  });
});
