// Server-only authentication for the BFF (audit finding H1). Never import from client components.
//
// Local operators authenticate once with a passphrase configured in .env; the BFF then issues an
// HMAC-signed, HttpOnly, SameSite=Strict session cookie. Mutations additionally require:
//   - same-origin Origin (and Sec-Fetch-Site when the browser sends it),
//   - a CSRF token bound to the session (double-submit via the x-opspilot-csrf header),
//   - Content-Type: application/json.
// If the auth secrets are not configured, every request fails closed (503); there is no bypass.
import { createHmac, randomBytes, timingSafeEqual, createHash } from "node:crypto";

export type Role = "viewer" | "operator";
export interface Session { sub: string; role: Role; exp: number; csrf: string }

export const SESSION_COOKIE = "opspilot_session";
export const CSRF_HEADER = "x-opspilot-csrf";
const SESSION_TTL_S = 8 * 3600;

export class AuthError extends Error {
  constructor(public status: 401 | 403 | 415 | 429 | 503, public klass: string, message: string) { super(message); }
}

interface AuthConfig { sessionSecret: string; operatorPassphrase: string; viewerPassphrase?: string; expectedOrigin?: string }

export function authConfig(): AuthConfig {
  const sessionSecret = process.env.OPSPILOT_WEB_SESSION_SECRET ?? "";
  const operatorPassphrase = process.env.OPSPILOT_WEB_OPERATOR_PASSPHRASE ?? "";
  if (sessionSecret.length < 32 || operatorPassphrase.length < 12) {
    throw new AuthError(503, "auth_not_configured",
      "web authentication is not configured (OPSPILOT_WEB_SESSION_SECRET >= 32 chars, OPSPILOT_WEB_OPERATOR_PASSPHRASE >= 12 chars)");
  }
  return { sessionSecret, operatorPassphrase, viewerPassphrase: process.env.OPSPILOT_WEB_VIEWER_PASSPHRASE || undefined,
           expectedOrigin: process.env.OPSPILOT_WEB_ORIGIN || undefined };
}

const b64 = (b: Buffer) => b.toString("base64url");
const sign = (secret: string, body: string) => b64(createHmac("sha256", secret).update(body).digest());
const digestEq = (a: string, b: string) =>
  timingSafeEqual(createHash("sha256").update(a).digest(), createHash("sha256").update(b).digest());

export function issueSession(sub: string, role: Role, now = Date.now()): { value: string; session: Session } {
  const { sessionSecret } = authConfig();
  const session: Session = { sub, role, exp: Math.floor(now / 1000) + SESSION_TTL_S, csrf: b64(randomBytes(24)) };
  const body = b64(Buffer.from(JSON.stringify(session)));
  return { value: `${body}.${sign(sessionSecret, body)}`, session };
}

export function readSession(cookieValue: string | undefined, now = Date.now()): Session | null {
  const { sessionSecret } = authConfig();
  if (!cookieValue) return null;
  const [body, sig] = cookieValue.split(".");
  if (!body || !sig || !digestEq(sig, sign(sessionSecret, body))) return null;
  try {
    const s = JSON.parse(Buffer.from(body, "base64url").toString()) as Session;
    if (typeof s.exp !== "number" || s.exp <= Math.floor(now / 1000)) return null;
    if (s.role !== "viewer" && s.role !== "operator") return null;
    return s;
  } catch {
    return null;
  }
}

export function checkPassphrase(passphrase: string): Role | null {
  const cfg = authConfig();
  if (digestEq(passphrase, cfg.operatorPassphrase)) return "operator";
  if (cfg.viewerPassphrase && digestEq(passphrase, cfg.viewerPassphrase)) return "viewer";
  return null;
}

export function cookieAttributes(req: Request, maxAge = SESSION_TTL_S): string {
  const secure = new URL(req.url).protocol === "https:" || process.env.NODE_ENV === "production";
  return `Path=/; HttpOnly; SameSite=Strict; Max-Age=${maxAge}${secure ? "; Secure" : ""}`;
}

export function cookieValue(req: Request, name = SESSION_COOKIE): string | undefined {
  const raw = req.headers.get("cookie") ?? "";
  for (const part of raw.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return v.join("=");
  }
  return undefined;
}

/** Origins this server answers on: OPSPILOT_WEB_ORIGIN if set, else the scheme + Host the browser used.
 * (req.url may be normalised by the framework, e.g. 127.0.0.1 -> localhost, so Host is authoritative.) */
function expectedOrigins(req: Request): Set<string> {
  const configured = authConfig().expectedOrigin;
  if (configured) return new Set([configured]);
  const url = new URL(req.url);
  const host = req.headers.get("host");
  const proto = (req.headers.get("x-forwarded-proto") ?? url.protocol.replace(":", "")).split(",")[0].trim();
  return new Set([url.origin, ...(host ? [`${proto}://${host}`] : [])]);
}

export function assertSameOrigin(req: Request): void {
  const origin = req.headers.get("origin");
  if (!origin || !expectedOrigins(req).has(origin)) {
    throw new AuthError(403, "cross_origin", "cross-origin or missing Origin");
  }
  const site = req.headers.get("sec-fetch-site");
  if (site && site !== "same-origin") throw new AuthError(403, "cross_origin", `Sec-Fetch-Site ${site} not allowed`);
}

export function assertJson(req: Request): void {
  const ctype = (req.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (ctype !== "application/json") throw new AuthError(415, "unsupported_media_type", "Content-Type must be application/json");
}

export function assertCsrf(req: Request, session: Session): void {
  const token = req.headers.get(CSRF_HEADER) ?? "";
  if (!token || !digestEq(token, session.csrf)) throw new AuthError(403, "csrf", "missing or invalid CSRF token");
}

/** Same-origin + JSON (+ CSRF when a session exists) for any state-changing request. Origin checks alone
 * are not authentication: callers must also hold a valid session (checked separately). */
export function assertSafeMutation(req: Request, session: Session | null): void {
  assertSameOrigin(req);
  assertJson(req);
  if (session) assertCsrf(req, session);
}

export function errorResponse(e: AuthError): Response {
  return Response.json({ error: { class: e.klass, message: e.message } }, { status: e.status });
}

// Simple per-process login throttle (local single-operator deployment).
const failures = new Map<string, { n: number; until: number }>();
export function throttle(key: string, failed: boolean, now = Date.now()): void {
  const f = failures.get(key);
  if (!failed) { failures.delete(key); return; }
  const n = (f && f.until > now ? f.n : 0) + 1;
  failures.set(key, { n, until: now + 5 * 60_000 });
}
export function throttled(key: string, now = Date.now()): boolean {
  const f = failures.get(key);
  return !!f && f.until > now && f.n >= 5;
}
