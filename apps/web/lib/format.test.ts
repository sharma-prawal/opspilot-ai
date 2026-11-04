import { describe, expect, it } from "vitest";
import { confidenceLabel, ms, pct, stageIndex, statusTone, utcTime } from "./format";

describe("format helpers", () => {
  it("formats percentages and missing values", () => {
    expect(pct(0.3891, 1)).toBe("38.9%");
    expect(pct(null)).toBe("—");
  });
  it("formats UTC timestamps deterministically", () => {
    expect(utcTime("2026-11-03T14:09:00+00:00")).toBe("2026-11-03 14:09:00Z");
    expect(utcTime("not a date")).toBe("—");
  });
  it("formats latency", () => {
    expect(ms(42.4)).toBe("42 ms");
    expect(ms(1530)).toBe("1.5 s");
  });
  it("maps statuses to tones", () => {
    expect(statusTone("awaiting_approval")).toBe("warn");
    expect(statusTone("succeeded")).toBe("success");
    expect(statusTone("unknown-status")).toBe("neutral");
  });
  it("labels confidence bands", () => {
    expect(confidenceLabel(0.95)).toBe("high");
    expect(confidenceLabel(0.6)).toBe("medium");
    expect(confidenceLabel(0.2)).toBe("low");
  });
  it("maps graph nodes to workflow stages", () => {
    expect(stageIndex("telemetry")).toBe(2);
    expect(stageIndex("await_approval")).toBe(4);
    expect(stageIndex("report")).toBe(6);
    expect(stageIndex(null)).toBe(-1);
  });
});
