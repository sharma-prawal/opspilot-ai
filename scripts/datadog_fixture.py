"""Synthetic Datadog API fixture (v0.9): documented response shapes, fictional services, no real telemetry.

Emulates the read endpoints OpsPilot's Datadog connector calls, with the request and response structures documented
at https://docs.datadoghq.com/api/latest/ (logs search and aggregate, metrics timeseries query, spans search, API key
validation). It is a contract fixture, not Datadog: queries are understood only as far as the built-in templates
need (``service:``, ``env:``, ``status:``, ``trace_id:``, free-text words, ``{service:...}`` metric scopes).

The story (all synthetic): at 13:58:40Z inventory-service 3.8.0 starts with ``reservation_lock_mode=table``; from
14:02Z its ``UPDATE stock_levels`` statements on inventory-db wait for locks for seconds, ``POST /reservations``
times out, and orders-api answers ``POST /orders`` with 504s. notification-worker is healthy throughout. Some spans
are not indexed (retention filters), so a few traces are partial. One log carries a fake credential so redaction can
be seen. A few logs have no service tag and one service name (``Legacy_Billing``) is not a valid OpsPilot slug.

Usage:
    uv run python scripts/datadog_fixture.py --port 8126        # serve on 127.0.0.1 (``make datadog-fixture``)

Then, for the API process only: ``DATADOG_ENABLED=true DATADOG_LOCAL_API_URL=http://127.0.0.1:8126
DATADOG_API_KEY=fixture-api-key DATADOG_APP_KEY=fixture-app-key``. The fixture accepts only those two synthetic keys.
Failure modes for tests: ``Fixture.fail[path] = status | "timeout" | "malformed" | "not_json"``.
"""

from __future__ import annotations

import argparse
import ast
import base64
import json
import operator
import random
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

API_KEY = "fixture-api-key"
APP_KEY = "fixture-app-key"
SITE = "datadoghq.com"
START = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
END = datetime(2026, 11, 15, 15, 0, tzinfo=UTC)
DEPLOY = datetime(2026, 11, 15, 13, 58, 40, tzinfo=UTC)
ONSET = datetime(2026, 11, 15, 14, 2, tzinfo=UTC)
INCIDENT_TIME = "2026-11-15T14:05:00Z"
SERVICES = ("orders-api", "inventory-service", "notification-worker", "billing.worker_v2")
ENV = "prod"
FAKE_SECRET = "sk_live_FIXTURE0000000000000000"  # noqa: S105 - synthetic value, shown redacted by OpsPilot


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ms(dt: datetime) -> int:
    delta = dt - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000


def _event_id(rng: random.Random) -> str:
    return "AQAAAZ" + base64.b64encode(rng.randbytes(18)).decode().rstrip("=").replace("/", "_").replace("+", "-")


# ------------------------------------------------------------------------------------------------------ data
@dataclass
class Data:
    logs: list[dict[str, Any]] = field(default_factory=list)
    spans: list[dict[str, Any]] = field(default_factory=list)


def build() -> Data:
    rng = random.Random(20261115)
    d = Data()

    def log(ts: datetime, service: str | None, status: str, message: str, **attrs: Any) -> None:
        tags = [f"env:{ENV}", "source:python" if service != "orders-api" else "source:go"]
        if service:
            tags.insert(0, f"service:{service}")
        a: dict[str, Any] = {
            "timestamp": iso(ts),
            "status": status,
            "message": message,
            "host": f"i-0{rng.randrange(10**6):06x}",
            "tags": tags,
            "attributes": attrs,
        }
        if service:
            a["service"] = service
        d.logs.append({"id": _event_id(rng), "type": "log", "attributes": a})

    def span(
        trace: str,
        sid: str,
        parent: str,
        service: str,
        resource: str,
        kind: str,
        start: datetime,
        dur_ms: float,
        error: str | None = None,
        indexed: bool = True,
        **attrs: Any,
    ) -> None:
        if not indexed:
            return
        a: dict[str, Any] = {
            "trace_id": trace,
            "span_id": sid,
            "parent_id": parent,
            "service": service,
            "resource_name": resource,
            "resource_hash": f"{rng.getrandbits(64):016x}",
            "type": kind,
            "env": ENV,
            "host": f"i-0{rng.randrange(10**6):06x}",
            "start_timestamp": iso(start),
            "end_timestamp": iso(start + timedelta(milliseconds=dur_ms)),
            "ingestion_reason": "rule",
            "retained_by": "retention_filter",
            "single_span": False,
            "tags": [f"env:{ENV}", f"service:{service}", *(["status:error"] if error else [])],
            "attributes": {"duration": int(dur_ms * 1e6), **attrs},
            "custom": {},
        }
        if error:
            a["custom"] = {"error": {"message": error, "type": "TimeoutError"}}
        d.spans.append({"id": _event_id(rng), "type": "spans", "attributes": a})

    # lifecycle and steady-state logs
    log(DEPLOY, "inventory-service", "info", "starting inventory-service version=3.8.0 reservation_lock_mode=table")
    log(
        DEPLOY + timedelta(seconds=4),
        "inventory-service",
        "info",
        "config loaded: db_pool_max=40 lock_timeout_ms=10000",
    )
    log(
        datetime(2026, 11, 15, 13, 10, tzinfo=UTC),
        "notification-worker",
        "info",
        "started notification-worker version=1.4.2",
    )
    log(datetime(2026, 11, 15, 13, 30, tzinfo=UTC), "Legacy_Billing", "warn", "billing export retry")
    for i in range(3):
        log(datetime(2026, 11, 15, 13, 40 + i, tzinfo=UTC), None, "info", "lambda cold start (untagged)")
    t = START
    n = 0
    while t < END:
        n += 1
        after = t >= ONSET
        trace = f"{rng.getrandbits(64):d}"
        o_sid, i_sid, db_sid = (f"{rng.getrandbits(63):d}" for _ in range(3))
        db_ms = rng.uniform(4200, 9800) if after else rng.uniform(3, 12)
        inv_ms = min(db_ms + rng.uniform(5, 20), 5000) if after else db_ms + rng.uniform(8, 25)
        failing = after and rng.random() < 0.7
        o_ms = 5000 + rng.uniform(1, 9) if failing else inv_ms + rng.uniform(10, 40)
        # retention: about 1 trace in 7 loses its inventory-service span (partial trace)
        inv_indexed = n % 7 != 3
        span(
            trace,
            o_sid,
            "0",
            "orders-api",
            "POST /orders",
            "web",
            t,
            o_ms,
            error="upstream inventory-service timed out after 5000ms" if failing else None,
            **{
                "http.status_code": "504" if failing else "201",
                "http.method": "POST",
                "http.route": "/orders",
                "peer.service": "inventory-service",
            },
        )
        span(
            trace,
            i_sid,
            o_sid,
            "inventory-service",
            "POST /reservations",
            "web",
            t + timedelta(milliseconds=3),
            inv_ms,
            error="context deadline exceeded waiting for stock_levels lock" if failing else None,
            indexed=inv_indexed,
            **{"http.status_code": "500" if failing else "200", "http.method": "POST", "peer.service": "inventory-db"},
        )
        span(
            trace,
            db_sid,
            i_sid,
            "inventory-db",
            "UPDATE stock_levels",
            "db",
            t + timedelta(milliseconds=5),
            db_ms,
            **{"db.system": "postgresql", "db.type": "postgresql", "component": "postgres"},
        )
        if failing:
            log(
                t + timedelta(milliseconds=o_ms),
                "orders-api",
                "error",
                f"POST /orders failed: 504 upstream inventory-service timed out after 5000ms order_id=ord-{n:05d}",
                **{"dd": {"trace_id": trace, "span_id": o_sid}, "http": {"status_code": 504}},
            )
            log(
                t + timedelta(milliseconds=inv_ms),
                "inventory-service",
                "error",
                f"reservation failed: lock wait on stock_levels exceeded {int(db_ms)}ms "
                f"sku=SKU-{rng.randrange(1000, 9999)}",
                **{"dd": {"trace_id": trace, "span_id": i_sid}, "db": {"statement": "UPDATE stock_levels"}},
            )
        elif after and rng.random() < 0.4:
            log(
                t + timedelta(milliseconds=inv_ms),
                "inventory-service",
                "warn",
                f"slow reservation: waited {int(db_ms)}ms for stock_levels lock",
            )
        if n % 30 == 0:  # a service name with '.' and '_' (valid Datadog service tag), healthy, warns occasionally
            log(t, "billing.worker_v2", "warn" if n % 90 == 0 else "info", f"invoice batch {n} exported in 1.2s")
        if n % 40 == 0:
            log(t, "notification-worker", "info", f"sent batch of {rng.randrange(20, 60)} notifications")
            span(
                f"{rng.getrandbits(64):d}",
                f"{rng.getrandbits(63):d}",
                "0",
                "notification-worker",
                "send_batch",
                "worker",
                t,
                rng.uniform(40, 120),
            )
        t += timedelta(seconds=20)
    log(
        ONSET + timedelta(minutes=1),
        "orders-api",
        "error",
        f"payment provider call rejected: api_key={FAKE_SECRET} (synthetic, redacted by OpsPilot)",
    )
    return d


# --------------------------------------------------------------------------------------------------- metrics
def _metric_value(metric: str, service: str, t: datetime, rng: random.Random) -> float | None:
    if not START <= t < END:
        return None  # the fixture holds data for 12:00-15:00Z only
    after = t >= ONSET
    profile = {
        "orders-api": (55.0, 0.32 if after else 0.003, 5.4 if after else 0.09),
        "inventory-service": (54.0, 0.58 if after else 0.002, 6.1 if after else 0.03),
    }
    if service not in profile:
        return None  # notification-worker has no APM http trace metrics; unknown services have no data at all
    rps, five, p95 = profile[service]
    if metric == "trace.http.request.hits":
        return rps * 60 * rng.uniform(0.95, 1.05)
    if metric == "trace.http.request.hits.by_http_status":
        return rps * 60 * five * rng.uniform(0.9, 1.1)
    if metric == "trace.http.request.errors":
        return rps * 60 * five * rng.uniform(0.95, 1.08)
    if metric == "trace.http.request":
        return p95 * rng.uniform(0.92, 1.08)
    return None  # e.g. system.cpu.user: hosts are not tagged with the service in this fixture (missing series)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _eval(node: ast.AST, env: dict[str, float | None]) -> float | None:
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        a, b = _eval(node.left, env), _eval(node.right, env)
        if a is None or b is None or (isinstance(node.op, ast.Div) and b == 0):
            return None
        return _OPS[type(node.op)](a, b)
    raise ValueError("unsupported formula")


def timeseries(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    attrs = ((body.get("data") or {}).get("attributes")) or {}
    if (body.get("data") or {}).get("type") != "timeseries_request":
        return 400, {"errors": ["data.type must be timeseries_request"]}
    frm, to, interval = int(attrs["from"]), int(attrs["to"]), max(int(attrs.get("interval") or 60_000), 60_000)
    queries = attrs.get("queries") or []
    formulas = attrs.get("formulas") or [{"formula": queries[0]["name"]}]
    parsed = []
    for q in queries:
        m = re.match(r"^(\w+):([\w.]+)\{([^}]*)\}", q["query"])
        if not m:
            return 400, {"errors": [f"Error parsing query: {q['query'][:60]}"]}
        scope = dict(p.split(":", 1) for p in m.group(3).split(",") if ":" in p)
        parsed.append((q["name"], m.group(2), scope))
    service = next((s.get("service") for _, _, s in parsed if s.get("service")), None)
    times: list[int] = list(range(frm - frm % interval + interval, to, interval))
    rng = random.Random(f"{service}|{[p[1] for p in parsed]}")
    values: list[float | None] = []
    present = False
    for ts in times:
        t = datetime.fromtimestamp(ts / 1000, UTC)
        env = {name: _metric_value(metric, service or "", t, rng) for name, metric, _ in parsed}
        if any(v is not None for v in env.values()):
            present = True
        # a 3-minute gap in orders-api's 5xx data (agent restart): Datadog returns null, OpsPilot must not fill it
        if service == "orders-api" and datetime(2026, 11, 15, 13, 20, tzinfo=UTC) <= t < datetime(
            2026, 11, 15, 13, 23, tzinfo=UTC
        ):
            env = dict.fromkeys(env)
        values.append(_eval(ast.parse(formulas[0]["formula"], mode="eval"), env))
    if not present:
        return 200, {"data": {"type": "timeseries_response", "attributes": {"series": [], "times": [], "values": []}}}
    first = parsed[0][1]
    unit = [{"family": "time", "name": "second", "plural": "seconds", "scale_factor": 1.0, "short_name": "s"}, None]
    if "hits" in first or "errors" in first:
        unit = [{"family": "general", "name": "hit", "plural": "hits", "scale_factor": 1.0, "short_name": "hit"}, None]
    series = [{"group_tags": [f"service:{service}"] if service else [], "query_index": 0, "unit": unit}]
    return 200, {
        "data": {"type": "timeseries_response", "attributes": {"series": series, "times": times, "values": [values]}}
    }


# ---------------------------------------------------------------------------------------------- search helpers
def _matches(item: dict[str, Any], query: str) -> bool:
    a = item["attributes"]
    q = query
    # values may be escaped as Datadog's search syntax documents (orders\-api); unescape before comparing
    for key, raw in re.findall(r"(service|env):((?:\\.|[\w.])+)", q):
        val = re.sub(r"\\(.)", r"\1", raw)
        tagval = (
            a.get("service")
            if key == "service"
            else a.get("env") or next((t.split(":", 1)[1] for t in a.get("tags", []) if t.startswith("env:")), None)
        )
        if tagval != val:
            return False
    m = re.search(r"status:\(([^)]*)\)", q) or re.search(r"status:(\w+)", q)
    if m:
        wanted = {w.strip() for w in m.group(1).split("OR")}
        status = a.get("status") or ("error" if "status:error" in a.get("tags", []) else "ok")
        if status not in wanted:
            return False
    m = re.search(r"trace_id:\(([^)]*)\)", q)
    if m and a.get("trace_id") not in {w.strip() for w in m.group(1).split("OR")}:
        return False
    rest = re.sub(r"(service|env|status|trace_id):(\([^)]*\)|(?:\\.|[\w.])+)", "", q)
    words = re.search(r"\(([^)]*)\)", rest)
    if words:
        terms = [w.strip().lower() for w in words.group(1).split("OR")]
        if not any(term in str(a.get("message", "")).lower() for term in terms):
            return False
    return True


def _in_window(item: dict[str, Any], frm: str, to: str) -> bool:
    ts = item["attributes"].get("timestamp") or item["attributes"].get("start_timestamp")
    return frm <= ts < to


def _page(
    items: list[dict[str, Any]], page: dict[str, Any], sort: str, key: str
) -> tuple[list[dict[str, Any]], str | None]:
    items = sorted(items, key=lambda i: i["attributes"][key], reverse=sort.startswith("-"))
    offset = int(base64.b64decode(page["cursor"]).decode()) if page.get("cursor") else 0
    limit = int(page.get("limit") or 10)
    chunk = items[offset : offset + limit]
    nxt = offset + limit
    return chunk, base64.b64encode(str(nxt).encode()).decode() if nxt < len(items) else None


def _meta(after: str | None) -> dict[str, Any]:
    meta: dict[str, Any] = {"elapsed": 42, "request_id": "pddv1ChZmaXh0dXJlLXJlcXVlc3Q", "status": "done"}
    if after:
        meta["page"] = {"after": after}
    return meta


def _bound(value: str) -> str:
    """filter.from/to: ISO strings or epoch milliseconds, normalized to ISO for comparison."""
    if re.fullmatch(r"\d{10,}", str(value)):
        return iso(datetime.fromtimestamp(int(value) / 1000, UTC))
    return iso(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


# --------------------------------------------------------------------------------------------------- fixture
@dataclass
class Fixture:
    data: Data = field(default_factory=build)
    fail: dict[str, Any] = field(default_factory=dict)  # path -> status | "timeout" | "malformed" | "not_json"
    requests: list[dict[str, Any]] = field(default_factory=list)
    rate_reset: str = "0"  # X-RateLimit-Reset sent with a 429

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        hdr = {k.lower(): v for k, v in headers.items()}
        doc: Any = None
        if body:
            try:
                doc = json.loads(body)
            except json.JSONDecodeError:
                doc = None
        self.requests.append({"method": method, "path": path, "headers": hdr, "body": doc})
        failure = self.fail.get(path)
        if failure == "timeout":
            raise TimeoutError("synthetic timeout")
        if isinstance(failure, int):
            extra = (
                {
                    "x-ratelimit-limit": "50",
                    "x-ratelimit-period": "60",
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-reset": self.rate_reset,
                    "x-ratelimit-name": "spans_search",
                }
                if failure == 429
                else {}
            )
            msg = {403: "Forbidden", 429: "Too many requests", 500: "Internal Server Error", 400: "Bad Request"}
            return (
                failure,
                {"content-type": "application/json", **extra},
                json.dumps({"errors": [msg.get(failure, "error")]}).encode(),
            )
        if failure == "not_json":
            return 200, {"content-type": "text/html"}, b"<html>maintenance</html>"
        if failure == "malformed":
            return 200, {"content-type": "application/json"}, json.dumps({"data": {"unexpected": True}}).encode()
        if hdr.get("dd-api-key") != API_KEY:
            return 403, {"content-type": "application/json"}, json.dumps({"errors": ["Forbidden"]}).encode()
        if path == "/api/v1/validate" and method == "GET":
            return 200, {"content-type": "application/json"}, json.dumps({"valid": True}).encode()
        if hdr.get("dd-application-key") != APP_KEY:
            return 403, {"content-type": "application/json"}, json.dumps({"errors": ["Forbidden"]}).encode()
        if method != "POST":
            return 405, {}, b""
        status, payload = self._route(path, doc or {})
        return status, {"content-type": "application/json"}, json.dumps(payload).encode()

    def _route(self, path: str, doc: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if path == "/api/v2/query/timeseries":
            return timeseries(doc)
        if path == "/api/v2/logs/events/search":
            f = doc.get("filter") or {}
            frm, to = _bound(f.get("from", iso(END - timedelta(minutes=15)))), _bound(f.get("to", iso(END)))
            items = [i for i in self.data.logs if _in_window(i, frm, to) and _matches(i, f.get("query", "*"))]
            chunk, after = _page(items, doc.get("page") or {}, doc.get("sort", "timestamp"), "timestamp")
            out: dict[str, Any] = {"data": chunk, "meta": _meta(after)}
            if after:
                out["links"] = {"next": "https://api.datadoghq.com/api/v2/logs/events?page[cursor]=" + after}
            return 200, out
        if path == "/api/v2/logs/analytics/aggregate":
            f = doc.get("filter") or {}
            frm, to = _bound(f.get("from")), _bound(f.get("to"))
            counts: dict[str, int] = {}
            missing = ((doc.get("group_by") or [{}])[0]).get("missing", "")
            for i in self.data.logs:
                if _in_window(i, frm, to) and _matches(i, f.get("query", "*")):
                    svc = i["attributes"].get("service") or missing
                    counts[svc] = counts.get(svc, 0) + 1
            buckets = [
                {"by": {"service": k}, "computes": {"c0": v}} for k, v in sorted(counts.items(), key=lambda x: -x[1])
            ]
            return 200, {
                "data": {"buckets": buckets},
                "meta": {"elapsed": 12, "request_id": "fixture", "status": "done"},
            }
        if path == "/api/v2/spans/events/search":
            data = doc.get("data") or {}
            if data.get("type") != "search_request":
                return 400, {"errors": ["data.type must be search_request"]}
            attrs = data.get("attributes") or {}
            f = attrs.get("filter") or {}
            frm, to = _bound(f.get("from")), _bound(f.get("to"))
            items = [i for i in self.data.spans if _in_window(i, frm, to) and _matches(i, f.get("query", "*"))]
            chunk, after = _page(items, attrs.get("page") or {}, attrs.get("sort", "timestamp"), "start_timestamp")
            out = {"data": chunk, "meta": _meta(after)}
            if after:
                out["links"] = {"next": "https://api.datadoghq.com/api/v2/spans/events?page[cursor]=" + after}
            return 200, out
        return 404, {"errors": ["Not found"]}


def serve(port: int) -> None:
    fixture = Fixture()

    class Handler(BaseHTTPRequestHandler):
        def _go(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else b""
            try:
                status, headers, payload = fixture.handle(
                    self.command, self.path.split("?")[0], dict(self.headers), body
                )
            except TimeoutError:
                return
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = _go

        def log_message(self, fmt: str, *args: Any) -> None:  # requests carry the synthetic keys only; keep quiet
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"synthetic Datadog fixture on http://127.0.0.1:{port} (synthetic data only; Ctrl-C to stop)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=8126)
    serve(parser.parse_args().port)
