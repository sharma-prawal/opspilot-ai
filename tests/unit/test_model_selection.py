"""v0.4: the investigation model is configuration (LLM_MODEL); compatibility is checked, never assumed."""

import json

import httpx
import pytest

from opspilot_shared.config import Settings
from opspilot_shared.llm.models import describe_model

SHOW = {
    "good:9b": {
        "capabilities": ["completion", "tools", "thinking"],
        "details": {"family": "fam", "parameter_size": "9B", "quantization_level": "Q4_K_M"},
        "model_info": {"fam.context_length": 32768},
    },
    "embed-only:1b": {"capabilities": ["embedding"], "details": {}, "model_info": {}},
    "legacy:7b": {"details": {"family": "old"}, "model_info": {}},  # older Ollama: no capability list
}


def _client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        name = json.loads(request.content)["model"]
        if name not in SHOW:
            return httpx.Response(404, json={"error": f"model '{name}' not found"})
        return httpx.Response(200, json=SHOW[name])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")


async def test_chat_model_with_completion_capability_is_compatible() -> None:
    async with _client() as c:
        info = await describe_model(c, "good:9b", "llm")
    assert info.installed and info.compatible and not info.problems
    assert (info.family, info.parameter_size, info.quantization, info.context_length) == ("fam", "9B", "Q4_K_M", 32768)


async def test_missing_model_is_reported_not_raised() -> None:
    async with _client() as c:
        info = await describe_model(c, "absent:3b", "llm")
    assert not info.installed and not info.compatible
    assert "ollama pull absent:3b" in info.problems[0]


@pytest.mark.parametrize(("name", "role", "ok"), [("embed-only:1b", "llm", False), ("good:9b", "embedding", False)])
async def test_wrong_role_is_incompatible(name: str, role: str, ok: bool) -> None:
    async with _client() as c:
        info = await describe_model(c, name, role)  # type: ignore[arg-type]
    assert info.compatible is ok and "missing capability" in info.problems[0]


async def test_unknown_capabilities_defer_to_the_probe() -> None:
    async with _client() as c:
        info = await describe_model(c, "legacy:7b", "llm")
    assert info.installed and info.compatible


def test_llm_model_comes_from_configuration() -> None:
    s = Settings(_env_file=None, llm_model="any-local-model:latest")  # type: ignore[call-arg]
    from opspilot_shared.llm.ollama import OllamaChatModel

    assert OllamaChatModel(s).model_name == "any-local-model:latest"


async def test_unsupported_structured_output_fails_fast_without_retries() -> None:
    from pydantic import BaseModel

    from opspilot_shared.errors import LLMUnavailableError
    from opspilot_shared.llm.ollama import OllamaChatModel

    class Out(BaseModel):
        ok: bool

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(501, json={"error": "structured output is unavailable"})

    s = Settings(_env_file=None, llm_max_retries=2)  # type: ignore[call-arg]
    chat = OllamaChatModel(s, client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x"))
    with pytest.raises(LLMUnavailableError, match="structured output is unavailable"):
        await chat.generate_structured(messages=[{"role": "user", "content": "x"}], schema=Out, purpose="t")
    assert calls == 1
