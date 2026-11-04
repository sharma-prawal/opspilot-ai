"""Vector vs keyword vs hybrid retrieval benchmark on the labelled question set."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opspilot_eval.metrics import latency_summary, mean, ndcg_at_k, recall_at_k, reciprocal_rank
from opspilot_rag.retrieval import HybridRetriever
from opspilot_shared.config import REPO_ROOT
from opspilot_shared.domain.knowledge import RetrievalMode

QUESTIONS = REPO_ROOT / "datasets/evaluation/retrieval_questions.jsonl"  # development set
HELDOUT = REPO_ROOT / "datasets/evaluation/heldout/retrieval_questions.jsonl"  # held-out set
CHUNK_DEPTH = 30  # chunks retrieved per query, collapsed to a document ranking


def load_questions(path: Path = QUESTIONS) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def doc_ranking(source_uris: list[str]) -> list[str]:
    return list(dict.fromkeys(source_uris))


async def run(retriever: HybridRetriever, *, path: Path = QUESTIONS, warmup: bool = True) -> dict[str, Any]:
    questions = load_questions(path)
    if warmup:  # load the embedding model so the first query's latency is not a cold start
        await retriever.search("warmup", top_k=1, record=False)
    modes: dict[str, Any] = {}
    for mode in RetrievalMode:
        per_q, lat = [], []
        for q in questions:
            resp = await retriever.search(q["query"], mode=mode, top_k=CHUNK_DEPTH, record=False)
            ranked = doc_ranking([r.source_uri for r in resp.results])
            rel = set(q["relevant"])
            per_q.append(
                {
                    "id": q["id"],
                    "style": q["style"],
                    "recall@5": recall_at_k(ranked, rel, 5),
                    "recall@10": recall_at_k(ranked, rel, 10),
                    "mrr@10": reciprocal_rank(ranked, rel, 10),
                    "ndcg@10": ndcg_at_k(ranked, rel, 10),
                    "top3": ranked[:3],
                    "latency_ms": resp.latency_ms,
                }
            )
            lat.append(resp.latency_ms)

        def agg(rows: list[dict[str, Any]]) -> dict[str, float]:
            return {m: mean([r[m] for r in rows]) for m in ("recall@5", "recall@10", "mrr@10", "ndcg@10")}

        modes[mode.value] = {
            "overall": agg(per_q),
            "by_style": {s: agg([r for r in per_q if r["style"] == s]) for s in ("exact", "paraphrase")},
            "latency": latency_summary(lat),
            "per_question": per_q,
            # Failure analysis input: questions with no relevant document in the top 5.
            "misses_at_5": [
                {"id": r["id"], "style": r["style"], "top3": r["top3"]} for r in per_q if r["recall@5"] == 0
            ],
        }
    return {"questions": len(questions), "chunk_depth": CHUNK_DEPTH, "modes": modes}
