"""Ollama adapters for the ChatModel and Embedder ports (native ``/api/chat`` and ``/api/embed``)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, ValidationError

from opspilot_shared.config import Settings
from opspilot_shared.domain.common import utcnow
from opspilot_shared.domain.evidence import LLMCallRecord
from opspilot_shared.errors import EmbeddingError, LLMOutputError, LLMUnavailableError
from opspilot_shared.ids import short_hash
from opspilot_shared.llm.ports import ChatMessage, StructuredResult
from opspilot_shared.llm.schema import inline_schema
from opspilot_shared.logging import get_logger
from opspilot_shared.tracing import get_tracer

_log = get_logger(__name__)
_tracer = get_tracer(__name__)

QUERY_INSTRUCTION = (
    "Given an operational question about a distributed payment platform, retrieve runbook, "
    "architecture, error-catalogue or past-incident passages that help answer it"
)


class OllamaChatModel:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._s = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.ollama_base_url, timeout=httpx.Timeout(settings.llm_timeout_seconds)
        )
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrency)

    @property
    def model_name(self) -> str:
        return self._s.llm_model

    async def aclose(self) -> None:
        await self._client.aclose()

    async def generate_structured[T: BaseModel](
        self, *, messages: list[ChatMessage], schema: type[T], purpose: str
    ) -> StructuredResult[T]:
        started_at = utcnow()
        t0 = time.perf_counter()
        convo: list[dict[str, str]] = [{"role": m["role"], "content": m["content"]} for m in messages]
        json_schema = inline_schema(schema)
        last_error = ""
        prompt_tokens = completion_tokens = 0
        attempts = 0
        with _tracer.start_as_current_span("llm.generate_structured") as span:
            span.set_attribute("llm.model", self.model_name)
            span.set_attribute("llm.purpose", purpose)
            for attempt in range(1, self._s.llm_max_retries + 2):
                attempts = attempt
                payload: dict[str, Any] = {
                    "model": self.model_name,
                    "messages": convo,
                    "stream": False,
                    "think": self._s.llm_think,
                    "format": json_schema,
                    "keep_alive": self._s.llm_keep_alive,
                    "options": {
                        "temperature": self._s.llm_temperature,
                        "num_ctx": self._s.llm_num_ctx,
                        "num_predict": self._s.llm_num_predict,
                        "seed": 7,
                    },
                }
                try:
                    async with self._semaphore:
                        resp = await self._client.post("/api/chat", json=payload)
                    resp.raise_for_status()
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    _log.warning("llm_call_failed", purpose=purpose, attempt=attempt, error=last_error)
                    await asyncio.sleep(min(2**attempt, 8))
                    continue
                body = resp.json()
                prompt_tokens += int(body.get("prompt_eval_count") or 0)
                completion_tokens += int(body.get("eval_count") or 0)
                content = (body.get("message") or {}).get("content", "")
                try:
                    value = schema.model_validate_json(content)
                except ValidationError as exc:
                    last_error = f"schema validation failed: {exc.error_count()} error(s): {exc.errors()[:3]}"
                    _log.warning("llm_invalid_output", purpose=purpose, attempt=attempt, error=last_error)
                    convo = [
                        *convo,
                        {"role": "assistant", "content": content[:4000]},
                        {
                            "role": "user",
                            "content": (
                                "Your previous reply did not match the required JSON schema: "
                                f"{last_error}. Reply again with corrected JSON only."
                            ),
                        },
                    ]
                    continue
                latency = (time.perf_counter() - t0) * 1000
                record = LLMCallRecord(
                    id=f"llm-{short_hash(purpose, started_at.isoformat(), attempts)}",
                    purpose=purpose,
                    model=self.model_name,
                    latency_ms=round(latency, 1),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    attempts=attempts,
                    started_at=started_at,
                )
                span.set_attribute("llm.prompt_tokens", prompt_tokens)
                span.set_attribute("llm.completion_tokens", completion_tokens)
                span.set_attribute("llm.attempts", attempts)
                _log.info(
                    "llm_call",
                    purpose=purpose,
                    model=self.model_name,
                    latency_ms=record.latency_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    attempts=attempts,
                )
                return StructuredResult(value=value, record=record)
            span.set_status(Status(StatusCode.ERROR, last_error))
        if last_error.startswith("schema validation"):
            raise LLMOutputError(f"{purpose}: {last_error}")
        raise LLMUnavailableError(f"{purpose}: {last_error}")


class OllamaEmbedder:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._s = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.ollama_base_url, timeout=httpx.Timeout(settings.embedding_timeout_seconds)
        )

    @property
    def model_name(self) -> str:
        return self._s.embedding_model

    @property
    def dimensions(self) -> int:
        return self._s.embedding_dimensions

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _embed(self, inputs: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        size = self._s.embedding_batch_size
        for i in range(0, len(inputs), size):
            batch = inputs[i : i + size]
            with _tracer.start_as_current_span("llm.embed") as span:
                span.set_attribute("llm.model", self.model_name)
                span.set_attribute("embed.batch_size", len(batch))
                try:
                    resp = await self._client.post(
                        "/api/embed",
                        json={"model": self.model_name, "input": batch, "keep_alive": self._s.llm_keep_alive},
                    )
                    resp.raise_for_status()
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    raise EmbeddingError(f"embedding request failed: {exc}") from exc
            vectors = resp.json().get("embeddings") or []
            if len(vectors) != len(batch):
                raise EmbeddingError(f"expected {len(batch)} embeddings, got {len(vectors)}")
            for v in vectors:
                if len(v) != self.dimensions:
                    raise EmbeddingError(
                        f"embedding dimension {len(v)} != configured EMBEDDING_DIMENSIONS={self.dimensions}"
                    )
            out.extend(vectors)
        return out

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([f"Instruct: {QUERY_INSTRUCTION}\nQuery:{text}"]))[0]
