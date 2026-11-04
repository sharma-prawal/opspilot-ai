// H1 regression: the BFF authenticates and authorizes callers before attaching backend credentials.
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST as login, GET as sessionInfo, DELETE as logout } from "@/app/api/session/route";
import { GET, POST } from "@/app/api/ops/[...path]/route";
import { issueSession } from "@/lib/server/auth";

const ORIGIN = "http://127.0.0.1:3000";
const TOKEN = "SENTINEL-BACKEND-OPERATOR-TOKEN-0123456789";
const ACTION = "11111111-2222-3333-4444-555555555555";
let upstream: { url: string; init: RequestInit }[] = [];

beforeEach(() => {
  process.env.OPSPILOT_WEB_SESSION_SECRET = "s".repeat(48);
  process.env.OPSPILOT_WEB_OPERATOR_PASSPHRASE = "correct horse battery";
  process.env.OPSPILOT_WEB_VIEWER_PASSPHRASE = "viewer passphrase 123";
  process.env.OPERATOR_TOKEN = TOKEN;
  delete process.env.OPSPILOT_WEB_ORIGIN;
  upstream = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    upstream.push({ url, init });
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json", "set-cookie": "evil=1" } });
  }));
});
afterEach(() => vi.unstubAllGlobals());

function ctx(path: string) {
  return { params: Promise.resolve({ path: path.split("/") }) } as never;
}

function req(path: string, init: { method?: string; body?: string; headers?: Record<string, string> } = {}) {
  return new NextRequest(`${ORIGIN}/api/ops/${path}`, { method: init.method ?? "GET", body: init.body, headers: init.headers });
}

function sessionCookie(role: "viewer" | "operator", sub = "alice") {
  const { value, session } = issueSession(sub, role);
  return { cookie: `opspilot_session=${value}`, csrf: session.csrf };
}

function mutation(path: string, role: "viewer" | "operator" | null, overrides: Record<string, string> = {}, body = "{}") {
  const h: Record<string, string> = { origin: ORIGIN, host: "127.0.0.1:3000", "content-type": "application/json",
                                      "sec-fetch-site": "same-origin" };
  if (role) {
    const s = sessionCookie(role);
    h.cookie = s.cookie;
    h["x-opspilot-csrf"] = s.csrf;
  }
  return req(path, { method: "POST", body, headers: { ...h, ...overrides } });
}

const decision = `api/v1/approvals/${ACTION}/decision`;

describe("BFF authentication and authorization", () => {
  it("rejects an unauthenticated POST and never contacts the backend", async () => {
    const res = await POST(mutation(decision, null), ctx(decision));
    expect(res.status).toBe(401);
    expect(upstream).toHaveLength(0);
  });

  it("rejects the audit's reproduction: cross-origin text/plain POST", async () => {
    const res = await POST(req(decision, { method: "POST", body: '{"decision":"approve"}',
      headers: { origin: "https://untrusted.example", "content-type": "text/plain" } }), ctx(decision));
    expect(res.status).toBe(401); // no session at all
    expect(upstream).toHaveLength(0);
  });

  it("rejects a cross-origin POST even with a valid session cookie", async () => {
    const res = await POST(mutation(decision, "operator", { origin: "https://untrusted.example" }), ctx(decision));
    expect(res.status).toBe(403);
    const site = await POST(mutation(decision, "operator", { "sec-fetch-site": "cross-site" }), ctx(decision));
    expect(site.status).toBe(403);
    expect(upstream).toHaveLength(0);
  });

  it("rejects unsupported content types", async () => {
    const res = await POST(mutation(decision, "operator", { "content-type": "text/plain" }), ctx(decision));
    expect(res.status).toBe(415);
    const form = await POST(mutation(decision, "operator", { "content-type": "application/x-www-form-urlencoded" }), ctx(decision));
    expect(form.status).toBe(415);
    expect(upstream).toHaveLength(0);
  });

  it("requires the session-bound CSRF token", async () => {
    const missing = await POST(mutation(decision, "operator", { "x-opspilot-csrf": "" }), ctx(decision));
    const wrong = await POST(mutation(decision, "operator", { "x-opspilot-csrf": "forged" }), ctx(decision));
    expect([missing.status, wrong.status]).toEqual([403, 403]);
    expect(upstream).toHaveLength(0);
  });

  it("rejects invalid, tampered and expired sessions", async () => {
    const bad = await GET(req("api/v1/incidents", { headers: { cookie: "opspilot_session=not.valid" } }), ctx("api/v1/incidents"));
    const { value } = issueSession("alice", "operator");
    const tampered = value.replace(/^[^.]+/, Buffer.from(JSON.stringify({ sub: "alice", role: "operator", exp: 9e9, csrf: "x" })).toString("base64url"));
    const t = await GET(req("api/v1/incidents", { headers: { cookie: `opspilot_session=${tampered}` } }), ctx("api/v1/incidents"));
    const expired = issueSession("alice", "operator", Date.now() - 9 * 3600 * 1000).value;
    const e = await GET(req("api/v1/incidents", { headers: { cookie: `opspilot_session=${expired}` } }), ctx("api/v1/incidents"));
    expect([bad.status, t.status, e.status]).toEqual([401, 401, 401]);
    expect(upstream).toHaveLength(0);
  });

  it("blocks privilege escalation: a viewer cannot decide, cancel, ingest or start", async () => {
    for (const path of [decision, `api/v1/investigations/${ACTION}/cancel`, "api/v1/knowledge/ingest",
                        `api/v1/incidents/${ACTION}/investigations`, "api/v1/incidents/simulate"]) {
      const res = await POST(mutation(path, "viewer"), ctx(path));
      expect(res.status, path).toBe(403);
    }
    expect(upstream).toHaveLength(0);
    const search = await POST(mutation("api/v1/knowledge/search", "viewer", {}, '{"query":"pool"}'), ctx("api/v1/knowledge/search"));
    expect(search.status).toBe(200); // read-only operation allowed for viewers
  });

  it("forwards an authorized operator request with server-side credentials and session identity", async () => {
    const res = await POST(mutation(decision, "operator", {}, '{"decision":"approve","decided_by":"mallory"}'), ctx(decision));
    expect(res.status).toBe(200);
    expect(upstream).toHaveLength(1);
    const sent = upstream[0];
    expect((sent.init.headers as Record<string, string>).authorization).toBe(`Bearer ${TOKEN}`);
    expect(JSON.parse(String(sent.init.body)).decided_by).toBe("alice"); // client-supplied identity overwritten
    const text = await res.text();
    expect(text).not.toContain(TOKEN);
    expect(res.headers.get("set-cookie")).toBeNull(); // upstream headers are not relayed
  });

  it("does not attach backend credentials to reads", async () => {
    const s = sessionCookie("viewer");
    const res = await GET(req("api/v1/incidents", { headers: { cookie: s.cookie } }), ctx("api/v1/incidents"));
    expect(res.status).toBe(200);
    expect((upstream[0].init.headers as Record<string, string>).authorization).toBeUndefined();
  });

  it("rejects unknown paths and non-object bodies", async () => {
    const unknown = await POST(mutation("api/v1/system/overview", "operator"), ctx("api/v1/system/overview"));
    expect(unknown.status).toBe(404);
    const traversal = await GET(req("api/v1/../../etc", { headers: { cookie: sessionCookie("operator").cookie } }), ctx("api/v1/../../etc"));
    expect(traversal.status).toBe(404);
    const arr = await POST(mutation(decision, "operator", {}, "[1,2]"), ctx(decision));
    expect(arr.status).toBe(415);
  });

  it("honours an explicitly configured origin", async () => {
    process.env.OPSPILOT_WEB_ORIGIN = "https://ops.internal.example";
    const res = await POST(mutation(decision, "operator"), ctx(decision)); // browser on 127.0.0.1:3000
    expect(res.status).toBe(403);
    const ok = await POST(mutation(decision, "operator", { origin: "https://ops.internal.example" }), ctx(decision));
    expect(ok.status).toBe(200);
  });

  it("fails closed when authentication is not configured", async () => {
    delete process.env.OPSPILOT_WEB_SESSION_SECRET;
    const res = await POST(mutation(decision, null), ctx(decision));
    expect(res.status).toBe(503);
    expect(upstream).toHaveLength(0);
  });
});

describe("sign-in endpoint", () => {
  const signIn = (body: unknown, headers: Record<string, string> = {}) =>
    login(new Request(`${ORIGIN}/api/session`, { method: "POST", body: JSON.stringify(body),
      headers: { origin: ORIGIN, host: "127.0.0.1:3000", "content-type": "application/json", ...headers } }));

  it("issues an HttpOnly SameSite=Strict session for the operator passphrase", async () => {
    const res = await signIn({ name: "alice", passphrase: "correct horse battery" });
    expect(res.status).toBe(200);
    const cookie = res.headers.get("set-cookie") ?? "";
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=Strict");
    const body = await res.json();
    expect(body.role).toBe("operator");
    expect(JSON.stringify(body)).not.toContain(TOKEN);
    const info = await sessionInfo(new Request(`${ORIGIN}/api/session`, { headers: { cookie: cookie.split(";")[0] } }));
    expect((await info.json()).csrf).toBe(body.csrf);
  });

  it("rejects wrong passphrases, cross-origin sign-in and throttles brute force", async () => {
    expect((await signIn({ name: "eve", passphrase: "nope" }, { "x-forwarded-for": "10.0.0.9" })).status).toBe(401);
    expect((await signIn({ name: "eve", passphrase: "correct horse battery" }, { origin: "https://evil.example" })).status).toBe(403);
    for (let i = 0; i < 5; i++) await signIn({ name: "eve", passphrase: "nope" }, { "x-forwarded-for": "10.0.0.7" });
    expect((await signIn({ name: "eve", passphrase: "correct horse battery" }, { "x-forwarded-for": "10.0.0.7" })).status).toBe(429);
  });

  it("assigns the viewer role for the viewer passphrase", async () => {
    const res = await signIn({ name: "bob", passphrase: "viewer passphrase 123" });
    expect((await res.json()).role).toBe("viewer");
  });

  it("logout requires same-origin and the CSRF token", async () => {
    const s = sessionCookie("operator");
    const forged = await logout(new Request(`${ORIGIN}/api/session`, { method: "DELETE", headers: { cookie: s.cookie, origin: ORIGIN, host: "127.0.0.1:3000" } }));
    expect(forged.status).toBe(403);
    const ok = await logout(new Request(`${ORIGIN}/api/session`, { method: "DELETE",
      headers: { cookie: s.cookie, origin: ORIGIN, host: "127.0.0.1:3000", "x-opspilot-csrf": s.csrf } }));
    expect(ok.status).toBe(200);
    expect(ok.headers.get("set-cookie")).toContain("Max-Age=0");
  });
});
