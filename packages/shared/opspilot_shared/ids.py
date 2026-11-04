"""Deterministic identifiers and canonical hashing."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

# Fixed namespace so IDs are stable across machines and runs.
OPSPILOT_NAMESPACE = uuid.UUID("6f1d3c3e-5b0a-4f7e-9a51-0c2b9e7d4a10")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(value: Any) -> str:
    return sha256_hex(value if isinstance(value, str) else canonical_json(value))


def stable_uuid(*parts: object, namespace: uuid.UUID = OPSPILOT_NAMESPACE) -> uuid.UUID:
    return uuid.uuid5(namespace, "\x1f".join(str(p) for p in parts))


def short_hash(*parts: object, length: int = 12) -> str:
    return sha256_hex("\x1f".join(str(p) for p in parts))[:length]
