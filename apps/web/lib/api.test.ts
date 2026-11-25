import { afterEach, expect, it, vi } from "vitest";
import { api, clearSession } from "./api";

afterEach(() => { vi.unstubAllGlobals(); clearSession(); });
it.each(["all", "%_!", "' OR 1=1 --"])("preserves literal search %s while omitting all-source/state sentinels", async q => {
  const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 }), {
    headers: { "content-type": "application/json" },
  }));
  vi.stubGlobal("fetch", fetcher);
  await api.searchIncidents({ q, source: "all", status: "all", limit: 50, offset: 0 });
  const url = new URL(String(fetcher.mock.calls[0][0]), "http://synthetic.test");
  expect(url.pathname).toBe("/api/ops/api/v1/incidents/search");
  expect(url.searchParams.get("q")).toBe(q);
  expect(url.searchParams.has("source")).toBe(false);
  expect(url.searchParams.has("status")).toBe(false);
  expect(url.searchParams.get("offset")).toBe("0");
});

it.each(["actions", "approvals", "decide"] as const)("uses persisted decision history after BFF redaction on %s", async endpoint => {
  const history = { decision: "approve", decided_by: "original-sre", decided_at: "2026-11-20T12:00:00Z" };
  const action = { status: "succeeded", authorization: "[REDACTED]", decision_history: history };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(
    url === "/api/session" ? { authenticated: true, csrf: "synthetic-csrf" }
      : endpoint === "decide" ? action : [action],
  ), { headers: { "content-type": "application/json" } })));
  const result = endpoint === "actions" ? await api.actions("saved")
    : endpoint === "approvals" ? await api.approvals("all")
      : [await api.decide("saved", { decision: "approve", params_hash: "a".repeat(64) })];
  expect(result[0].authorization).toEqual(history);
});

it.each([
  { authorization: "[REDACTED]" },
  { authorization: { decision: "approve" }, decision_history: null },
])("does not infer authorization from a redacted or explicitly missing history", async action => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([action]), {
    headers: { "content-type": "application/json" },
  })));
  expect((await api.actions("legacy"))[0].authorization).toBeNull();
});
