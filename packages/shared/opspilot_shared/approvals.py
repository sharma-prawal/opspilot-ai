"""HMAC-signed approval tokens.

A token is issued by the API only after a valid operator decision, and binds the approval to one
``action_id`` and the exact ``params_hash``. The MCP action server verifies it independently
(and also cross-checks the persisted request). Tokens expire and are single-use in effect, because
execution is idempotent per action_id.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass

from opspilot_shared.errors import ApprovalError


@dataclass(frozen=True, slots=True)
class ApprovalClaims:
    action_id: uuid.UUID
    params_hash: str
    approved_by: str
    issued_at: int
    expires_at: int
    expired: bool = False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def issue_token(
    key: str, *, action_id: uuid.UUID, params_hash: str, approved_by: str, ttl_seconds: int, now: int | None = None
) -> str:
    if len(key) < 16:
        raise ApprovalError("ACTION_SIGNING_KEY is missing or too short")
    iat = int(now if now is not None else time.time())
    body = json.dumps(
        {"aid": str(action_id), "ph": params_hash, "by": approved_by, "iat": iat, "exp": iat + ttl_seconds},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    sig = hmac.new(key.encode(), body, hashlib.sha256).digest()
    return f"{_b64(body)}.{_b64(sig)}"


def verify_token(key: str, token: str, *, now: int | None = None, allow_expired: bool = False) -> ApprovalClaims:
    """Verify signature and expiry. ``allow_expired`` returns signed-but-expired claims flagged ``expired``;
    callers may use them only to *replay* an already-recorded result, never to authorise a new effect."""
    if len(key) < 16:
        raise ApprovalError("ACTION_SIGNING_KEY is missing or too short")
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body, sig = _unb64(body_b64), _unb64(sig_b64)
    except ValueError as exc:
        raise ApprovalError("malformed approval token") from exc
    expected = hmac.new(key.encode(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise ApprovalError("approval token signature invalid")
    claims = json.loads(body)
    expired = int(now if now is not None else time.time()) >= int(claims["exp"])
    if expired and not allow_expired:
        raise ApprovalError("approval token expired")
    return ApprovalClaims(
        uuid.UUID(claims["aid"]), claims["ph"], claims["by"], int(claims["iat"]), int(claims["exp"]), expired=expired
    )


def action_params_hash(action_type: str, parameters: dict[str, object]) -> str:
    canonical = json.dumps(
        {"action_type": action_type, "parameters": parameters}, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
