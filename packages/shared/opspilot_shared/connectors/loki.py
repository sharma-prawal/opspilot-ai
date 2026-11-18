"""Grafana Loki connector (v0.6): log queries over the official HTTP API, read-only.

Endpoints used (all GET, https://grafana.com/docs/loki/latest/reference/loki-http-api/):

- ``/loki/api/v1/status/buildinfo``: version, for the connection test;
- ``/loki/api/v1/labels``: authentication/tenant probe (a multi-tenant Loki answers 401 "no org id" without one);
- ``/loki/api/v1/label/<service label>/values``: services that can be queried;
- ``/loki/api/v1/query_range`` with ``query``, ``start``/``end`` (Unix nanoseconds), ``limit`` and
  ``direction=backward``: a ``streams`` result of ``{"stream": {labels}, "values": [["<ns>", "<line>"], ...]}``.

Verified against grafana/loki:3.5.0 (``make telemetry-up``).
"""

from __future__ import annotations

import time
from typing import Any

from opspilot_shared.connectors.base import HttpConnector, epoch_ns, from_epoch_ns
from opspilot_shared.connectors.contract import (
    ConnectionStatus,
    ConnectorError,
    FetchResult,
    FetchWindow,
    QueryTemplate,
)
from opspilot_shared.connectors.templates import render
from opspilot_shared.uploads.model import LogRecord
from opspilot_shared.uploads.parse import infer_level, log_line_fields, map_level, normalize_service

QUERY_RANGE = "/loki/api/v1/query_range"
_LEVEL_LABELS = ("level", "detected_level", "severity", "severity_text", "lvl")


class LokiConnector(HttpConnector):
    KIND = "loki"
    SIGNAL = "log"
    NAME = "Grafana Loki"

    def __init__(self, *, tenant_id: str = "", **kw: Any) -> None:
        self.tenant_id = tenant_id
        headers = {"X-Scope-OrgID": tenant_id} if tenant_id else {}
        super().__init__(headers=headers, **kw)

    def allowed_paths(self) -> list[str]:
        return [
            "/loki/api/v1/status/buildinfo",
            "/loki/api/v1/labels",
            f"/loki/api/v1/label/{self.service_label}/values",
            QUERY_RANGE,
        ]

    def extra_info(self) -> dict[str, Any]:
        return {"tenant": self.tenant_id or None}

    async def test(self) -> ConnectionStatus:
        return await self.test_paths("/loki/api/v1/status/buildinfo", "/loki/api/v1/labels", {"since": "1h"})

    async def services(self, window: FetchWindow) -> list[str]:
        self.check_window(window)
        doc, _ = await self.http.get_json(
            f"/loki/api/v1/label/{self.service_label}/values",
            {"start": epoch_ns(window.start), "end": epoch_ns(window.end)},
        )
        return self.label_values(doc)

    async def fetch(self, template: QueryTemplate, service: str, window: FetchWindow) -> FetchResult:
        self.check_window(window)
        query = render(template, label=self.service_label, service=service)
        limit = self.limits.max_log_lines
        prov = self.provenance(template, service, window, endpoint=QUERY_RANGE, query=query, limit=limit)
        t0 = time.perf_counter()
        try:
            doc, _ = await self.http.get_json(
                QUERY_RANGE,
                {
                    "query": query,
                    "start": epoch_ns(window.start),
                    "end": epoch_ns(window.end),
                    "limit": str(limit),
                    "direction": "backward",
                },
            )
            logs = self._records(doc, prov.id, service, prov)
        except ConnectorError as exc:
            prov.status, prov.error = "error", exc.as_dict()
            prov.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            return FetchResult(provenance=prov)
        prov.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        prov.returned = len(logs)
        prov.status = "ok" if logs else "empty"
        prov.truncated = len(logs) + prov.rejected >= limit
        if prov.truncated:
            prov.issues.append(
                f"the {limit}-line limit was reached: only the most recent lines of the window are included"
            )
        return FetchResult(provenance=prov, logs=logs)

    def _records(self, doc: Any, qid: str, service: str, prov: Any) -> list[LogRecord]:
        data = doc.get("data") if isinstance(doc, dict) else None
        if not isinstance(data, dict) or doc.get("status") != "success":
            raise ConnectorError("invalid_response", "Loki did not answer with status=success and a data object")
        if data.get("resultType") != "streams":
            raise ConnectorError(
                "query_error", f"expected a log query (streams), got {str(data.get('resultType'))[:20]!r}"
            )
        raw: list[tuple[Any, ...]] = []
        for stream in data.get("result") or []:
            labels = stream.get("stream") if isinstance(stream, dict) else None
            values = stream.get("values") if isinstance(stream, dict) else None
            if not isinstance(labels, dict) or not isinstance(values, list):
                prov.rejected += 1
                continue
            for v in values:
                if isinstance(v, list) and len(v) >= 2 and isinstance(v[1], str):
                    raw.append((str(v[0]), v[1], labels))
                else:
                    prov.rejected += 1
        out: list[tuple[Any, ...]] = []
        for ns, line, labels in raw:
            ts = from_epoch_ns(ns)
            if ts is None:
                prov.rejected += 1
                continue
            out.append((ts, ns, line, labels))
        out.sort(key=lambda r: (r[0], r[1]))
        records: list[LogRecord] = []
        for n, (ts, ns, line, labels) in enumerate(out, start=1):
            f = log_line_fields(line)
            prov.redactions += f["redactions"]
            label_svc = normalize_service(labels.get(self.service_label))
            level = f["level"] or next((map_level(labels[k]) for k in _LEVEL_LABELS if labels.get(k)), None)
            attrs = dict(f["attributes"])
            for k, v in list(labels.items())[:8]:
                if k != self.service_label and k not in _LEVEL_LABELS and len(attrs) < 24:
                    attrs[f"label.{k}"[:40]] = str(v)[:120]
            records.append(
                LogRecord(
                    ts=ts,
                    ts_original=ns,
                    tz="epoch",
                    service=label_svc or service,
                    service_source="record" if label_svc else "query",
                    source=f"{qid}:entry {n}",
                    level=level or infer_level(f["message"]),  # type: ignore[arg-type]
                    level_inferred=level is None,
                    message=f["message"],
                    trace_id=f["trace_id"],
                    span_id=f["span_id"],
                    attributes=attrs,
                )
            )
        return records
