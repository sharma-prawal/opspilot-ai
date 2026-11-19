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
