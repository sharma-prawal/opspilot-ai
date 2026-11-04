"""Resource measurements on the local machine (C0 item P): embedding bursts, a chat call, Ollama memory.

Numbers are measurements of this machine at run time, not targets. Memory is the resident set size of every
process whose command line contains ``ollama`` (server + model runners), sampled every 100 ms.
"""

from __future__ import annotations

import asyncio
import platform
import subprocess
import time
from typing import Any

import httpx
from pydantic import BaseModel

from opspilot_eval.metrics import latency_summary
from opspilot_shared.config import Settings
from opspilot_shared.llm.ollama import OllamaChatModel, OllamaEmbedder

BURST = 32


def _sysctl(key: str) -> str:
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no user input
            ["/usr/sbin/sysctl", "-n", key], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def ollama_rss_mb() -> float:
    out = subprocess.run(["/bin/ps", "-axo", "rss=,command="], capture_output=True, text=True, timeout=5).stdout
    kb = sum(int(line.split(None, 1)[0]) for line in out.splitlines() if "ollama" in line.lower() and line.strip())
    return round(kb / 1024, 1)


class _Sampler:
    def __init__(self) -> None:
        self.peak = 0.0
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, await asyncio.to_thread(ollama_rss_mb))
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self._stop.set()


async def _sampled(coro: Any) -> tuple[Any, float, float]:
    sampler = _Sampler()
    task = asyncio.create_task(sampler.run())
    t0 = time.perf_counter()
    try:
        result = await coro
    finally:
        sampler.stop()
        await task
    return result, round((time.perf_counter() - t0) * 1000, 1), sampler.peak


async def embedding_burst(settings: Settings, bound: int) -> dict[str, Any]:
    s = settings.model_copy(update={"embedding_max_concurrency": bound})
    emb = OllamaEmbedder(s)
    lat: list[float] = []

    async def one(i: int) -> None:
        t0 = time.perf_counter()
        await emb.embed_query(f"ledger connection pool exhausted after deploy {i}")
        lat.append(round((time.perf_counter() - t0) * 1000, 1))

    try:
        _, wall, peak_rss = await _sampled(asyncio.gather(*(one(i) for i in range(BURST))))
    finally:
        await emb.aclose()
    return {
        "bound": bound,
        "requests": BURST,
        "wall_ms": wall,
        "per_request": latency_summary(lat),
        "peak_in_flight": emb.peak_in_flight,
        "ollama_peak_rss_mb": peak_rss,
    }


class _Probe(BaseModel):
    service: str
    healthy: bool


async def chat_call(settings: Settings) -> dict[str, Any]:
    chat = OllamaChatModel(settings)
    messages = [
        {"role": "system", "content": "Answer with JSON only."},
        {"role": "user", "content": "The ledger-service health check reports errors. Fill the fields."},
    ]
    try:
        res, wall, peak = await _sampled(
            chat.generate_structured(messages=messages, schema=_Probe, purpose="resource_probe")  # type: ignore[arg-type]
        )
    finally:
        await chat.aclose()
    return {
        "model": settings.llm_model,
        "wall_ms": wall,
        "prompt_tokens": res.record.prompt_tokens,
        "completion_tokens": res.record.completion_tokens,
        "ollama_peak_rss_mb": peak,
    }


async def loaded_models(settings: Settings) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=10) as c:
        models = (await c.get("/api/ps")).json().get("models", [])
    return [{"name": m.get("name"), "size_mb": round((m.get("size") or 0) / 2**20)} for m in models]


async def run(settings: Settings) -> dict[str, Any]:
    await embedding_burst(settings, settings.embedding_max_concurrency)  # warm-up: load the embedding model
    idle = ollama_rss_mb()
    bounded = await embedding_burst(settings, settings.embedding_max_concurrency)
    wide = await embedding_burst(settings, 16)
    chat = await chat_call(settings)
    return {
        "machine": {
            "chip": _sysctl("machdep.cpu.brand_string"),
            "memory_gb": round(int(_sysctl("hw.memsize") or 0) / 2**30, 1) if _sysctl("hw.memsize").isdigit() else None,
            "os": platform.platform(),
        },
        "limits": {
            "embedding_max_concurrency": settings.embedding_max_concurrency,
            "llm_max_concurrency": settings.llm_max_concurrency,
            "max_concurrent_investigations": settings.max_concurrent_investigations,
            "max_pending_investigations": settings.max_pending_investigations,
        },
        "ollama_idle_rss_mb": idle,
        "embedding_burst_bounded": bounded,
        "embedding_burst_wide": wide,
        "chat_call": chat,
        "loaded_models_after": await loaded_models(settings),
    }
