// E2E isolation (audit finding 10): every run gets its own API (opspilot_test) and web server, and nothing is
// mutated until the browser -> BFF -> API -> database chain is verified to be that isolated stack.

export interface Identity { database: string; test_database: boolean; instance: string }

export const E2E_API_PORT = Number(process.env.E2E_API_PORT ?? 8100);
export const E2E_WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3100);
export const E2E_API_URL = `http://127.0.0.1:${E2E_API_PORT}`;
export const E2E_WEB_URL = `http://127.0.0.1:${E2E_WEB_PORT}`;

/** Throws unless the identity reported by the stack is the isolated E2E instance on a test database. */
export function assertIsolated(identity: Partial<Identity> | null | undefined, via: string): Identity {
  const problems: string[] = [];
  if (!identity || typeof identity.database !== "string") problems.push("no identity reported");
  else {
    if (!identity.database.endsWith("_test")) problems.push(`database is '${identity.database}', not a *_test database`);
    if (identity.test_database !== true) problems.push("API does not report a test database");
    if (identity.instance !== "e2e") problems.push(`instance is '${identity.instance}', not 'e2e'`);
  }
  if (problems.length) throw new Error(`refusing to run E2E (${via}): ${problems.join("; ")}`);
  return identity as Identity;
}
