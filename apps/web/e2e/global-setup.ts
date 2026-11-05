// Runs once before any spec. Fails the whole run before any mutation unless both the API directly and the
// web BFF (as a signed-in browser would reach it) report the isolated E2E stack on a *_test database.
import { E2E_API_URL, E2E_WEB_URL, assertIsolated } from "./isolation";

export default async function globalSetup(): Promise<void> {
  const direct = await (await fetch(`${E2E_API_URL}/api/v1/system/identity`)).json();
  assertIsolated(direct, `API ${E2E_API_URL}`);

  const passphrase = process.env.OPSPILOT_WEB_OPERATOR_PASSPHRASE;
  if (!passphrase) throw new Error("OPSPILOT_WEB_OPERATOR_PASSPHRASE not set (run via `make e2e`)");
  const login = await fetch(`${E2E_WEB_URL}/api/session`, {
    method: "POST",
    headers: { "content-type": "application/json", origin: E2E_WEB_URL },
    body: JSON.stringify({ name: "e2e-identity-check", passphrase }),
  });
  if (!login.ok) throw new Error(`refusing to run E2E: sign-in to ${E2E_WEB_URL} failed (${login.status})`);
  const cookie = (login.headers.get("set-cookie") ?? "").split(";")[0];
  const viaBff = await (await fetch(`${E2E_WEB_URL}/api/ops/api/v1/system/identity`, { headers: { cookie } })).json();
  assertIsolated(viaBff, `web ${E2E_WEB_URL} -> BFF -> API`);
}
