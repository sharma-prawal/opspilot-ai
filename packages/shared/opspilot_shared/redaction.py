"""Central sensitive-field redaction policy (audit finding E).

Applied at every boundary where data leaves the trusted core: tool-call records (before they enter graph
state or logs), persistence, REST serialization and structured logging. Keys are matched by name,
case-insensitively; values are replaced, never partially masked.
"""

from __future__ import annotations

from typing import Any

REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = (
    "token",
    "password",
    "passphrase",
    "secret",
    "signing_key",
    "authorization",
    "api_key",
    "cookie",
    "credential",
)
# Exact keys that contain a sensitive part but are safe (non-secret identifiers / counters).
SAFE_KEYS = frozenset({"prompt_tokens", "completion_tokens", "token_usage", "max_tokens", "num_tokens"})


def is_sensitive(key: str) -> bool:
    k = key.lower()
    return k not in SAFE_KEYS and any(part in k for part in SENSITIVE_KEY_PARTS)


def redact(value: Any) -> Any:
    """Deep copy of ``value`` with every sensitive key's value replaced by ``[REDACTED]``."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if isinstance(k, str) and is_sensitive(k) and v not in (None, "") else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact(v) for v in value)
    return value


def contains_secret(value: Any) -> bool:
    """True if any sensitive key still carries a non-redacted value (used by sanitisation and tests)."""
    if isinstance(value, dict):
        return any(
            (isinstance(k, str) and is_sensitive(k) and v not in (None, "", REDACTED, "<redacted>"))
            or contains_secret(v)
            for k, v in value.items()
        )
    if isinstance(value, list | tuple):
        return any(contains_secret(v) for v in value)
    return False
