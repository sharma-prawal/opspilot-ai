"""Deterministic stand-ins for model ports (no Ollama needed)."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from opspilot_agents.prompts import PlanOutput, RcaOutput
from opspilot_shared.domain.common import utcnow
from opspilot_shared.domain.evidence import LLMCallRecord
from opspilot_shared.llm.ports import ChatMessage, StructuredResult


class HashEmbedder:
    """Bag-of-words feature hashing into a fixed dimension, L2-normalised. Similar text → similar vectors."""

    def __init__(self, dim: int) -> None:
        self._dim = dim

    @property
    def model_name(self) -> str:
        return "test-hash-embedder"

    @property
    def dimensions(self) -> int:
        return self._dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self._dim
        for tok in re.findall(r"[a-z0-9_]{2,}", text.lower()):
            h = int(hashlib.blake2b(tok.encode(), digest_size=8).hexdigest(), 16)
            v[h % self._dim] += 1.0 if (h >> 63) & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def _evidence_from(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    import json

    body = messages[-1]["content"]
    block = body[body.index("<evidence>") + len("<evidence>") : body.rindex("</evidence>")]
    return json.loads(block).get("evidence", [])


def heuristic_rca(messages: list[ChatMessage]) -> dict[str, Any]:
    """Picks the most correlated deployment as the cause. Exercises wiring, not reasoning quality."""
    ev = _evidence_from(messages)
    deploys = [e for e in ev if e["kind"] == "deployment"]
    errors = [e for e in ev if e["kind"] == "log_pattern" and "ERROR" in e["summary"]]
    top = max(deploys, key=lambda e: e["relevance"]) if deploys else None
    m = re.search(r"id (dep-[a-z0-9-]+)", top["summary"]) if top else None
    dep_id = m.group(1) if m else None
    svc = top["service"] if top else None
    return {
        "summary": "Most correlated change caused the errors.",
        "hypotheses": [
            {
                "title": f"Change {dep_id} broke {svc}",
                "category": "deployment_regression",
                "description": "Temporal correlation with error onset.",
                "confidence": 0.9,
                "supporting_evidence_ids": [e["id"] for e in ([top] if top else []) + errors[:2]],
            }
        ],
        "evidence_gaps": [],
        "followups": [],
        "impact_ongoing": True,
        "remediation_plan": [
            {
                "action_type": "rollback_deployment",
                "service": svc,
                "deployment_id": dep_id,
                "rationale": "revert the correlated change",
            }
        ]
        if dep_id
        else [],
        "escalation": {"required": False, "reason": "", "to": ""},
    }


class ScriptedChatModel:
    """Returns schema-valid objects produced by per-schema handlers (or fixed payloads)."""

    def __init__(
        self, handlers: dict[type[BaseModel], Callable[[list[ChatMessage]], dict[str, Any]]] | None = None
    ) -> None:
        self.handlers = handlers or {
            PlanOutput: lambda _m: {
                "category": "unknown",
                "category_confidence": 0.3,
                "rationale": "alert only",
                "capabilities": ["telemetry", "changes", "knowledge"],
            },
            RcaOutput: heuristic_rca,
        }
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    @property
    def model_name(self) -> str:
        return "scripted-test-model"

    async def generate_structured[T: BaseModel](
        self, *, messages: list[ChatMessage], schema: type[T], purpose: str
    ) -> StructuredResult[T]:
        self.calls.append((purpose, messages))
        value = schema.model_validate(self.handlers[schema](messages))
        rec = LLMCallRecord(
            id=f"llm-test-{len(self.calls)}",
            purpose=purpose,
            model=self.model_name,
            latency_ms=1.0,
            prompt_tokens=0,
            completion_tokens=0,
            started_at=utcnow(),
        )
        return StructuredResult(value=value, record=rec)
