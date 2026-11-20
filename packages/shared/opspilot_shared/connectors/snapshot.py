"""Collect a read-only telemetry snapshot for one incident (v0.6).

The selected templates are run for the incident's service and each declared affected service over one bounded
window. The results become an ordinary evidence ``Dataset`` (the same normalized records as an upload), so the
investigation workflow, the evidence analysis and the report are reused unchanged. Each query's provenance is kept
next to it.

What was not collected stays unknown: ``Dataset.collected`` names, per signal, the services whose queries
succeeded; the evidence provider reports any other (signal, service) as unavailable rather than as "no data".
v0.9: the signal of each query comes from its template (a Datadog connector returns logs, metrics and spans); a
``span`` entry exists only when a span-capable connector was selected, so v0.6 Loki/Prometheus snapshots are unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from opspilot_shared.connectors.contract import (
    ConnectorError,
    FetchResult,
    FetchWindow,
    QueryProvenance,
    QueryTemplate,
    TelemetryConnector,
)
from opspilot_shared.connectors.registry import ConnectorRegistry
from opspilot_shared.uploads.model import MAX_RECORDS, Dataset

MAX_QUERIES = 40
CONCURRENCY = 4


@dataclass(frozen=True)
class SourceSelection:
    connector: str
    templates: tuple[str, ...]


@dataclass
class Snapshot:
    dataset: Dataset
    queries: list[QueryProvenance]

    @property
    def usable(self) -> bool:
        return bool(self.dataset.logs or self.dataset.metrics or self.dataset.spans)

    def redactions(self) -> int:
        return sum(q.redactions for q in self.queries)


async def collect(
    registry: ConnectorRegistry,
    sources: Sequence[SourceSelection],
    services: Sequence[str],
    window: FetchWindow,
) -> Snapshot:
    plan: list[tuple[TelemetryConnector, QueryTemplate, str]] = []
    for src in sources:
        connector = registry.get(src.connector)
        if not src.templates:
            raise ConnectorError("invalid_request", f"choose at least one {src.connector} template")
        available = {t.id: t for t in connector.templates()}
        for tid in dict.fromkeys(src.templates):
            if tid not in available:
                raise ConnectorError("invalid_request", f"unknown {src.connector} template {tid!r}")
            for svc in dict.fromkeys(services):
                plan.append((connector, available[tid], svc))
    if not plan:
        raise ConnectorError("invalid_request", "choose at least one connector and template")
    if len(plan) > MAX_QUERIES:
        raise ConnectorError(
            "invalid_request", f"{len(plan)} queries requested; at most {MAX_QUERIES} (fewer templates or services)"
        )
    gate = asyncio.Semaphore(CONCURRENCY)

    async def run(item: tuple[TelemetryConnector, QueryTemplate, str]) -> FetchResult:
        connector, template, svc = item
        async with gate:
            return await connector.fetch(template, svc, window)

    results = await asyncio.gather(*(run(p) for p in plan))
    logs, seen = [], set()
    for res in results:  # two templates can match the same line: keep its first occurrence (and its source)
        for r in res.logs:
            key = (r.service, r.ts_original, r.message)
            if key not in seen:
                seen.add(key)
                logs.append(r)
    metrics = [r for res in results for r in res.metrics]
    spans, seen_spans = [], set()
    for res in results:  # error spans and their expanded traces can overlap across services
        for sp in res.spans:
            if (sp.trace_id, sp.span_id) not in seen_spans:
                seen_spans.add((sp.trace_id, sp.span_id))
                spans.append(sp)
    warnings: list[str] = []
    if len(logs) + len(metrics) + len(spans) > MAX_RECORDS:
        warnings.append(f"more than {MAX_RECORDS} records were returned; the oldest were dropped")
        spans = sorted(spans, key=lambda r: r.ts)[-min(len(spans), MAX_RECORDS // 5) :]
        keep_logs = max(0, MAX_RECORDS - len(metrics) - len(spans))
        logs = sorted(logs, key=lambda r: r.ts)[-keep_logs:] if keep_logs else []
        metrics = sorted(metrics, key=lambda r: r.ts)[-(MAX_RECORDS - len(logs) - len(spans)) :]
    selected = {t.returns for _, t, _ in plan}
    span_capable = any("span" in c.signals for c, _, _ in plan)
    collected: dict[str, set[str]] = {"log": set(), "metric": set()}
    if span_capable:
        collected["span"] = set()
    for res in results:
        q = res.provenance
        signal = q.returns
        if q.status == "error":
            err = q.error or {}
            warnings.append(f"{q.id} failed ({err.get('kind', 'error')}): {err.get('message', '')}")
        else:
            collected[signal].add(q.service)
            if q.status == "empty":
                warnings.append(f"{q.id} returned no data for this window")
        warnings += [f"{q.id}: {i}" for i in q.issues]
    for signal, label in (("log", "logs"), ("metric", "metrics"), ("span", "traces/spans")):
        if signal in selected:
            missing = [s for s in dict.fromkeys(services) if s not in collected[signal]]
            if missing:
                warnings.append(f"no {label} could be collected for {', '.join(missing)}; they stay unknown")
    if "metric" not in selected:
        warnings.append("no metrics were queried: impact cannot be measured, so conclusions will stay uncertain")
    dataset = Dataset(
        files=[],
        logs=logs,
        metrics=metrics,
        spans=spans,
        warnings=warnings,
        collected={k: sorted(v) for k, v in collected.items()},
    )
    return Snapshot(dataset=dataset, queries=[r.provenance for r in results])
