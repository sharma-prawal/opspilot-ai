// Mirror of opspilot_shared/redaction.py (audit finding E): defence in depth so a credential that reaches
// the BFF in a JSON body (e.g. from an older backend or legacy rows) is never relayed to the browser.
export const REDACTED = "[REDACTED]";
const SENSITIVE_PARTS = ["token", "password", "passphrase", "secret", "signing_key", "authorization", "api_key",
  "cookie", "credential"];
const SAFE_KEYS = new Set(["prompt_tokens", "completion_tokens", "token_usage", "max_tokens", "num_tokens"]);

export function isSensitive(key: string): boolean {
  const k = key.toLowerCase();
  return !SAFE_KEYS.has(k) && SENSITIVE_PARTS.some((p) => k.includes(p));
}

export function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) =>
      [k, isSensitive(k) && v !== null && v !== "" ? REDACTED : redact(v)]));
  }
  return value;
}
