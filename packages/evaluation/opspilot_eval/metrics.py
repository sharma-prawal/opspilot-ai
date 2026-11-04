"""Ranking metrics over document-level relevance (binary)."""

from __future__ import annotations

import math
from statistics import median, quantiles


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    return len(set(ranked[:k]) & relevant) / len(relevant) if relevant else 0.0


def reciprocal_rank(ranked: list[str], relevant: set[str], k: int) -> float:
    return next((1.0 / i for i, d in enumerate(ranked[:k], start=1) if d in relevant), 0.0)


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 1) for i, d in enumerate(ranked[:k], start=1) if d in relevant)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def latency_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50_ms": 0.0, "p95_ms": 0.0}
    p95 = quantiles(values, n=20)[-1] if len(values) >= 2 else values[0]
    return {"p50_ms": round(median(values), 2), "p95_ms": round(p95, 2)}


def mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0
