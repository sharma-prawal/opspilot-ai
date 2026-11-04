// Finding 10 regression: E2E refuses to run unless the stack reports the isolated test database.
import { describe, expect, it } from "vitest";
import { assertIsolated } from "@/e2e/isolation";

describe("E2E isolation guard", () => {
  it("accepts only the e2e instance on a *_test database", () => {
    expect(assertIsolated({ database: "opspilot_test", test_database: true, instance: "e2e" }, "t").database).toBe("opspilot_test");
  });
  it.each([
    [{ database: "opspilot", test_database: false, instance: "default" }, "not a *_test database"],
    [{ database: "opspilot_test", test_database: true, instance: "default" }, "not 'e2e'"],
    [{ database: "opspilot_test", test_database: false, instance: "e2e" }, "does not report a test database"],
    [null, "no identity"],
    [{}, "no identity"],
  ])("refuses %j", (identity, reason) => {
    expect(() => assertIsolated(identity as never, "t")).toThrow(reason);
  });
});
