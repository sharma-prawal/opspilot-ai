"""C0 item P: embeddings are concurrency-bounded like chat."""

import asyncio
import json

import httpx

from opspilot_shared.config import Settings
from opspilot_shared.llm.ollama import OllamaEmbedder


async def test_embedding_requests_are_bounded_under_a_burst() -> None:
    s = Settings(_env_file=None, embedding_max_concurrency=2, embedding_dimensions=32)  # type: ignore[call-arg]
    live = peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.02)
        live -= 1
        n = len(json.loads(request.content)["input"])
        return httpx.Response(200, json={"embeddings": [[0.1] * 32] * n})

    emb = OllamaEmbedder(s, client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x"))
    vectors = await asyncio.gather(*(emb.embed_query(f"q{i}") for i in range(12)))
    assert len(vectors) == 12 and peak == 2 and emb.peak_in_flight == 2
