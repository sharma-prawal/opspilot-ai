// Finding E regression: credentials in upstream JSON never reach the browser through the BFF.
import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GET } from "@/app/api/ops/[...path]/route";
import { issueSession } from "@/lib/server/auth";
import { REDACTED, redact } from "@/lib/server/redact";

const SENTINEL = "eyJhaWQiOiJ4In0.SENTINEL-SIGNATURE";
const INV = "11111111-2222-3333-4444-555555555555";

beforeEach(() => {
  process.env.OPSPILOT_WEB_SESSION_SECRET = "s".repeat(48);
  process.env.OPSPILOT_WEB_OPERATOR_PASSPHRASE = "correct horse battery";
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([
    { tool: "execute_remediation", arguments: { action_id: "a", approval_token: SENTINEL } },
    { tool: "llm", usage: { prompt_tokens: 7 }, nested: [{ Authorization: `Bearer ${SENTINEL}` }] },
  ]), { status: 200, headers: { "content-type": "application/json" } })));
});
afterEach(() => vi.unstubAllGlobals());

it("redacts sensitive keys in relayed JSON and keeps counters", async () => {
  const { value } = issueSession("alice", "viewer");
  const req = new NextRequest(`http://127.0.0.1:3000/api/ops/api/v1/investigations/${INV}/tool-calls`,
    { headers: { cookie: `opspilot_session=${value}` } });
  const res = await GET(req, { params: Promise.resolve({ path: `api/v1/investigations/${INV}/tool-calls`.split("/") }) } as never);
  const text = await res.text();
  expect(res.status).toBe(200);
  expect(text).not.toContain("SENTINEL");
  const body = JSON.parse(text);
  expect(body[0].arguments).toEqual({ action_id: "a", approval_token: REDACTED });
  expect(body[1].usage.prompt_tokens).toBe(7);
});

it("matches the backend policy for nulls and nesting", () => {
  expect(redact({ approval_token: null, x: { session_secret: "v" } })).toEqual({ approval_token: null, x: { session_secret: REDACTED } });
});
