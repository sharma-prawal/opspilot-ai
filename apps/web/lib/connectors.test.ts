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
