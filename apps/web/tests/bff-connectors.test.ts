// v0.6/v0.9: connector routes contact the configured Loki/Prometheus/Datadog, so they are operator-only and limited
// to the implemented connectors; the backend operator token never reaches the browser.
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET, POST } from "@/app/api/ops/[...path]/route";
import { issueSession } from "@/lib/server/auth";

const ORIGIN = "http://127.0.0.1:3000";
const TOKEN = "SENTINEL-BACKEND-OPERATOR-TOKEN-0123456789";
let upstream: { url: string; auth: string | undefined }[] = [];

beforeEach(() => {
  process.env.OPSPILOT_WEB_SESSION_SECRET = "s".repeat(48);
  process.env.OPSPILOT_WEB_OPERATOR_PASSPHRASE = "correct horse battery";
  process.env.OPERATOR_TOKEN = TOKEN;
  upstream = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    upstream.push({ url, auth: (init?.headers as Record<string, string> | undefined)?.authorization });
    return new Response('{"connectors": []}', { status: 200, headers: { "content-type": "application/json" } });
  }));
});
afterEach(() => vi.unstubAllGlobals());

const ctx = (path: string) => ({ params: Promise.resolve({ path: path.split("/") }) }) as never;

function req(path: string, role: "viewer" | "operator", method = "POST") {
  const { value, session } = issueSession("alice", role);
  return new NextRequest(`${ORIGIN}/api/ops/${path}`, {
    method,
    body: method === "POST" ? "{}" : undefined,
    headers: {
      origin: ORIGIN, host: "127.0.0.1:3000", "content-type": "application/json", "sec-fetch-site": "same-origin",
      cookie: `opspilot_session=${value}`, "x-opspilot-csrf": session.csrf,
    },
  });
}

const ROUTES = [
  "api/v1/connectors/loki/test",
  "api/v1/connectors/prometheus/services",
  "api/v1/connectors/datadog/test",
  "api/v1/connectors/datadog/services",
  "api/v1/incidents/connected/preview",
  "api/v1/incidents/connected",
];

describe("BFF connector routes", () => {
  it("are operator-only", async () => {
    for (const path of ROUTES) expect((await POST(req(path, "viewer"), ctx(path))).status, path).toBe(403);
    expect(upstream).toHaveLength(0);
    for (const path of ROUTES) expect((await POST(req(path, "operator"), ctx(path))).status, path).toBe(200);
    expect(upstream.map((u) => u.url.replace(/^https?:\/\/[^/]+\//, ""))).toEqual(ROUTES);
  });

  it("let any signed-in role read the connector list, without the backend token", async () => {
    const res = await GET(req("api/v1/connectors", "viewer", "GET"), ctx("api/v1/connectors"));
    expect(res.status).toBe(200);
    expect(upstream[0].auth).toBeUndefined();
    expect(await res.text()).not.toContain(TOKEN);
  });

  it("refuse other connectors and sub-paths", async () => {
    for (const path of [
      "api/v1/connectors/splunk/test", "api/v1/connectors/loki/push", "api/v1/connectors/loki/test/x",
      "api/v1/connectors/datadog/query", "api/v1/connectors/datadog/test/x", "api/v1/connectors/datadog",
    ]) {
      expect((await POST(req(path, "operator"), ctx(path))).status, path).toBe(404);
    }
    expect(upstream).toHaveLength(0);
  });
});
