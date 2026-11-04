// Backend-for-frontend proxy. Forwards a strict allowlist of API paths to the OpsPilot API and
// injects the operator token server-side for state-changing requests. The browser never sees it.
import type { NextRequest } from "next/server";

const API = process.env.OPSPILOT_API_URL ?? "http://127.0.0.1:8000";
const ALLOWED = /^(api\/v1\/(system|knowledge|incidents|investigations|approvals)(\/[\w\-./]*)?|health\/(live|ready|dependencies))$/;

async function forward(req: NextRequest, ctx: RouteContext<"/api/ops/[...path]">): Promise<Response> {
  const { path } = await ctx.params;
  const joined = path.join("/");
  if (!ALLOWED.test(joined) || joined.includes("..")) {
    return Response.json({ error: { class: "not_found", message: "unknown API path" } }, { status: 404 });
  }
  const headers: Record<string, string> = { "content-type": "application/json" };
  const rid = req.headers.get("x-request-id");
  if (rid) headers["x-request-id"] = rid;
  if (req.method === "POST" && process.env.OPERATOR_TOKEN) headers.authorization = `Bearer ${process.env.OPERATOR_TOKEN}`;
  try {
    const upstream = await fetch(`${API}/${joined}${req.nextUrl.search}`, {
      method: req.method,
      headers,
      body: req.method === "POST" ? await req.text() : undefined,
      cache: "no-store",
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return Response.json({ error: { class: "unavailable", message: `OpsPilot API unreachable at ${API}` } }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
