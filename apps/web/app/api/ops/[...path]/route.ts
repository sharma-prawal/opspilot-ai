// Backend-for-frontend proxy (audit finding H1).
//
// Every request requires a valid session. Mutations also require same-origin, a session-bound CSRF token
// and application/json. Authorization is per route: viewers may read and search; operator actions require
// the operator role. The backend operator token is attached server-side only after these checks and is
// never returned to the browser. Operator identity for decisions/cancellations comes from the session,
// not from the request body.
import type { NextRequest } from "next/server";
import {
  AuthError, assertSafeMutation, cookieValue, errorResponse, readSession, type Role, type Session,
} from "@/lib/server/auth";

const API = process.env.OPSPILOT_API_URL ?? "http://127.0.0.1:8000";
const READABLE = /^(api\/v1\/(system|knowledge|incidents|investigations|approvals)(\/[\w\-./]*)?|health\/(live|ready|dependencies))$/;

interface Rule { pattern: RegExp; role: Role; identity?: "decided_by" | "actor" }
const MUTATIONS: Rule[] = [
  { pattern: /^api\/v1\/knowledge\/search$/, role: "viewer" },
  { pattern: /^api\/v1\/knowledge\/ingest$/, role: "operator" },
  { pattern: /^api\/v1\/incidents\/simulate$/, role: "operator" },
  { pattern: /^api\/v1\/incidents\/[0-9a-f-]{36}\/investigations$/, role: "operator" },
  { pattern: /^api\/v1\/investigations\/[0-9a-f-]{36}\/resume$/, role: "operator" },
  { pattern: /^api\/v1\/investigations\/[0-9a-f-]{36}\/cancel$/, role: "operator", identity: "actor" },
  { pattern: /^api\/v1\/approvals\/[0-9a-f-]{36}\/decision$/, role: "operator", identity: "decided_by" },
];
const RANK: Record<Role, number> = { viewer: 0, operator: 1 };

function authenticate(req: Request): Session {
  const session = readSession(cookieValue(req));
  if (!session) throw new AuthError(401, "unauthenticated", "sign in required");
  return session;
}

async function upstream(req: NextRequest, joined: string, body: string | undefined): Promise<Response> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const rid = req.headers.get("x-request-id");
  if (rid && /^[\w-]{1,64}$/.test(rid)) headers["x-request-id"] = rid;
  if (req.method === "POST") {
    const token = process.env.OPERATOR_TOKEN ?? "";
    if (token.length < 16) throw new AuthError(503, "backend_auth_not_configured", "OPERATOR_TOKEN not configured");
    headers.authorization = `Bearer ${token}`;
  }
  try {
    const res = await fetch(`${API}/${joined}${req.nextUrl.search}`, { method: req.method, headers, body, cache: "no-store" });
    // Only status, content-type and body are relayed; no upstream headers (e.g. cookies) pass through.
    return new Response(res.body, { status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json", "cache-control": "no-store" } });
  } catch {
    return Response.json({ error: { class: "unavailable", message: "OpsPilot API unreachable" } }, { status: 502 });
  }
}

async function handle(req: NextRequest, ctx: RouteContext<"/api/ops/[...path]">): Promise<Response> {
  try {
    const { path } = await ctx.params;
    const joined = path.join("/");
    if (!READABLE.test(joined) || joined.includes("..")) {
      return Response.json({ error: { class: "not_found", message: "unknown API path" } }, { status: 404 });
    }
    const session = authenticate(req);
    if (req.method === "GET") return await upstream(req, joined, undefined);

    const rule = MUTATIONS.find((r) => r.pattern.test(joined));
    if (!rule) return Response.json({ error: { class: "not_found", message: "unknown API path" } }, { status: 404 });
    assertSafeMutation(req, session);
    if (RANK[session.role] < RANK[rule.role]) {
      throw new AuthError(403, "forbidden", `role ${session.role} may not perform this operation`);
    }
    let payload: unknown = {};
    const raw = await req.text();
    if (raw) {
      try { payload = JSON.parse(raw); } catch { throw new AuthError(415, "unsupported_media_type", "invalid JSON body"); }
    }
    if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
      throw new AuthError(415, "unsupported_media_type", "JSON object body required");
    }
    if (rule.identity) (payload as Record<string, unknown>)[rule.identity] = session.sub; // attributable, not spoofable
    return await upstream(req, joined, JSON.stringify(payload));
  } catch (e) {
    if (e instanceof AuthError) return errorResponse(e);
    throw e;
  }
}

export const GET = handle;
export const POST = handle;
