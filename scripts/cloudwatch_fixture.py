"""Synthetic AWS CloudWatch API fixture (v0.11): documented wire formats, fictional services, no real data.

One loopback HTTP server answers the three AWS APIs the OpsPilot CloudWatch connector calls, in the protocols the
official SDK (botocore) speaks for them, so the real ``boto3`` client signs, sends and parses every request:

- CloudWatch Logs, AWS JSON 1.1 (``X-Amz-Target: Logs_20140328.<Operation>``): ``StartQuery``, ``GetQueryResults``,
  ``StopQuery``, ``DescribeLogGroups``. Logs Insights results are lists of ``{"field", "value"}`` cells with string
  values plus ``@ptr``; statuses ``Scheduled`` → ``Running`` → ``Complete`` (or ``Failed``/``Timeout``/``Cancelled``);
  ``statistics`` with ``recordsMatched``/``recordsScanned``/``bytesScanned``/``logGroupsScanned``…; errors as
  ``{"__type", "message"}`` with HTTP 400 (``ResourceNotFoundException``, ``AccessDeniedException``,
  ``ThrottlingException``, ``LimitExceededException``, ``MalformedQueryException``, ``InvalidParameterException``).
- CloudWatch metrics, AWS JSON 1.0 (``X-Amz-Target: GraniteServiceVersion20100801.GetMetricData``): epoch-second
  ``Timestamps`` with matching ``Values``, ``StatusCode`` (``Complete``/``PartialData``/``Forbidden``), ``NextToken``.
- AWS STS, query protocol (form body ``Action=GetCallerIdentity``), XML answer or ``ErrorResponse``.

Requests must carry a SigV4 ``Authorization`` header for the right signing service; the access key selects a
credential scenario (``KEYS``). It is a contract fixture, not AWS: Logs Insights QL is understood only as far as
OpsPilot's templates need (``fields``, ``filter @message like /re/``, ``filter `f` = "v"``, ``ispresent`` OR lists,
``stats count(*) as value by bin(Nm) as @t``, ``sort @timestamp desc``, ``limit``). Anything else is a
``MalformedQueryException``.

The story (all synthetic; fictional account 111122223333, region us-east-1): api-gateway → checkout-service →
inventory-service on ECS behind ALBs. At 14:02:15Z inventory-service 3.8.0 starts and logs that its database pool
configuration was loaded with ``max_size=8`` (previously 40, from a parameter path). From 14:05Z its database
connection wait p95 rises from ~6 ms to ~1.9 s, inventory requests time out acquiring connections and answer 503,
checkout-service's calls to inventory fail, and api-gateway answers 502; ALB target 5xx and response time rise.
At 14:50:30Z inventory-service reloads ``max_size=40`` and the errors stop. Nothing in CloudWatch records a
deployment: change history stays unknown, and the configuration line is an observed log indicator only.
pricing-service's log group does not exist and its Lambda published no datapoints; the identity may not read
audit-worker's log group. Scenario log groups under ``/fixture/`` exercise each failure mode (``SCENARIOS``).

Usage::

    uv run python scripts/cloudwatch_fixture.py --port 8131          # ``make cloudwatch-fixture``

Then, for the API process only: ``CLOUDWATCH_ENABLED=true CLOUDWATCH_AUTH_MODE=fixture CLOUDWATCH_REGION=us-east-1
CLOUDWATCH_LOCAL_ENDPOINT_URL=http://127.0.0.1:8131 CLOUDWATCH_RESOURCES_FILE=infra/cloudwatch/resources.fixture.yaml``.
"""

# ruff: noqa: E501 - synthetic log lines are kept one record per line for readability
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

ACCOUNT = "111122223333"  # fictional (AWS documentation example account)
START = datetime(2026, 11, 18, 13, 0, tzinfo=UTC)
END = datetime(2026, 11, 18, 16, 0, tzinfo=UTC)
CONFIG_EVENT = datetime(2026, 11, 18, 14, 2, 15, tzinfo=UTC)
ONSET = datetime(2026, 11, 18, 14, 5, tzinfo=UTC)
RESTORE = datetime(2026, 11, 18, 14, 50, 30, tzinfo=UTC)
INCIDENT_TIME = "2026-11-18T14:12:00Z"
FAKE_SECRET = "Fixture-Pa55word-0000"  # noqa: S105 - synthetic value, shown redacted by OpsPilot
# Access key → credential scenario (the connector's fixture key is the first one).
KEYS = {
    "AKIAOPSPILOTFIXTURE0": "ok",
    "AKIAFIXTUREEXPIRED00": "expired",  # every call: ExpiredTokenException / ExpiredToken
    "AKIAFIXTUREINVALID00": "invalid",  # every call: UnrecognizedClientException / InvalidClientTokenId
    "AKIAFIXTURENOPERMS00": "no_permissions",  # STS works; every CloudWatch call: AccessDeniedException
    "AKIAFIXTUREOTHERACCT": "other_account",  # STS reports account 444455556666
}
STORY_GROUPS = {
    "/ecs/shop-prod/api-gateway": "api-gateway",
    "/ecs/shop-prod/checkout-service": "checkout-service",
    "/ecs/shop-prod/inventory-service": "inventory-service",
    "/ecs/shop-prod/audit-worker": "audit-worker",
}
DENIED_GROUPS = {"/ecs/shop-prod/audit-worker", "/fixture/denied"}
SCENARIOS = {
    "/fixture/empty": "empty",  # Complete with no rows
    "/fixture/delayed": "delayed",  # Scheduled, Running, Running, then Complete
    "/fixture/slow": "slow",  # Running forever (OpsPilot's polling ceiling stops it)
    "/fixture/partial": "partial",  # Running forever, with partial rows
    "/fixture/failed": "failed",  # status Failed
    "/fixture/timeout": "timeout",  # status Timeout
    "/fixture/cancelled": "cancelled",  # status Cancelled (by someone else)
    "/fixture/throttled": "throttled",  # StartQuery: ThrottlingException
    "/fixture/limit": "limit",  # StartQuery: LimitExceededException (too many concurrent queries)
    "/fixture/malformed": "malformed",  # rows without a valid @timestamp / without field names
    "/fixture/denied": "denied",  # StartQuery: AccessDeniedException
    "/fixture/uncorrelated": "uncorrelated",  # events without request/trace IDs
}
EXISTING_GROUPS = {*STORY_GROUPS, *SCENARIOS}  # /ecs/shop-prod/pricing-service does not exist


# ------------------------------------------------------------------------------------------------ the story
@dataclass(frozen=True)
class Event:
    ts: datetime
    group: str
    stream: str
    message: str
    fields: dict[str, str] = field(default_factory=dict)


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def _story() -> list[Event]:
    rnd = random.Random(1118)
    ev: list[Event] = []
    inv, chk, api = (
        "/ecs/shop-prod/inventory-service",
        "/ecs/shop-prod/checkout-service",
        "/ecs/shop-prod/api-gateway",
    )
    inv_stream = "ecs/inventory-service/5c1d9e2a7b3f4a60"
    new_stream = "ecs/inventory-service/9f2c1ab04e7d4b21"
    chk_stream = "ecs/checkout-service/1a7e3c5b9d2f4e68"
    api_stream = "ecs/api-gateway/7b3d5f1a9c2e4d80"

    def inv_json(ts: datetime, level: str, msg: str, stream: str = inv_stream, **extra: str) -> None:
        rid = f"req-{rnd.randrange(16**8):08x}"
        tid = f"1-{int(ts.timestamp()):08x}-{rnd.randrange(16**24):024x}"
        body = {"level": level, "service": "inventory-service", "msg": msg, "requestId": rid, "traceId": tid, **extra}
        ev.append(
            Event(
                ts,
                inv,
                stream,
                json.dumps(body),
                {"level": level, "requestId": rid, "traceId": tid, "service": "inventory-service"},
            )
        )

    t = START
    while t < END:
        failing = ONSET <= t < RESTORE
        stream = new_stream if t >= CONFIG_EVENT else inv_stream
        # inventory-service: JSON logs
        inv_json(t + timedelta(seconds=7), "INFO", "GET /inventory/sku 200", stream, latency_ms=str(rnd.randint(8, 30)))
        if failing:
            for k in range(rnd.randint(3, 5)):
                inv_json(
                    t + timedelta(seconds=11 + k * 9),
                    "ERROR",
                    "timeout acquiring connection from pool after 2000 ms (pool max_size=8, waiting=37)",
                    stream,
                )
            inv_json(
                t + timedelta(seconds=52),
                "ERROR",
                "GET /inventory/sku answered 503: database connection wait exceeded",
                stream,
            )
            if t.minute % 6 == 0:
                inv_json(t + timedelta(seconds=40), "WARN", "db pool saturation: 8/8 connections in use", stream)
        # checkout-service: plain text logs, trace id on some lines only (correlation gap)
        ev.append(
            Event(t + timedelta(seconds=15), chk, chk_stream, f"INFO POST /checkout 200 in {rnd.randint(60, 140)}ms")
        )
        if failing:
            ev.append(
                Event(
                    t + timedelta(seconds=24),
                    chk,
                    chk_stream,
                    "ERROR inventory-service call failed: HTTP 503 after 2512ms (reserve-stock)",
                )
            )
            if t.minute % 3 == 0:
                tid = f"1-{int(t.timestamp()):08x}-{rnd.randrange(16**24):024x}"
                ev.append(
                    Event(
                        t + timedelta(seconds=33),
                        chk,
                        chk_stream,
                        f"ERROR traceId={tid} upstream timeout calling inventory-service: timed out after 2500ms",
                        {"traceId": tid},
                    )
                )
        # api-gateway: text with request IDs
        rid = f"{rnd.randrange(16**8):08x}-{rnd.randrange(16**4):04x}"
        ev.append(
            Event(
                t + timedelta(seconds=19),
                api,
                api_stream,
                f"INFO requestId={rid} POST /api/orders 200",
                {"requestId": rid},
            )
        )
        if failing:
            rid = f"{rnd.randrange(16**8):08x}-{rnd.randrange(16**4):04x}"
            ev.append(
                Event(
                    t + timedelta(seconds=29),
                    api,
                    api_stream,
                    f"ERROR requestId={rid} upstream checkout-service returned 502 for POST /api/orders",
                    {"requestId": rid},
                )
            )
        t += timedelta(minutes=1)
    # lifecycle and configuration indicators (observations, not a change history)
    inv_json(CONFIG_EVENT - timedelta(seconds=40), "INFO", "SIGTERM received, shutting down gracefully", inv_stream)
    inv_json(CONFIG_EVENT, "INFO", "inventory-service 3.8.0 starting (build 9f2c1ab)", new_stream)
    inv_json(
        CONFIG_EVENT + timedelta(seconds=2),
        "INFO",
        "configuration loaded: db.pool.max_size=8 (previous 40) source=ssm:/shop/prod/inventory/db",
        new_stream,
    )
    inv_json(CONFIG_EVENT + timedelta(seconds=3), "INFO", "listening on :8080", new_stream)
    inv_json(
        RESTORE, "INFO", "configuration reloaded: db.pool.max_size=40 source=ssm:/shop/prod/inventory/db", new_stream
    )
    ev.append(
        Event(
            ONSET + timedelta(minutes=3, seconds=5),
            chk,
            chk_stream,
            f"WARN reserve-stock retry 2/3 using db_password={FAKE_SECRET}",
        )
    )
    ev.append(
        Event(
            START + timedelta(minutes=30, seconds=4),
            "/ecs/shop-prod/audit-worker",
            "ecs/audit-worker/0",
            "INFO audit batch flushed",
        )
    )
    # scenario groups
    for i in range(6):
        ts = START + timedelta(hours=1, minutes=i * 7)
        for g in ("/fixture/delayed", "/fixture/partial", "/fixture/uncorrelated", "/fixture/slow", "/fixture/failed"):
            ev.append(Event(ts, g, "s/0", f"ERROR synthetic failure {i} in {g.split('/')[-1]} (connection refused)"))
        ev.append(Event(ts, "/fixture/malformed", "s/0", f"ERROR malformed scenario event {i}"))
    return sorted(ev, key=lambda e: e.ts)


EVENTS = _story()


# ------------------------------------------------------------------------------------------------ metrics
def _metric_series(
    namespace: str, name: str, stat: str, dims: dict[str, str], period: int, start: datetime, end: datetime
) -> tuple[list[float], list[float], str]:
    """(timestamps, values, status) of one synthetic metric. Periods without data are absent, as in CloudWatch."""
    key = (
        namespace,
        name,
        dims.get("TargetGroup") or dims.get("ServiceName") or dims.get("FunctionName") or dims.get("Service"),
    )
    if namespace == "Fixture/Forbidden":
        return [], [], "Forbidden"
    if namespace == "AWS/Lambda":  # pricing-sync published nothing in the window
        return [], [], "Complete"
    rnd = random.Random(f"{key}-{stat}")
    t = max(start, START)
    t = t - timedelta(seconds=int(t.timestamp()) % period)
    stamps: list[float] = []
    values: list[float] = []
    while t < min(end, END):
        failing = ONSET <= t < RESTORE
        v: float | None
        if key == ("AWS/ApplicationELB", "TargetResponseTime", "targetgroup/inventory-service/8e2c4a6b1d3f5a97"):
            v = round(rnd.uniform(1.6, 2.2) if failing else rnd.uniform(0.012, 0.03), 4)
        elif key[1] == "TargetResponseTime":
            v = round(rnd.uniform(2.4, 2.8) if failing else rnd.uniform(0.07, 0.15), 4)
        elif key[1] == "HTTPCode_Target_5XX_Count":
            v = float(rnd.randint(30, 60)) if failing else (float(rnd.randint(1, 2)) if rnd.random() < 0.08 else None)
        elif key[1] == "RequestCount":
            v = float(rnd.randint(110, 150))
        elif key[1] == "UnHealthyHostCount":
            v = 0.0
        elif key[1] == "CPUUtilization":
            v = round(rnd.uniform(18, 26) if failing else rnd.uniform(22, 31), 2)
        elif key[1] == "MemoryUtilization":
            v = round(rnd.uniform(41, 44), 2)
        elif key == ("Shop/Inventory", "DbConnectionWaitTime", "inventory-service"):
            v = round(rnd.uniform(1700, 1990) if failing else rnd.uniform(3, 9), 1)
        else:
            v = None
        if v is not None and not (t.minute == 37 and key[1] == "CPUUtilization"):  # one gap: CPU not published
            stamps.append(t.timestamp())
            values.append(v)
        t += timedelta(seconds=period)
    return stamps, values, "Complete"


# ------------------------------------------------------------------------------------------------ Logs Insights
class Malformed(Exception):
    pass


_LIKE = re.compile(r"^\|?\s*filter\s+@message\s+like\s+/(.+)/\s*$")
_EQ = re.compile(r'^\|\s*filter\s+`([A-Za-z_@][A-Za-z0-9_.@-]*)`\s*=\s*"((?:[^"\\]|\\.)*)"\s*$')
_PRESENT = re.compile(r"^\|\s*filter\s+((?:ispresent\([@A-Za-z_]+\)(?:\s+or\s+)?)+)\s*$")
_STATS = re.compile(r"^\|\s*stats\s+count\(\*\)\s+as\s+value\s+by\s+bin\((\d+)([mh])\)\s+as\s+@t\s*$")
_LIMIT = re.compile(r"^\|\s*limit\s+(\d+)\s*$")


def run_query(
    query: str, groups: list[str], start: int, end: int, limit: int
) -> tuple[list[list[dict[str, str]]], dict[str, float]]:
    lines = [ln.strip() for ln in query.strip().splitlines() if ln.strip()]
    selected = [e for e in EVENTS if e.group in groups and start <= e.ts.timestamp() <= end]
    scanned = len(selected)
    fields: list[str] = ["@timestamp", "@message"]
    stats_bin: int | None = None
    max_rows = limit
    for ln in lines:
        if ln.startswith("fields "):
            fields = [f.strip() for f in ln[len("fields ") :].split(",")]
        elif m := _LIKE.match(ln):
            rx = re.compile(m.group(1))
            selected = [e for e in selected if rx.search(e.message)]
        elif m := _EQ.match(ln):
            name, value = m.group(1), m.group(2).replace('\\"', '"').replace("\\\\", "\\")
            selected = [e for e in selected if e.fields.get(name) == value]
        elif m := _PRESENT.match(ln):
            names = re.findall(r"ispresent\(([@A-Za-z_]+)\)", m.group(1))
            selected = [e for e in selected if any(n in e.fields for n in names)]
        elif m := _STATS.match(ln):
            stats_bin = int(m.group(1)) * (60 if m.group(2) == "m" else 3600)
        elif ln == "| sort @timestamp desc":
            selected = sorted(selected, key=lambda e: e.ts, reverse=True)
        elif m := _LIMIT.match(ln):
            max_rows = min(max_rows, int(m.group(1)))
        else:
            raise Malformed(f"unsupported query line: {ln[:60]}")
    stats = {
        "recordsMatched": float(len(selected)),
        "recordsScanned": float(scanned),
        "estimatedRecordsSkipped": 0.0,
        "bytesScanned": float(
            sum(len(e.message) + 60 for e in EVENTS if e.group in groups and start <= e.ts.timestamp() <= end)
        ),
        "estimatedBytesSkipped": 0.0,
        "logGroupsScanned": float(len(groups)),
    }
    if stats_bin:
        counts: dict[int, int] = {}
        for e in selected:
            b = int(e.ts.timestamp()) // stats_bin * stats_bin
            counts[b] = counts.get(b, 0) + 1
        rows = [
            [{"field": "@t", "value": _ts(datetime.fromtimestamp(b, UTC))}, {"field": "value", "value": str(n)}]
            for b, n in sorted(counts.items())
        ]
        return rows[:max_rows], stats
    rows = []
    for e in selected[:max_rows]:
        row: list[dict[str, str]] = []
        for f in fields:
            if f == "@timestamp":
                row.append({"field": f, "value": _ts(e.ts)})
            elif f == "@message":
                row.append({"field": f, "value": e.message})
            elif f == "@logStream":
                row.append({"field": f, "value": e.stream})
            elif f == "@log":
                row.append({"field": f, "value": f"{ACCOUNT}:{e.group}"})
            elif f in e.fields:
                row.append({"field": f, "value": e.fields[f]})
        row.append(
            {"field": "@ptr", "value": "Cm4KNQoh" + hashlib.sha256(f"{e.ts}{e.message}".encode()).hexdigest()[:24]}
        )
        rows.append(row)
    return rows, stats


@dataclass
class Query:
    id: str
    groups: list[str]
    scenario: str
    rows: list[list[dict[str, str]]]
    stats: dict[str, float]
    polls: int = 0
    stopped: bool = False


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.queries: dict[str, Query] = {}
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.calls: list[str] = []


STATE = State()


def _status(q: Query) -> str:
    if q.stopped:
        return "Cancelled"
    s = q.scenario
    if s in ("slow", "partial"):
        return "Running"
    if s == "failed":
        return "Failed"
    if s == "timeout":
        return "Timeout"
    if s == "cancelled":
        return "Cancelled"
    if s == "delayed":
        return ["Scheduled", "Running", "Running"][q.polls - 1] if q.polls <= 3 else "Complete"
    return "Running" if q.polls <= 1 else "Complete"


# ------------------------------------------------------------------------------------------------ HTTP
class AwsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


_CREDENTIAL = re.compile(r"Credential=([A-Z0-9]{16,128})/\d{8}/([a-z0-9-]+)/([a-z0-9-]+)/aws4_request")


class Handler(BaseHTTPRequestHandler):
    server_version = "cloudwatch-fixture"

    def log_message(self, fmt: str, *args: Any) -> None:  # quiet
        return

    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-amzn-RequestId", str(uuid.uuid4()))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/_fixture/state":
            with STATE.lock:
                doc = {"started": STATE.started, "stopped": STATE.stopped, "calls": STATE.calls[-200:]}
            self._send(200, json.dumps(doc).encode(), "application/json")
            return
        self._send(404, b"{}", "application/json")

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        target = self.headers.get("X-Amz-Target", "")
        m = _CREDENTIAL.search(self.headers.get("Authorization", ""))
        try:
            if target.startswith("Logs_20140328."):
                self._json(m, "logs", "application/x-amz-json-1.1", target.split(".", 1)[1], body)
            elif target.startswith("GraniteServiceVersion20100801."):
                self._json(m, "monitoring", "application/x-amz-json-1.0", target.split(".", 1)[1], body)
            else:
                self._sts(m, body)
        except BrokenPipeError:
            return

    def _scenario(self, m: re.Match[str] | None, service: str) -> str:
        if m is None:
            raise AwsError("MissingAuthenticationTokenException", "Missing Authentication Token", 400)
        if m.group(3) != service:
            raise AwsError("InvalidSignatureException", "Credential should be scoped to correct service", 400)
        scenario = KEYS.get(m.group(1))
        if scenario is None or scenario == "invalid":
            raise AwsError("UnrecognizedClientException", "The security token included in the request is invalid.", 400)
        if scenario == "expired":
            raise AwsError("ExpiredTokenException", "The security token included in the request is expired", 400)
        return scenario

    def _json(self, m: re.Match[str] | None, service: str, ctype: str, op: str, body: bytes) -> None:
        try:
            scenario = self._scenario(m, service)
            if scenario == "no_permissions":
                raise AwsError(
                    "AccessDeniedException",
                    f"User: arn:aws:sts::{ACCOUNT}:assumed-role/OpsPilotNoAccess/someone@example.com is not authorized to perform: {'logs' if service == 'logs' else 'cloudwatch'}:{op} because no identity-based policy allows the action",
                    400,
                )
            req = json.loads(body or b"{}")
            with STATE.lock:
                STATE.calls.append(op)
            doc = getattr(self, f"op_{op}")(req)
            self._send(200, json.dumps(doc).encode(), ctype)
        except AwsError as e:
            err = {"__type": e.code, "message": e.message}
            self._send(e.status, json.dumps(err).encode(), ctype, {"x-amzn-query-error": f"{e.code};Sender"})
        except (AttributeError, ValueError, KeyError) as e:
            err = {
                "__type": "InvalidParameterException",
                "message": f"fixture could not handle the request: {type(e).__name__}",
            }
            self._send(400, json.dumps(err).encode(), ctype)

    # -- CloudWatch Logs ----------------------------------------------------------------------------------------
    def op_StartQuery(self, req: dict[str, Any]) -> dict[str, Any]:
        groups = req.get("logGroupNames") or []
        if not groups or len(groups) > 50:
            raise AwsError("InvalidParameterException", "between 1 and 50 log groups are required")
        if req.get("queryLanguage") not in (None, "CWLI"):
            raise AwsError("InvalidParameterException", "unsupported query language in fixture")
        for g in groups:
            if g in DENIED_GROUPS:
                raise AwsError(
                    "AccessDeniedException",
                    f"User: arn:aws:sts::{ACCOUNT}:assumed-role/OpsPilotReadOnly/someone@example.com is not authorized to perform: logs:StartQuery on resource: arn:aws:logs:us-east-1:{ACCOUNT}:log-group:{g}:*",
                )
            if g not in EXISTING_GROUPS:
                raise AwsError(
                    "ResourceNotFoundException", f"Log group '{g}' does not exist for account ID '{ACCOUNT}'"
                )
        scenario = next((SCENARIOS[g] for g in groups if g in SCENARIOS), "story")
        if scenario == "throttled":
            raise AwsError("ThrottlingException", "Rate exceeded")
        if scenario == "limit":
            raise AwsError("LimitExceededException", "Account maximum query concurrency limit of [100] reached.")
        start, end, limit = int(req["startTime"]), int(req["endTime"]), int(req.get("limit") or 1000)
        if end < start:
            raise AwsError("InvalidParameterException", "endTime must be after startTime")
        try:
            rows, stats = run_query(str(req.get("queryString") or ""), groups, start, end, limit)
        except (Malformed, re.error) as e:
            raise AwsError("MalformedQueryException", str(e)) from None
        if scenario == "malformed":
            rows = [
                [{"field": "@timestamp", "value": "not-a-timestamp"}, {"field": "@message", "value": "x"}],
                [{"value": "no field name"}],
                *rows[:2],
            ]
        if scenario == "empty":
            rows = []
        qid = str(uuid.uuid4())
        with STATE.lock:
            STATE.queries[qid] = Query(qid, groups, scenario, rows, stats)
            STATE.started.append(qid)
        return {"queryId": qid}

    def op_GetQueryResults(self, req: dict[str, Any]) -> dict[str, Any]:
        with STATE.lock:
            q = STATE.queries.get(str(req.get("queryId")))
            if q is None:
                raise AwsError("ResourceNotFoundException", "Query does not exist")
            q.polls += 1
            status = _status(q)
        if status == "Complete" or (q.scenario == "partial" and q.polls > 1):
            results = q.rows if status == "Complete" else q.rows[: max(1, len(q.rows) // 2)]
            stats = q.stats
        else:
            results = []
            stats = {k: 0.0 for k in q.stats}
        return {"queryLanguage": "CWLI", "results": results, "statistics": stats, "status": status}

    def op_StopQuery(self, req: dict[str, Any]) -> dict[str, Any]:
        with STATE.lock:
            q = STATE.queries.get(str(req.get("queryId")))
            if q is None:
                raise AwsError("ResourceNotFoundException", "Query does not exist")
            if _status(q) in ("Complete", "Failed", "Timeout", "Cancelled"):
                raise AwsError("InvalidParameterException", "Query is not running")
            q.stopped = True
            STATE.stopped.append(q.id)
        return {"success": True}

    def op_DescribeLogGroups(self, req: dict[str, Any]) -> dict[str, Any]:
        ids = req.get("logGroupIdentifiers") or []
        groups = [
            {"logGroupName": g, "creationTime": 1735689600000, "retentionInDays": 30, "metricFilterCount": 0,
             "arn": f"arn:aws:logs:us-east-1:{ACCOUNT}:log-group:{g}:*", "storedBytes": 1048576, "logGroupClass": "STANDARD",
             "logGroupArn": f"arn:aws:logs:us-east-1:{ACCOUNT}:log-group:{g}"}
            for g in ids if g in EXISTING_GROUPS
        ]  # fmt: skip
        return {"logGroups": groups}

    # -- CloudWatch metrics ---------------------------------------------------------------------------------------
    def op_GetMetricData(self, req: dict[str, Any]) -> dict[str, Any]:
        start = datetime.fromtimestamp(float(req["StartTime"]), UTC)
        end = datetime.fromtimestamp(float(req["EndTime"]), UTC)
        results = []
        for q in req.get("MetricDataQueries") or []:
            ms = q["MetricStat"]
            metric = ms["Metric"]
            if int(ms["Period"]) % 60:
                raise AwsError("InvalidParameterCombination", "The parameter Period must be a multiple of 60.")
            dims = {d["Name"]: d["Value"] for d in metric.get("Dimensions") or []}
            stamps, values, status = _metric_series(
                metric["Namespace"], metric["MetricName"], ms["Stat"], dims, int(ms["Period"]), start, end
            )
            if req.get("ScanBy") != "TimestampAscending":
                stamps, values = stamps[::-1], values[::-1]
            results.append(
                {
                    "Id": q["Id"],
                    "Label": metric["MetricName"],
                    "Timestamps": stamps,
                    "Values": values,
                    "StatusCode": status,
                    "Messages": [],
                }
            )
        return {"MetricDataResults": results, "Messages": []}

    # -- STS ----------------------------------------------------------------------------------------------------
    def _sts(self, m: re.Match[str] | None, body: bytes) -> None:
        form = parse_qs(body.decode())
        try:
            if form.get("Action") != ["GetCallerIdentity"]:
                raise AwsError("InvalidAction", "Could not find operation", 400)
            try:
                scenario = self._scenario(m, "sts")
            except AwsError as e:
                code = {
                    "ExpiredTokenException": "ExpiredToken",
                    "UnrecognizedClientException": "InvalidClientTokenId",
                }.get(e.code, e.code)
                raise AwsError(code, e.message, 403) from None
            account = "444455556666" if scenario == "other_account" else ACCOUNT
            xml = (
                '<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/"><GetCallerIdentityResult>'
                f"<Arn>arn:aws:sts::{account}:assumed-role/OpsPilotReadOnly/fixture-operator@example.com</Arn>"
                f"<UserId>AROAFIXTURE000000000:fixture-operator@example.com</UserId><Account>{account}</Account>"
                f"</GetCallerIdentityResult><ResponseMetadata><RequestId>{uuid.uuid4()}</RequestId></ResponseMetadata>"
                "</GetCallerIdentityResponse>"
            )
            self._send(200, xml.encode(), "text/xml")
        except AwsError as e:
            xml = (
                f'<ErrorResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/"><Error><Type>Sender</Type><Code>{e.code}</Code>'
                f"<Message>{e.message}</Message></Error><RequestId>{uuid.uuid4()}</RequestId></ErrorResponse>"
            )
            self._send(e.status, xml.encode(), "text/xml")


def serve(port: int) -> ThreadingHTTPServer:
    STATE.__init__()  # type: ignore[misc]  # a fresh query table per server (tests start one per case)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    return httpd


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8131)
    args = ap.parse_args()
    httpd = serve(args.port)
    print(
        f"synthetic CloudWatch fixture on http://127.0.0.1:{args.port} (incident window {START:%Y-%m-%d %H:%M} to {END:%H:%M}Z)"
    )
    httpd.serve_forever()


if __name__ == "__main__":
    main()
