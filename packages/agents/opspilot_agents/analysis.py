"""Deterministic telemetry/change analysis. Numbers are computed in code, not by the LLM."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Any

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_HEX = re.compile(r"\b[0-9a-f]{16,}\b", re.I)
_NUM = re.compile(r"\b\d+(\.\d+)?(ms|s)?\b")
_UPSTREAM = re.compile(r"upstream ([a-z][a-z0-9-]{1,62})")
SCHEMA_HINTS = ("column", "relation", "undefinedcolumn", "undefinedtable", "schema", "migration")


@dataclass(frozen=True, slots=True)
class Anomaly:
    metric: str
    baseline: float
    peak: float
    current: float
    onset: datetime
    threshold: float


def detect_onset(
    points: list[tuple[datetime, float]],
    *,
    min_abs_increase: float,
    factor: float = 5.0,
    sustain: int = 3,
    baseline_fraction: float = 0.5,
) -> Anomaly | None:
    """First sustained excursion above max(baseline*factor, baseline+min_abs_increase).

    Baseline is the median of the first ``baseline_fraction`` of the series, which is robust to
    the excursion itself as long as the window starts well before onset.
    """
    if len(points) < sustain + 10:
        return None
    head = [v for _, v in points[: max(10, int(len(points) * baseline_fraction))]]
    baseline = median(head)
    threshold = max(baseline * factor, baseline + min_abs_increase)
    values = [v for _, v in points]
    for i in range(len(points) - sustain + 1):
        if all(v > threshold for v in values[i : i + sustain]):
            tail = values[i:]
            return Anomaly(
                metric="", baseline=baseline, peak=max(tail), current=tail[-1], onset=points[i][0], threshold=threshold
            )
    return None


def signature(message: str) -> str:
    s = _UUID.sub("<uuid>", message)
    s = _HEX.sub("<hex>", s)
    s = _NUM.sub("<n>", s)
    return s.strip()[:300]


@dataclass(slots=True)
class LogPattern:
    signature: str
    level: str
    count: int
    first_seen: datetime
    last_seen: datetime
    sample: str
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def upstream(self) -> str | None:
        up = self.attributes.get("upstream")
        if isinstance(up, str):
            return up
        m = _UPSTREAM.search(self.sample)
        return m.group(1) if m else None


_ATTR_KEYS = ("code", "upstream", "sqlstate", "status", "endpoint", "version")


def cluster_logs(entries: list[dict[str, Any]], *, top_n: int = 6) -> list[LogPattern]:
    """Group log entries by normalised message signature; ERRORs ranked first, then by count."""
    groups: dict[tuple[str, str], LogPattern] = {}
    for e in entries:
        ts = datetime.fromisoformat(e["ts"]) if isinstance(e["ts"], str) else e["ts"]
        key = (e["level"], signature(e["message"]))
        g = groups.get(key)
        attrs = {k: v for k, v in (e.get("attributes") or {}).items() if k in _ATTR_KEYS}
        if g is None:
            groups[key] = LogPattern(key[1], e["level"], 1, ts, ts, e["message"][:500], attrs)
        else:
            g.count += 1
            g.first_seen, g.last_seen = min(g.first_seen, ts), max(g.last_seen, ts)
    ranked = sorted(groups.values(), key=lambda g: (g.level != "ERROR", -g.count, g.signature))
    return ranked[:top_n]


def change_correlation(
    change_time: datetime,
    onset: datetime,
    *,
    change_service: str,
    affected_services: set[str],
    related_services: set[str],
    schema_change: bool,
    schema_signals: bool,
    horizon_minutes: float = 360.0,
    decay_minutes: float = 30.0,
) -> float:
    """Score in [0,1] for how plausibly a change caused an anomaly starting at ``onset``.

    Temporal proximity (exponential decay, zero for changes after onset+2m or beyond the horizon),
    weighted by whether the changed service is affected/related, plus a bonus when a schema change
    co-occurs with schema-related error signatures.
    """
    delta = (onset - change_time).total_seconds() / 60.0
    if delta < -2 or delta > horizon_minutes:
        return 0.0
    temporal = math.exp(-max(delta, 0.0) / decay_minutes)
    weight = 1.0 if change_service in affected_services else 0.7 if change_service in related_services else 0.4
    bonus = 0.15 if (schema_change and schema_signals) else 0.0
    return round(min(1.0, temporal * weight + bonus), 4)


def has_schema_signals(patterns: list[LogPattern]) -> bool:
    return any(h in p.sample.lower() for p in patterns if p.level == "ERROR" for h in SCHEMA_HINTS)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
