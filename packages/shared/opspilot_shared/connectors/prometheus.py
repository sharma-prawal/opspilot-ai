"""Prometheus connector (v0.6): range queries over the official HTTP API, read-only.

Endpoints used (all GET, https://prometheus.io/docs/prometheus/latest/querying/api/):

- ``/api/v1/status/buildinfo``: version, for the connection test (``/api/v1/labels`` when build info is absent);
- ``/api/v1/label/<service label>/values``: services that can be queried;
- ``/api/v1/query_range`` with ``query``, ``start``/``end`` (Unix seconds) and ``step`` (seconds): a ``matrix``
  result of ``{"metric": {labels}, "values": [[<unix s>, "<value>"], ...]}``. Prometheus refuses more than 11,000
  points per series; OpsPilot asks for about 240.

Verified against prom/prometheus:v3.5.0 (``make telemetry-up``). Compatible APIs (Thanos, Mimir, VictoriaMetrics)
expose the same endpoints but were not tested.
"""

from __future__ import annotations

import math
import time
from typing import Any

from opspilot_shared.connectors.base import HttpConnector, epoch_s, from_epoch_s, step_for
from opspilot_shared.connectors.contract import (
    ConnectionStatus,
    ConnectorError,
    FetchResult,
    FetchWindow,
    QueryTemplate,
)
from opspilot_shared.connectors.templates import render
from opspilot_shared.uploads.model import MetricRecord
from opspilot_shared.uploads.parse import normalize_service

QUERY_RANGE = "/api/v1/query_range"


class PrometheusConnector(HttpConnector):
    KIND = "prometheus"
    SIGNAL = "metric"
    NAME = "Prometheus"

    def allowed_paths(self) -> list[str]:
        return ["/api/v1/status/buildinfo", "/api/v1/labels", f"/api/v1/label/{self.service_label}/values", QUERY_RANGE]

    async def test(self) -> ConnectionStatus:
        return await self.test_paths("/api/v1/status/buildinfo", "/api/v1/labels", {})

    async def services(self, window: FetchWindow) -> list[str]:
        self.check_window(window)
        doc, _ = await self.http.get_json(
            f"/api/v1/label/{self.service_label}/values", {"start": epoch_s(window.start), "end": epoch_s(window.end)}
        )
        return self.label_values(doc)

    async def fetch(self, template: QueryTemplate, service: str, window: FetchWindow) -> FetchResult:
        self.check_window(window)
        step = step_for(window)
        query = render(template, label=self.service_label, service=service, step_seconds=step)
        prov = self.provenance(template, service, window, endpoint=QUERY_RANGE, query=query, step=step)
        t0 = time.perf_counter()
        try:
            doc, _ = await self.http.get_json(
                QUERY_RANGE,
                {"query": query, "start": epoch_s(window.start), "end": epoch_s(window.end), "step": str(step)},
            )
            metrics = self._records(doc, template, service, prov)
        except ConnectorError as exc:
            prov.status, prov.error = "error", exc.as_dict()
            prov.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            return FetchResult(provenance=prov)
        prov.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        prov.returned = len(metrics)
        prov.status = "ok" if metrics else "empty"
        return FetchResult(provenance=prov, metrics=metrics)

    def _records(self, doc: Any, t: QueryTemplate, service: str, prov: Any) -> list[MetricRecord]:
        data = doc.get("data") if isinstance(doc, dict) else None
        if not isinstance(data, dict) or doc.get("status") != "success":
            raise ConnectorError("invalid_response", "Prometheus did not answer with status=success and data")
        for w in [*(doc.get("warnings") or []), *(doc.get("infos") or [])][:5]:
            prov.issues.append(self.http.clean(f"Prometheus: {w}", 200))
        if data.get("resultType") != "matrix":
            raise ConnectorError(
                "query_error", f"expected a range-vector result (matrix), got {str(data.get('resultType'))[:20]!r}"
            )
        series = [s for s in data.get("result") or [] if isinstance(s, dict)]
        prov.series = len(series)
        if len(series) > self.limits.max_series:
            prov.truncated = True
            prov.issues.append(
                f"{len(series)} series returned; only the first {self.limits.max_series} are kept (aggregate the "
                "template, e.g. with sum by (...))"
            )
            series = series[: self.limits.max_series]
        points: list[tuple[Any, ...]] = []
        for s in series:
            labels = {str(k)[:60]: str(v)[:120] for k, v in (s.get("metric") or {}).items()}
            for v in s.get("values") or []:
                if not (isinstance(v, list) and len(v) == 2):
                    prov.rejected += 1
                    continue
                ts = from_epoch_s(v[0])
                try:
                    value = float(v[1])
                except (TypeError, ValueError):
                    value = math.nan
                if ts is None or not math.isfinite(value):  # NaN (e.g. 0/0) or ±Inf is no measurement
                    prov.rejected += 1
                    continue
                points.append((ts, value, str(v[0]), labels))
        if prov.rejected:
            prov.issues.append(f"{prov.rejected} point(s) without a finite value were skipped (never filled in)")
        points.sort(key=lambda p: p[0])
        out: list[MetricRecord] = []
        for n, (ts, value, raw_ts, labels) in enumerate(points, start=1):
            label_svc = normalize_service(labels.get(self.service_label))
            out.append(
                MetricRecord(
                    ts=ts,
                    ts_original=raw_ts,
                    tz="epoch",
                    service=label_svc or service,
                    service_source="record" if label_svc else "query",
                    source=f"{prov.id}:point {n}",
                    metric=t.metric or t.id,
                    metric_original=t.id,
                    value=value,
                    unit=t.unit,
                    labels=dict(list(labels.items())[:10]),
                )
            )
        return out
