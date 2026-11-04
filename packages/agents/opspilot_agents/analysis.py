"""Deterministic telemetry/change analysis. Numbers are computed in code, not by the LLM."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median, pstdev
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


@dataclass(frozen=True, slots=True)
class Shift:
    metric: str
    direction: str  # up | down
    baseline: float
    extreme: float
    current: float
    onset: datetime
    recovered: bool


def _min_abs_change(unit: str) -> float:
    return {"ratio": 0.02, "ms": 100.0}.get(unit, 0.0)


def detect_shift(
    points: list[tuple[datetime, float]], *, metric: str, unit: str, sustain: int = 3, baseline_fraction: float = 0.5
) -> Shift | None:
    """First sustained departure from baseline in either direction, unit-aware.

    Up: value > max(baseline*factor, baseline+min_abs) with factor 5 for ratios, 2 otherwise.
    Down: value < baseline*0.5 (only meaningful for non-ratio throughput/size metrics).
    ``recovered`` is true when the last ``sustain`` points are back inside the threshold.
    """
    if len(points) < sustain + 10:
        return None
    head = [v for _, v in points[: max(10, int(len(points) * baseline_fraction))]]
    baseline = median(head)
    noise = pstdev(head)
    factor = 5.0 if unit == "ratio" else 2.0
    # Count-like metrics often have a baseline median of 0; require a material absolute change too, so
    # ordinary noise (0,1,2 per minute) never registers as an onset.
    min_abs = _min_abs_change(unit) or max(5.0, 0.1 * baseline)
    up_thr = max(baseline * factor, baseline + min_abs, baseline + 4 * noise)
    down_thr = min(baseline * 0.5, baseline - 4 * noise) if unit != "ratio" and baseline > 0 else None
    values = [v for _, v in points]

    def above(v: float) -> bool:
        return v > up_thr

    def below(v: float) -> bool:
        return down_thr is not None and v < down_thr

    checks: tuple[tuple[str, Callable[[float], bool]], ...] = (("up", above), ("down", below))
    for direction, beyond in checks:
        for i in range(len(values) - sustain + 1):
            if all(beyond(v) for v in values[i : i + sustain]):
                tail = values[i:]
                extreme = max(tail) if direction == "up" else min(tail)
                recovered = not any(beyond(v) for v in values[-sustain:])
                return Shift(metric, direction, baseline, extreme, values[-1], points[i][0], recovered)
    return None


_STOP = {
    "with",
    "from",
    "that",
    "this",
    "into",
    "when",
    "after",
    "before",
    "failed",
    "error",
    "errors",
    "service",
    "returned",
    "upstream",
    "request",
    "requests",
    "change",
    "update",
    "add",
    "adds",
    "message",
}


def informative_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z][a-z0-9_]{3,}", text.lower()) if t not in _STOP}


def lexical_overlap_bonus(change_text: str, signals: list[str]) -> tuple[float, list[str]]:
    """Bonus when a change description shares specific vocabulary with observed failures (generic)."""
    shared = sorted(
        informative_tokens(change_text) & set().union(*(informative_tokens(s) for s in signals)) if signals else set()
    )
    return (0.2 if len(shared) >= 2 else 0.1 if shared else 0.0), shared[:6]
