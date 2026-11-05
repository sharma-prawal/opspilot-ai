// Operator sign-in for the BFF. POST {name, passphrase} -> session cookie; GET -> session info incl. the
// CSRF token (the cookie itself is HttpOnly); DELETE -> sign out.
import {
  AuthError, SESSION_COOKIE, assertCsrf, assertSafeMutation, assertSameOrigin, checkPassphrase, cookieAttributes, cookieValue, errorResponse,
  issueSession, readSession, throttle, throttled,
} from "@/lib/server/auth";

const NAME = /^[\w.@ -]{1,64}$/;

export async function POST(req: Request): Promise<Response> {
  try {
    assertSafeMutation(req, null); // no session yet: origin + content-type checks only
    const key = req.headers.get("x-forwarded-for") ?? "local";
    if (throttled(key)) throw new AuthError(429, "throttled", "too many failed sign-in attempts; retry later");
    let body: { name?: unknown; passphrase?: unknown };
    try { body = await req.json(); } catch { throw new AuthError(415, "unsupported_media_type", "invalid JSON body"); }
    const name = typeof body.name === "string" ? body.name.trim() : "";
    const passphrase = typeof body.passphrase === "string" ? body.passphrase : "";
    if (!NAME.test(name)) throw new AuthError(401, "invalid_credentials", "name is required");
    const role = checkPassphrase(passphrase);
    throttle(key, role === null);
    if (!role) throw new AuthError(401, "invalid_credentials", "invalid passphrase");
    const { value, session } = issueSession(name, role);
    return Response.json({ authenticated: true, sub: session.sub, role: session.role, csrf: session.csrf, exp: session.exp },
      { headers: { "set-cookie": `${SESSION_COOKIE}=${value}; ${cookieAttributes(req)}` } });
  } catch (e) {
    if (e instanceof AuthError) return errorResponse(e);
    throw e;
  }
}

export async function GET(req: Request): Promise<Response> {
  try {
    const s = readSession(cookieValue(req));
    if (!s) return Response.json({ authenticated: false }, { status: 401 });
    return Response.json({ authenticated: true, sub: s.sub, role: s.role, csrf: s.csrf, exp: s.exp });
  } catch (e) {
    if (e instanceof AuthError) return errorResponse(e);
    throw e;
  }
}

export async function DELETE(req: Request): Promise<Response> {
  try {
    const s = readSession(cookieValue(req));
    if (s) {
      assertSameOrigin(req);
      assertCsrf(req, s);
    }
    return Response.json({ authenticated: false },
      { headers: { "set-cookie": `${SESSION_COOKIE}=; ${cookieAttributes(req, 0)}` } });
  } catch (e) {
    if (e instanceof AuthError) return errorResponse(e);
    throw e;
  }
}
