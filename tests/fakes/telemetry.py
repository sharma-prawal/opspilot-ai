"""In-process fake Loki and Prometheus HTTP APIs (v0.6 tests), served through ``httpx.MockTransport``.

The fakes answer with the response shapes verified against grafana/loki:3.5.0 and prom/prometheus:v3.5.0 (see
``make telemetry-up``) for the synthetic incident of ``scripts/generate_telemetry.py``: payment-service starts with a
smaller DB pool at 09:12:20Z and, from 09:14Z, its authorizations time out and checkout-api payments fail.

Every request is recorded, so tests can assert that only GETs to read endpoints were made. ``fail`` makes the next
requests to a path answer with a given status (or raise a transport error) to exercise connector error states.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from opspilot_shared.config import Settings
from opspilot_shared.connectors.registry import ConnectorRegistry

_GEN = Path(__file__).resolve().parents[2] / "scripts/generate_telemetry.py"
_spec = importlib.util.spec_from_file_location("generate_telemetry", _GEN)
assert _spec and _spec.loader
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

ONSET = gen.ONSET.timestamp()
POOL_CHANGE = gen.PAY_DEPLOY.timestamp()
TENANT = "opspilot-demo"
WINDOW = {"start": "2026-11-12T07:30:00Z", "end": "2026-11-12T09:45:00Z"}
INCIDENT_TIME = "2026-11-12T09:16:00Z"
SECRET_TOKEN = "prom-read-token-0123456789"


@dataclass
class Recorded:
    method: str
    host: str
    path: str
    params: dict[str, str]
    headers: dict[str, str]


@dataclass
class FakeTelemetry:
    loki_tenant: str | None = TENANT
    prom_token: str | None = None
    requests: list[Recorded] = field(default_factory=list)
    fail: dict[str, Any] = field(default_factory=dict)  # path -> status code | Exception | "redirect" | "huge"
    streams: list[dict[str, Any]] = field(default_factory=lambda: _streams())

    # -- transports ---------------------------------------------------------------------------------------------
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def registry(self, **settings: Any) -> ConnectorRegistry:
        base = {
            "loki_url": "http://loki.test",
            "loki_tenant_id": TENANT,
            "prometheus_url": "http://prometheus.test",
            "telemetry_templates_file": str(
                Path(__file__).resolve().parents[2] / "infra/telemetry/query-templates.json"
            ),
            **settings,
        }
        s = Settings(_env_file=None, **base)  # type: ignore[call-arg]
        t = self.transport()
        return ConnectorRegistry.from_settings(s, transports={"loki": t, "prometheus": t})

    def _handle(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append(
            Recorded(request.method, request.url.host, request.url.path, params, dict(request.headers))
        )
        f = self.fail.get(request.url.path)
        if isinstance(f, Exception):
            raise f
        if f == "redirect":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
        if f == "huge":
            return httpx.Response(200, content=b"[" + b"0," * 4_000_000 + b"0]")
        if isinstance(f, int):
            return httpx.Response(f, json={"status": "error", "errorType": "x", "error": f"forced {f}"})
        if request.method != "GET":
            return httpx.Response(405)
        if request.url.host == "loki.test":
            return self._loki(request, params)
        return self._prometheus(request, params)

    # -- Loki ---------------------------------------------------------------------------------------------------
    def _loki(self, request: httpx.Request, p: dict[str, str]) -> httpx.Response:
        if self.loki_tenant and request.headers.get("x-scope-orgid") != self.loki_tenant:
            return httpx.Response(401, text="no org id\n")
        path = request.url.path
        if path == "/loki/api/v1/status/buildinfo":
            return httpx.Response(200, json={"version": "3.5.0", "revision": "fake"})
        if path == "/loki/api/v1/labels":
            return httpx.Response(200, json={"status": "success", "data": ["env", "namespace", "service_name"]})
        if path == "/loki/api/v1/label/service_name/values":
            return httpx.Response(
                200, json={"status": "success", "data": [s["stream"]["service_name"] for s in self.streams]}
            )
        if path == "/loki/api/v1/query_range":
            m = re.match(r'^\{service_name="([^"]+)"\}(?:\s*\|~\s*"(.*)")?$', p["query"])
            if not m:
                return httpx.Response(400, text="parse error at line 1, col 1: syntax error")
            svc, rx = m.group(1), m.group(2)
            pattern = re.compile(rx.replace("\\\\", "\\")) if rx else None
            start, end, limit = int(p["start"]), int(p["end"]), int(p["limit"])
            result = []
            for s in self.streams:
                if s["stream"]["service_name"] != svc:
                    continue
                vals = [v for v in s["values"] if start <= int(v[0]) <= end and (not pattern or pattern.search(v[1]))]
                vals = sorted(vals, key=lambda v: int(v[0]), reverse=p.get("direction") != "forward")[:limit]
                if vals:
                    result.append({"stream": s["stream"], "values": vals})
            return httpx.Response(
                200, json={"status": "success", "data": {"resultType": "streams", "result": result, "stats": {}}}
            )
        return httpx.Response(404, text="404 page not found")

    # -- Prometheus ---------------------------------------------------------------------------------------------
    def _prometheus(self, request: httpx.Request, p: dict[str, str]) -> httpx.Response:
        if self.prom_token and request.headers.get("authorization") != f"Bearer {self.prom_token}":
            return httpx.Response(401, text=f"Unauthorized (token {request.headers.get('authorization', '')})")
        path = request.url.path
        if path == "/api/v1/status/buildinfo":
            return httpx.Response(200, json={"status": "success", "data": {"version": "3.5.0"}})
        if path == "/api/v1/labels":
            return httpx.Response(200, json={"status": "success", "data": ["__name__", "env", "service", "status"]})
        if path == "/api/v1/label/service/values":
            return httpx.Response(200, json={"status": "success", "data": list(gen.SERVICES)})
        if path == "/api/v1/query_range":
            q = p["query"]
            m = re.search(r'service="([^"]+)"', q)
            if not m:
                return httpx.Response(400, json={"status": "error", "errorType": "bad_data", "error": "parse error"})
            svc = m.group(1)
            start, end, step = float(p["start"]), float(p["end"]), int(p["step"])
            if (end - start) / step > 11000:
                return httpx.Response(
                    400,
                    json={
                        "status": "error",
                        "errorType": "bad_data",
                        "error": "exceeded maximum resolution of 11,000 points per timeseries",
                    },
                )
            fn = _series_fn(q, svc)
            if fn is None:
                return httpx.Response(200, json={"status": "success", "data": {"resultType": "matrix", "result": []}})
            values = []
            t = start
            while t <= end:
                v = fn(t)
                values.append([round(t, 3), "NaN" if math.isnan(v) else repr(v)])
                t += step
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {"resultType": "matrix", "result": [{"metric": {}, "values": values}]},
                },
            )
        return httpx.Response(404, text="404 page not found")


def _series_fn(q: str, svc: str) -> Any:
    if svc not in gen.SERVICES:  # like a real Prometheus: no series for an unknown service
        return None
    after = lambda t: t >= ONSET  # noqa: E731
    bad = svc in ("checkout-api", "payment-service")
    if "db_pool_connections_in_use" in q:
        return (lambda t: 10.0 if after(t) else 8.0) if svc == "payment-service" else None
    if "db_pool_connections_max" in q:
        return (lambda t: 10.0 if t >= POOL_CHANGE else 50.0) if svc == "payment-service" else None
    if 'status=~"5.."' in q:
        return lambda t: 0.33 if after(t) and bad else 0.004
    if "histogram_quantile" in q:
        return lambda t: 2300.0 if after(t) and bad else 95.0
    if "http_requests_total" in q:
        return lambda t: 2400.0 + 10 * math.sin(t / 600)
    return None


def _streams() -> list[dict[str, Any]]:
    gen.rng.seed(20261112)
    return gen.loki_streams()


def window_dt() -> tuple[datetime, datetime]:
    return (
        datetime.fromisoformat(WINDOW["start"]).astimezone(UTC),
        datetime.fromisoformat(WINDOW["end"]).astimezone(UTC),
    )


def as_json(obj: Any) -> str:
    return json.dumps(obj, default=str)
