import { afterEach, expect, it, vi } from "vitest";
import { api } from "./api";

afterEach(() => vi.unstubAllGlobals());
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
