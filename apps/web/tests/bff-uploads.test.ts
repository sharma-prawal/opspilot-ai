// v0.5: uploaded-evidence routes go through the same BFF checks, are operator-only and have a bounded body size.
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "@/app/api/ops/[...path]/route";
import { issueSession } from "@/lib/server/auth";

const ORIGIN = "http://127.0.0.1:3000";
const INCIDENT = "11111111-2222-3333-4444-555555555555";
let upstream: string[] = [];

beforeEach(() => {
  process.env.OPSPILOT_WEB_SESSION_SECRET = "s".repeat(48);
  process.env.OPSPILOT_WEB_OPERATOR_PASSPHRASE = "correct horse battery";
  process.env.OPERATOR_TOKEN = "SENTINEL-BACKEND-OPERATOR-TOKEN-0123456789";
  upstream = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    upstream.push(url);
    return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
  }));
});
afterEach(() => vi.unstubAllGlobals());

const ctx = (path: string) => ({ params: Promise.resolve({ path: path.split("/") }) }) as never;

function post(path: string, role: "viewer" | "operator", body = "{}") {
  const { value, session } = issueSession("alice", role);
  return new NextRequest(`${ORIGIN}/api/ops/${path}`, {
    method: "POST",
    body,
    headers: {
      origin: ORIGIN, host: "127.0.0.1:3000", "content-type": "application/json", "sec-fetch-site": "same-origin",
      cookie: `opspilot_session=${value}`, "x-opspilot-csrf": session.csrf,
    },
  });
}

const ROUTES = ["api/v1/incidents/upload/preview", "api/v1/incidents/upload", `api/v1/incidents/${INCIDENT}/discard`];

describe("BFF upload routes", () => {
  it("are operator-only", async () => {
    for (const path of ROUTES) expect((await POST(post(path, "viewer"), ctx(path))).status, path).toBe(403);
    expect(upstream).toHaveLength(0);
    for (const path of ROUTES) expect((await POST(post(path, "operator"), ctx(path))).status, path).toBe(200);
    expect(upstream).toHaveLength(3);
  });

  it("refuses an oversized body before contacting the backend", async () => {
    const huge = JSON.stringify({ files: [{ name: "a.log", content: "x".repeat(13 * 1024 * 1024) }] });
    const res = await POST(post(ROUTES[0], "operator", huge), ctx(ROUTES[0]));
    expect(res.status).toBe(413);
    expect(upstream).toHaveLength(0);
  });

  it("does not open other incident sub-paths for mutation", async () => {
    const path = `api/v1/incidents/${INCIDENT}/dataset`;
    expect((await POST(post(path, "operator"), ctx(path))).status).toBe(404);
  });
});
