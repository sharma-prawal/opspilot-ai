import { describe, expect, it } from "vitest";
import { defaultServiceFor, fileProblem, normalizeService, parseServices, UPLOAD_LIMITS } from "./uploads";

describe("upload helpers", () => {
  it("normalizes service names the way the API accepts them", () => {
    expect(normalizeService("  Checkout API ")).toBe("checkout-api");
    expect(normalizeService("9lives")).toBe("lives");
    expect(normalizeService("x")).toBeNull();
    expect(parseServices("payment-service, Ledger  ??")).toEqual({ services: ["payment-service", "ledger"], invalid: ["??"] });
  });

  it("flags unsupported, empty and oversized files before reading them", () => {
    expect(fileProblem({ name: "run.sh", size: 10 })).toMatch(/Unsupported/);
    expect(fileProblem({ name: "a.log", size: 0 })).toMatch(/empty/);
    expect(fileProblem({ name: "a.CSV", size: UPLOAD_LIMITS.maxFileBytes + 1 })).toMatch(/limit/);
    expect(fileProblem({ name: "trace.json", size: 100 })).toBeNull();
  });

  it("defaults only text logs to the incident's service", () => {
    expect(defaultServiceFor("app.log", "checkout-api")).toBe("checkout-api");
    expect(defaultServiceFor("metrics.csv", "checkout-api")).toBe("");
  });
});
