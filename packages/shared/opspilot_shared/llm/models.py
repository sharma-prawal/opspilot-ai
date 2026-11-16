"""Inspect and probe local Ollama models so the configured models can be swapped safely.

The investigation model is chosen with ``LLM_MODEL`` (any Ollama chat model); nothing in the application names a
specific model. Before a model is used, these helpers confirm that the local Ollama installation has it, that it
advertises the capability the application needs, and (optionally) that it returns schema-valid JSON through the same
constrained-decoding path the agent uses. The agent calls tools from code, not through model tool-calling, so
structured output is the compatibility requirement for the chat model; ``tools`` is reported for information only.
"""

from __future__ import annotations

import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from opspilot_shared.config import Settings
from opspilot_shared.errors import LLMError
from opspilot_shared.llm.ports import ChatMessage

Role = Literal["llm", "embedding"]
REQUIRED_CAPABILITY: dict[Role, str] = {"llm": "completion", "embedding": "embedding"}


class ModelInfo(BaseModel):
    name: str
    role: Role
    installed: bool
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    runner: str | None = None  # e.g. "mlx" for Apple MLX builds; absent for GGUF (llama.cpp) builds
    context_length: int | None = None
    capabilities: list[str] = Field(default_factory=list)
    compatible: bool = False
    problems: list[str] = Field(default_factory=list)


def _context_length(model_info: dict[str, Any]) -> int | None:
    for key, value in model_info.items():
        if key.endswith(".context_length") and isinstance(value, int):
            return value
    return None


async def describe_model(client: httpx.AsyncClient, name: str, role: Role) -> ModelInfo:
    """What local Ollama knows about ``name`` and whether it can serve ``role``; a missing model is not an error."""
    resp = await client.post("/api/show", json={"model": name})
    if resp.status_code == 404:
        return ModelInfo(name=name, role=role, installed=False, problems=[f"not installed: run `ollama pull {name}`"])
    resp.raise_for_status()
    body = resp.json()
    details = body.get("details") or {}
    caps = sorted(body.get("capabilities") or [])
    info = ModelInfo(
        name=name,
        role=role,
        installed=True,
        family=details.get("family"),
        parameter_size=details.get("parameter_size"),
        quantization=details.get("quantization_level"),
        runner=details.get("runner"),
        context_length=_context_length(body.get("model_info") or {}),
        capabilities=caps,
    )
    need = REQUIRED_CAPABILITY[role]
    if caps and need not in caps:  # older Ollama versions report no capabilities; the probe is then authoritative
        info.problems.append(f"missing capability '{need}' (has {caps})")
    info.compatible = not info.problems
    return info


class _Probe(BaseModel):
    """A miniature of the agent's RCA contract: nested list, enum, bounded number, and a boolean."""

    model_config = ConfigDict(extra="forbid")
    category: Literal["deployment_regression", "dependency_degradation", "unknown"]
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(min_length=1, max_length=3)
    action_required: bool


_PROBE_MESSAGES: list[ChatMessage] = [
    {"role": "system", "content": "You classify incidents. Return JSON only."},
    {
        "role": "user",
        "content": (
            "<evidence>[{'id': 'ev-1', 'summary': 'payments-api 5xx rose to 30% two minutes after deployment "
            "dep-77'}, {'id': 'ev-2', 'summary': 'all dependencies healthy'}]</evidence> Classify the incident, "
            "cite evidence IDs exactly, and say whether action is required."
        ),
    },
]


async def probe_structured_output(settings: Settings, model: str) -> dict[str, Any]:
    """One structured call through the production adapter (same options, retries and validation)."""
    from opspilot_shared.llm.ollama import OllamaChatModel

    chat = OllamaChatModel(settings.model_copy(update={"llm_model": model}))
    t0 = time.perf_counter()
    try:
        out = await chat.generate_structured(messages=_PROBE_MESSAGES, schema=_Probe, purpose="models.probe")
    except LLMError as exc:
        error = str(exc)[:300]
        if "501" in error:  # Ollama answers 501 "structured output is unavailable" for some runners (e.g. MLX)
            error = (
                "this build does not support JSON-schema structured output in the installed Ollama (HTTP 501); "
                "use a GGUF tag of the same model (for example '<name>-q4_K_M') or upgrade Ollama"
            )
        return {"ok": False, "error": error, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    finally:
        await chat.aclose()
    cited_ok = set(out.value.evidence_ids) <= {"ev-1", "ev-2"}
    return {
        "ok": cited_ok,
        "error": None if cited_ok else f"cited unknown evidence ids {out.value.evidence_ids}",
        "latency_ms": out.record.latency_ms,
        "attempts": out.record.attempts,
        "completion_tokens": out.record.completion_tokens,
        "value": out.value.model_dump(),
    }


async def inspect_configured_models(settings: Settings, *, probe: bool = False) -> dict[str, Any]:
    """Configured chat + embedding models, everything installed locally, and an optional live probe."""
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=10) as client:
        version = (await client.get("/api/version")).json().get("version")
        installed = sorted(m["name"] for m in (await client.get("/api/tags")).json().get("models", []))
        llm = await describe_model(client, settings.llm_model, "llm")
        emb = await describe_model(client, settings.embedding_model, "embedding")
    result: dict[str, Any] = {
        "ollama_version": version,
        "llm": llm.model_dump(),
        "embedding": emb.model_dump(),
        "installed": installed,
    }
    if probe and llm.installed:
        result["llm"]["structured_output_probe"] = p = await probe_structured_output(settings, settings.llm_model)
        if not p["ok"]:
            result["llm"]["compatible"] = False
            result["llm"]["problems"].append(f"structured-output probe failed: {p['error']}")
    return result
