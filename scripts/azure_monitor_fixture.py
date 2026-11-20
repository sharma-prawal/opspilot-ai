"""Synthetic Azure Monitor Logs API fixture (v0.10): documented response shapes, fictional services, no real data.

Emulates ``POST /v1/workspaces/{workspaceId}/query`` of the Log Analytics Query API
(https://learn.microsoft.com/azure/azure-monitor/logs/api/overview): JSON body ``{"query", "timespan"}``, bearer
authentication, ``{"tables": [{"name": "PrimaryResult", "columns": [{"name", "type"}], "rows": [[...]]}]}`` answers
with Log Analytics column types (``datetime``, ``string``, ``bool``, ``int``, ``long``, ``real``, ``dynamic`` as JSON
text), HTTP 200 + ``error.code = "PartialError"`` for partial results, HTTP 204 for a workspace without data and
OneAPI error objects (``{"error": {"code", "message", "innererror"}}``) otherwise. It is a contract fixture, not
Azure: KQL is understood only as far as OpsPilot's built-in templates need (one table, ``where`` filters on
``AppRoleName =~``, ``Success``, ``SeverityLevel``, ``Message has_any``, ``OperationId in``; ``project``, ``extend`` of
exception frames, ``summarize … by bin(TimeGenerated, Ns)``, ``order by``, ``take``/``top``, ``union isfuzzy=true``
discovery and ``print``). Anything else is answered with HTTP 400 ``BadArgumentError``, as an unknown query would be.

The story (all synthetic, workspace-based Application Insights tables): at 10:28:10Z payment-service 2.14.0 starts and
loads ``db.pool.max_size=5`` (previously 50). From 10:31Z its SQL calls to orders-db wait for pooled connections,
``POST /payments`` fails with 503 after ~2 s, Npgsql pool-exhaustion exceptions are thrown, and orders-api's
``POST /orders`` answers 502. inventory-service stays healthy. At 11:12:30Z payment-service 2.13.4 starts with
``db.pool.max_size=50`` and the errors stop. orders-api is sampled at 50 % (``ItemCount`` 2), so a share of
payment-service requests reference a parent dependency that is not stored (incomplete correlation). A few traces have
no ``AppRoleName``, one role name (``Notification Worker``) cannot be an OpsPilot service name, ``Billing.Worker`` is
mixed case and only writes traces (no requests: its metrics are missing), and one trace carries a fake credential so
redaction can be seen. No deployment record exists anywhere: change history stays unknown.

Workspaces select scenarios (``WORKSPACES``); the default one holds the story. Usage::

    uv run python scripts/azure_monitor_fixture.py --port 8128          # ``make azure-fixture``

Then, for the API process only: ``AZURE_MONITOR_ENABLED=true AZURE_MONITOR_AUTH_MODE=fixture
AZURE_MONITOR_LOCAL_API_URL=http://127.0.0.1:8128 AZURE_MONITOR_WORKSPACE_ID=<a workspace below>``.
"""

# ruff: noqa: E501 - synthetic telemetry rows are kept one record per line for readability
from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

TOKEN = "opspilot-synthetic-fixture-token"  # noqa: S105 - the connector's fixture credential; synthetic
EXPIRED_TOKEN = "opspilot-synthetic-expired-token"  # noqa: S105 - answered with 401, to exercise token refresh
START = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
END = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
CHANGE = datetime(2026, 11, 16, 10, 28, 10, tzinfo=UTC)
ONSET = datetime(2026, 11, 16, 10, 31, tzinfo=UTC)
ROLLBACK = datetime(2026, 11, 16, 11, 12, 30, tzinfo=UTC)
INCIDENT_TIME = "2026-11-16T10:35:00Z"
WORKSPACE = "6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1001"  # the story
WORKSPACES = {
    WORKSPACE: "incident",
    "6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1002": "no_exceptions_table",  # AppExceptions (and AppDependencies) absent
    "6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1003": "partial",  # every query: HTTP 200 with a PartialError
    "6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1004": "malformed",  # 200 with a body that is not the documented shape
    "6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1005": "forbidden",  # 403 InsufficientAccessError (no RBAC role)
    "6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1006": "throttled",  # 429 with Retry-After: 30
    "6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1007": "gateway_timeout",  # 504: query exceeded the timeout
    "6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1008": "unavailable",  # 503
    "6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1009": "no_content",  # 204: workspace has no data
    "6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f100a": "redirect",  # 302 to another host: must never be followed
}
FAKE_SECRET = "Fixture-Pa55word-0000"  # noqa: S105 - synthetic value, shown redacted by OpsPilot

SCHEMA: dict[str, dict[str, str]] = {
    "AppRequests": {
        "TimeGenerated": "datetime", "Id": "string", "ParentId": "string", "OperationId": "string",
        "OperationName": "string", "Name": "string", "Url": "string", "ResultCode": "string", "Success": "bool",
        "DurationMs": "real", "AppRoleName": "string", "AppRoleInstance": "string", "AppVersion": "string",
        "ItemCount": "int", "Properties": "dynamic", "_ResourceId": "string",
    },
    "AppDependencies": {
        "TimeGenerated": "datetime", "Id": "string", "ParentId": "string", "OperationId": "string",
        "OperationName": "string", "Name": "string", "Target": "string", "DependencyType": "string",
        "Data": "string", "ResultCode": "string", "Success": "bool", "DurationMs": "real", "AppRoleName": "string",
        "AppRoleInstance": "string", "AppVersion": "string", "ItemCount": "int", "Properties": "dynamic",
        "_ResourceId": "string",
    },
    "AppExceptions": {
        "TimeGenerated": "datetime", "ProblemId": "string", "ExceptionType": "string", "OuterType": "string",
        "OuterMessage": "string", "InnermostType": "string", "InnermostMessage": "string", "Method": "string",
        "Assembly": "string", "Details": "dynamic", "SeverityLevel": "int", "OperationId": "string",
        "ParentId": "string", "AppRoleName": "string", "AppRoleInstance": "string", "AppVersion": "string",
        "ItemCount": "int", "Properties": "dynamic", "_ResourceId": "string",
    },
    "AppTraces": {
        "TimeGenerated": "datetime", "Message": "string", "SeverityLevel": "int", "OperationId": "string",
        "ParentId": "string", "AppRoleName": "string", "AppRoleInstance": "string", "AppVersion": "string",
        "ItemCount": "int", "Properties": "dynamic", "_ResourceId": "string",
    },
}  # fmt: skip
TABLES = tuple(SCHEMA)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "0Z"  # Log Analytics: 7 fractional digits


def _rid(app: str) -> str:
    return f"/subscriptions/00000000-0000-4000-8000-000000000000/resourceGroups/rg-fixture/providers/microsoft.insights/components/{app}"


# ------------------------------------------------------------------------------------------------------ data
@dataclass
class Data:
    rows: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {t: [] for t in TABLES})


def build() -> Data:
    rng = random.Random(20261116)
    d = Data()

    def hexid(n: int) -> str:
        return "".join(rng.choice("0123456789abcdef") for _ in range(n))

    def trace(ts: datetime, role: str | None, sev: int, msg: str, op: str = "", ver: str = "", **props: Any) -> None:
        d.rows["AppTraces"].append(
            {
                "TimeGenerated": ts, "Message": msg, "SeverityLevel": sev, "OperationId": op, "ParentId": op,
                "AppRoleName": role or "", "AppRoleInstance": f"{role}-0" if role else "", "AppVersion": ver,
                "ItemCount": 1, "Properties": props or None, "_ResourceId": _rid(role or "unknown"),
            }
        )  # fmt: skip

    def payment_version(ts: datetime) -> str:
        return "2.14.0" if CHANGE <= ts < ROLLBACK else "2.13.4"

    # lifecycle and configuration lines (observations only: no deployment record exists in the workspace)
    trace(START + timedelta(minutes=2), "inventory-service", 1, "inventory-service heartbeat ok", ver="5.2.1")
    trace(CHANGE, "payment-service", 1, "starting payment-service version=2.14.0", ver="2.14.0")
    trace(
        CHANGE + timedelta(seconds=1), "payment-service", 1,
        "configuration loaded: db.pool.max_size=5 db.pool.timeout_ms=2000 source=app-config revision=r-1842",
        ver="2.14.0", config_revision="r-1842",
    )  # fmt: skip
    trace(ROLLBACK, "payment-service", 1, "starting payment-service version=2.13.4", ver="2.13.4")
    trace(
        ROLLBACK + timedelta(seconds=1), "payment-service", 1,
        "configuration loaded: db.pool.max_size=50 db.pool.timeout_ms=2000 source=app-config revision=r-1841",
        ver="2.13.4", config_revision="r-1841",
    )  # fmt: skip
    for i in range(3):  # traces without a role name: cannot be queried by service
        trace(START + timedelta(minutes=40 + i), None, 2, "worker heartbeat delayed (no cloud role name configured)")
    trace(START + timedelta(minutes=55), "notification-worker", 1, "notification batch sent", ver="1.0.0")
    d.rows["AppTraces"][-1]["AppRoleName"] = "Notification Worker"  # not representable as an OpsPilot service name
    for m in range(0, 180, 15):
        t = START + timedelta(minutes=m, seconds=7)
        d.rows["AppTraces"].append(
            {
                "TimeGenerated": t, "Message": "nightly export chunk processed", "SeverityLevel": 1, "OperationId": "",
                "ParentId": "", "AppRoleName": "Billing.Worker", "AppRoleInstance": "billing-0", "AppVersion": "3.0.0",
                "ItemCount": 1, "Properties": None, "_ResourceId": _rid("billing-worker"),
            }
        )  # fmt: skip
    trace(
        START + timedelta(minutes=97), "inventory-service", 2, "cache refresh took 950 ms (threshold 800 ms)",
        ver="5.2.1",
    )  # fmt: skip

    # inventory-service: healthy traffic throughout
    t = START
    while t < END:
        op = hexid(32)
        d.rows["AppRequests"].append(
            {
                "TimeGenerated": t, "Id": hexid(16), "ParentId": op, "OperationId": op, "OperationName": "GET /stock/{sku}",
                "Name": "GET /stock/{sku}", "Url": "https://inventory.fixture.invalid/stock/SKU-1?debug=0", "ResultCode": "200",
                "Success": True, "DurationMs": round(rng.uniform(15, 45), 3), "AppRoleName": "inventory-service",
                "AppRoleInstance": "inventory-service-0", "AppVersion": "5.2.1", "ItemCount": 1, "Properties": None,
                "_ResourceId": _rid("inventory-service"),
            }
        )  # fmt: skip
        t += timedelta(seconds=30)

    # orders-api -> payment-service -> orders-db, one operation every 10 s; orders-api keeps every second one (50 %
    # adaptive sampling, ItemCount 2), payment-service keeps all of them.
    t = START + timedelta(seconds=3)
    n = 0
    while t < END:
        n += 1
        op = hexid(32)
        o_req, o_dep, p_req, p_dep = hexid(16), hexid(16), hexid(16), hexid(16)
        incident = ONSET <= t < ROLLBACK
        ramp = min(1.0, (t - ONSET).total_seconds() / 300) if incident else 0.0
        fail = incident and rng.random() < 0.15 + 0.6 * ramp
        version = payment_version(t)
        sql_ms = rng.uniform(2000, 2050) if fail else (rng.uniform(4, 12) * (6 if incident else 1))
        p_ms = sql_ms + rng.uniform(10, 30)
        o_dep_ms = p_ms + rng.uniform(5, 15)
        o_ms = o_dep_ms + rng.uniform(20, 60)
        kept = n % 2 == 0
        if kept:
            d.rows["AppRequests"].append(
                {
                    "TimeGenerated": t, "Id": o_req, "ParentId": op, "OperationId": op, "OperationName": "POST /orders",
                    "Name": "POST /orders", "Url": f"https://orders.fixture.invalid/orders?customer=c{n % 97}",
                    "ResultCode": "502" if fail else "201", "Success": not fail, "DurationMs": round(o_ms, 3),
                    "AppRoleName": "orders-api", "AppRoleInstance": f"orders-api-{n % 3}", "AppVersion": "7.4.2",
                    "ItemCount": 2, "Properties": None, "_ResourceId": _rid("orders-api"),
                }
            )  # fmt: skip
            d.rows["AppDependencies"].append(
                {
                    "TimeGenerated": t + timedelta(milliseconds=20), "Id": o_dep, "ParentId": o_req, "OperationId": op,
                    "OperationName": "POST /orders", "Name": "POST /payments", "Target": "payment-service",
                    "DependencyType": "HTTP", "Data": "https://payment-service/payments", "ResultCode": "503" if fail else "200",
                    "Success": not fail, "DurationMs": round(o_dep_ms, 3), "AppRoleName": "orders-api",
                    "AppRoleInstance": f"orders-api-{n % 3}", "AppVersion": "7.4.2", "ItemCount": 2,
                    "Properties": None, "_ResourceId": _rid("orders-api"),
                }
            )  # fmt: skip
            if fail:
                trace(
                    t + timedelta(milliseconds=int(o_ms)), "orders-api", 2,
                    f"payment call failed: 503 Service Unavailable from payment-service (order_id=o-{n})", op=op,
                    ver="7.4.2",
                )  # fmt: skip
                d.rows["AppTraces"][-1].update(ParentId=o_req, ItemCount=2)
        p_start = t + timedelta(milliseconds=25)
        d.rows["AppRequests"].append(
            {
                "TimeGenerated": p_start, "Id": p_req, "ParentId": o_dep, "OperationId": op,
                "OperationName": "POST /payments", "Name": "POST /payments", "Url": "https://payment-service/payments",
                "ResultCode": "503" if fail else "200", "Success": not fail, "DurationMs": round(p_ms, 3),
                "AppRoleName": "payment-service", "AppRoleInstance": f"payment-service-{n % 2}", "AppVersion": version,
                "ItemCount": 1, "Properties": None, "_ResourceId": _rid("payment-service"),
            }
        )  # fmt: skip
        d.rows["AppDependencies"].append(
            {
                "TimeGenerated": p_start + timedelta(milliseconds=3), "Id": p_dep, "ParentId": p_req, "OperationId": op,
                "OperationName": "POST /payments", "Name": "orders-db | payments_insert", "Target": "orders-db",
                "DependencyType": "SQL", "Data": "INSERT INTO payments (order_id, amount) VALUES (@p0, @p1)",
                "ResultCode": "timeout" if fail else "0", "Success": not fail, "DurationMs": round(sql_ms, 3),
                "AppRoleName": "payment-service", "AppRoleInstance": f"payment-service-{n % 2}", "AppVersion": version,
                "ItemCount": 1, "Properties": None, "_ResourceId": _rid("payment-service"),
            }
        )  # fmt: skip
        if fail:
            frames = [
                {"level": i, "method": m, "assembly": "Npgsql, Version=8.0.5.0", "fileName": f, "line": ln}
                for i, (m, f, ln) in enumerate(
                    [
                        ("Npgsql.PoolingDataSource.<Get>g__RentAsync", "PoolingDataSource.cs", 151),
                        ("Npgsql.NpgsqlConnection.<Open>g__OpenAsync", "NpgsqlConnection.cs", 382),
                        ("Payments.Data.PaymentRepository.InsertAsync", "PaymentRepository.cs", 58),
                        ("Payments.Api.PaymentsController.Create", "PaymentsController.cs", 41),
                        *[(f"Microsoft.AspNetCore.Mvc.Infrastructure.Invoker.Step{k}", None, None) for k in range(10)],
                    ]
                )
            ]
            d.rows["AppExceptions"].append(
                {
                    "TimeGenerated": p_start + timedelta(milliseconds=2004), "ProblemId": "Npgsql.NpgsqlException at Npgsql.PoolingDataSource.RentAsync",
                    "ExceptionType": "Npgsql.NpgsqlException", "OuterType": "Npgsql.NpgsqlException",
                    "OuterMessage": "The connection pool has been exhausted, either raise 'Max Pool Size' (currently 5) or 'Timeout' (currently 2 seconds)",
                    "InnermostType": "System.TimeoutException", "InnermostMessage": "The operation has timed out.",
                    "Method": "Npgsql.PoolingDataSource.RentAsync", "Assembly": "Npgsql, Version=8.0.5.0",
                    "Details": [{"outerId": "0", "type": "Npgsql.NpgsqlException", "message": "The connection pool has been exhausted", "hasFullStack": True, "parsedStack": frames}],
                    "SeverityLevel": 3, "OperationId": op, "ParentId": p_req, "AppRoleName": "payment-service",
                    "AppRoleInstance": f"payment-service-{n % 2}", "AppVersion": version, "ItemCount": 1, "Properties": None,
                    "_ResourceId": _rid("payment-service"),
                }
            )  # fmt: skip
            trace(
                p_start + timedelta(milliseconds=2001), "payment-service", 2,
                "waited 2000 ms for a database connection from the pool (in use 5/5, waiting 14)", op=op, ver=version,
            )  # fmt: skip
            d.rows["AppTraces"][-1]["ParentId"] = p_req
            if kept and n % 8 == 0:
                d.rows["AppExceptions"].append(
                    {
                        "TimeGenerated": t + timedelta(milliseconds=int(o_ms)), "ProblemId": "System.Net.Http.HttpRequestException",
                        "ExceptionType": "System.Net.Http.HttpRequestException", "OuterType": "System.Net.Http.HttpRequestException",
                        "OuterMessage": "Response status code does not indicate success: 503 (Service Unavailable).",
                        "InnermostType": "System.Net.Http.HttpRequestException",
                        "InnermostMessage": "Response status code does not indicate success: 503 (Service Unavailable).",
                        "Method": "Orders.Api.PaymentClient.ChargeAsync", "Assembly": "Orders.Api", "Details": None,
                        "SeverityLevel": 3, "OperationId": op, "ParentId": o_req, "AppRoleName": "orders-api",
                        "AppRoleInstance": f"orders-api-{n % 3}", "AppVersion": "7.4.2", "ItemCount": 2,
                        "Properties": None, "_ResourceId": _rid("orders-api"),
                    }
                )  # fmt: skip
        t += timedelta(seconds=10)
    trace(
        ONSET + timedelta(minutes=6), "payment-service", 3,
        f"retrying with connection string Host=orders-db;Username=payments;Password={FAKE_SECRET}", ver="2.14.0",
    )  # fmt: skip
    for rows in d.rows.values():
        rows.sort(key=lambda r: r["TimeGenerated"])
    return d


# ------------------------------------------------------------------------------------------------------ KQL subset
class KqlError(Exception):
    def __init__(self, inner: str, message: str) -> None:
        super().__init__(message)
        self.inner, self.message = inner, message


_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _strings(text: str) -> list[str]:
    return [json.loads(f'"{m}"') for m in _STRING.findall(text)]


def _span(timespan: str | None, now: datetime) -> tuple[datetime, datetime]:
    if not timespan:
        return datetime(2000, 1, 1, tzinfo=UTC), now
    if "/" in timespan:
        a, b = timespan.split("/", 1)
        return (
            datetime.fromisoformat(a.replace("Z", "+00:00")),
            datetime.fromisoformat(b.replace("Z", "+00:00")),
        )
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", timespan)
    if not m:
        raise KqlError("BadArgumentError", f"invalid timespan {timespan!r}")
    d, h, mi = (int(x or 0) for x in m.groups())
    return now - timedelta(days=d, hours=h, minutes=mi), now


def _terms(message: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", message.lower()) if t}


def _wpercentile(pairs: list[tuple[float, int]], pct: float) -> float:
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    acc = 0
    for v, w in pairs:
        acc += w
        if acc >= total * pct / 100:
            return v
    return pairs[-1][0]


def run_kql(query: str, timespan: str | None, data: Data, tables: tuple[str, ...], now: datetime) -> dict[str, Any]:
    lines = [ln.strip() for ln in query.strip().split("\n") if ln.strip()]
    head = lines[0]
    lo, hi = _span(timespan, now)
    if head.startswith("print "):
        name = head[6:].split("=")[0].strip()
        return {"name": "PrimaryResult", "columns": [{"name": name, "type": "long"}], "rows": [[1]]}
    if head.startswith("union isfuzzy=true"):
        wanted = [t.strip() for t in head.removeprefix("union isfuzzy=true").split(",")]
        counts: dict[str, int] = {}
        for tbl in wanted:
            if tbl in tables:
                for r in data.rows[tbl]:
                    if lo <= r["TimeGenerated"] <= hi:
                        counts[r["AppRoleName"]] = counts.get(r["AppRoleName"], 0) + 1
        top = int(re.search(r"top (\d+) by records", query).group(1))  # type: ignore[union-attr]
        ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:top]
        return {
            "name": "PrimaryResult",
            "columns": [{"name": "AppRoleName", "type": "string"}, {"name": "records", "type": "long"}],
            "rows": [[k, v] for k, v in ranked],
        }
    table = head.split()[0]
    if table not in SCHEMA:
        raise KqlError("SEM0100", f"'{table}' operator: Failed to resolve table or column expression named '{table}'")
    if table not in tables:
        raise KqlError("SEM0100", f"'where' operator: Failed to resolve table or column expression named '{table}'")
    rows = [r for r in data.rows[table] if lo <= r["TimeGenerated"] <= hi]
    columns = list(SCHEMA[table])
    types = dict(SCHEMA[table])
    out_rows: list[dict[str, Any]] | None = None
    for ln in lines[1:]:
        if not ln.startswith("|"):
            raise KqlError("SYN0002", f"unexpected text {ln[:40]!r}")
        op = ln[1:].strip()
        if op.startswith("where "):
            cond = op[6:].strip()
            if m := re.fullmatch(r'AppRoleName =~ ("(?:[^"\\]|\\.)*")', cond):
                want = json.loads(m.group(1)).lower()
                rows = [r for r in rows if str(r["AppRoleName"]).lower() == want]
            elif cond == "Success == false":
                rows = [r for r in rows if r.get("Success") is False]
            elif m := re.fullmatch(r"SeverityLevel >= (\d)", cond):
                rows = [r for r in rows if (r.get("SeverityLevel") or 0) >= int(m.group(1))]
            elif cond.startswith("Message has_any ("):
                words = {w.lower() for w in _strings(cond)}
                rows = [r for r in rows if words & _terms(str(r.get("Message") or ""))]
            elif cond.startswith("OperationId in ("):
                ids = set(_strings(cond))
                rows = [r for r in rows if r.get("OperationId") in ids]
            else:
                raise KqlError("SYN0002", f"the fixture does not understand 'where {cond[:60]}'")
        elif op.startswith("extend Frames = array_slice(Details[0].parsedStack, 0, 9)"):
            ext = []
            for r in rows:
                det = r.get("Details") or []
                stack = det[0].get("parsedStack") if det and isinstance(det[0], dict) else None
                ext.append(
                    {
                        **r,
                        "Frames": stack[:10] if stack else None,
                        "FrameCount": len(stack) if stack else None,
                        "HasFullStack": str(det[0].get("hasFullStack")).lower() if det else "",
                    }
                )
            rows = ext
            types |= {"Frames": "dynamic", "FrameCount": "int", "HasFullStack": "string"}
            columns += ["Frames", "FrameCount", "HasFullStack"]
        elif op.startswith("project "):
            wanted = [c.strip() for c in op[8:].split(",")]
            unknown = [c for c in wanted if c not in types]
            if unknown:
                raise KqlError(
                    "SEM0100", f"'project' operator: Failed to resolve scalar expression named '{unknown[0]}'"
                )
            columns = wanted
        elif op.startswith("summarize "):
            m = re.search(r"by bin\(TimeGenerated, (\d+)s\)$", op)
            if not m:
                raise KqlError("SYN0002", "the fixture supports summarize … by bin(TimeGenerated, <n>s) only")
            step = int(m.group(1))
            bins: dict[datetime, list[dict[str, Any]]] = {}
            for r in rows:
                epoch = int(r["TimeGenerated"].timestamp())
                b = datetime.fromtimestamp(epoch - epoch % step, UTC)
                bins.setdefault(b, []).append(r)
            out_rows = []
            for b, rs in bins.items():
                items = sum(r["ItemCount"] for r in rs)
                if "percentilew(DurationMs, ItemCount, 95)" in op:
                    value: float | None = _wpercentile([(r["DurationMs"], r["ItemCount"]) for r in rs], 95)
                elif "sumif(ItemCount, Success == false)" in op:
                    value = sum(r["ItemCount"] for r in rs if r["Success"] is False) / items
                elif "toint(ResultCode) between (500 .. 599)" in op:
                    value = sum(r["ItemCount"] for r in rs if str(r["ResultCode"]).isdigit() and 500 <= int(r["ResultCode"]) <= 599) / items  # fmt: skip
                elif m2 := re.search(r"todouble\(sum\(ItemCount\)\) \* 60\.0 / ([\d.]+)", op):
                    value = items * 60.0 / float(m2.group(1))
                else:
                    raise KqlError("SYN0002", "the fixture does not understand this summarize expression")
                out_rows.append({"TimeGenerated": b, "value": value, "records": len(rs), "items": items})
            columns = ["TimeGenerated", "value", "records", "items"]
            types = {"TimeGenerated": "datetime", "value": "real", "records": "long", "items": "long"}
            rows = out_rows
        elif m := re.fullmatch(r"order by TimeGenerated (asc|desc)", op):
            rows = sorted(rows, key=lambda r: r["TimeGenerated"], reverse=m.group(1) == "desc")
        elif m := re.fullmatch(r"take (\d+)", op):
            rows = rows[: int(m.group(1))]
        elif m := re.fullmatch(r"top (\d+) by DurationMs desc", op):
            rows = sorted(rows, key=lambda r: -r["DurationMs"])[: int(m.group(1))]
        else:
            raise KqlError("SYN0002", f"the fixture does not understand '| {op[:50]}'")
    return {
        "name": "PrimaryResult",
        "columns": [{"name": c, "type": types[c]} for c in columns],
        "rows": [[_cell(r.get(c), types[c]) for c in columns] for r in rows],
    }


def _cell(value: Any, typ: str) -> Any:
    if value is None:
        return None if typ != "string" else ""
    if typ == "datetime":
        return iso(value)
    if typ == "dynamic":
        return json.dumps(value)
    return value


# ------------------------------------------------------------------------------------------------------ server
def _error(status: int, code: str, message: str, inner: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    err: dict[str, Any] = {"code": code, "message": message, "correlationId": "00000000-0000-4000-8000-0000000f1c70"}
    if inner:
        err["innererror"] = inner
    return status, {"error": err}


@dataclass
class Fixture:
    data: Data = field(default_factory=build)
    requests: list[dict[str, Any]] = field(default_factory=list)
    scenario: dict[str, str] = field(default_factory=lambda: dict(WORKSPACES))
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    retry_after: str = "30"

    def handle(self, method: str, path: str, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        hdr = {k.lower(): v for k, v in headers.items()}
        doc: Any = None
        if body:
            try:
                doc = json.loads(body)
            except json.JSONDecodeError:
                doc = None
        self.requests.append({"method": method, "path": path, "headers": hdr, "body": doc})
        status, extra, payload = self._route(method, path, hdr, doc)
        if status == 204:
            return 204, extra, b""
        if isinstance(payload, bytes):
            return status, {"content-type": "application/json", **extra}, payload
        return status, {"content-type": "application/json; charset=utf-8", **extra}, json.dumps(payload).encode()

    def _route(
        self, method: str, path: str, hdr: dict[str, str], doc: Any
    ) -> tuple[int, dict[str, str], dict[str, Any] | bytes]:
        m = re.fullmatch(r"/v1/workspaces/([0-9a-f-]{36})/query", path)
        if not m:
            s, p = _error(404, "PathNotFoundError", f"The requested path does not exist: {path[:80]}")
            return s, {}, p
        auth = hdr.get("authorization", "")
        if not auth:
            s, p = _error(401, "AuthenticationFailed", "Authentication failed. The 'Authorization' header is missing.")
            return s, {}, p
        if auth == f"Bearer {EXPIRED_TOKEN}":
            s, p = _error(401, "AuthenticationFailed", "Authentication failed. The access token has expired.")
            return s, {"www-authenticate": 'Bearer error="invalid_token"'}, p
        if auth != f"Bearer {TOKEN}":
            s, p = _error(403, "InvalidAuthenticationToken", "The access token is invalid.")
            return s, {}, p
        if method != "POST":
            s, p = _error(405, "MethodNotAllowed", "The fixture serves POST queries only.")
            return s, {}, p
        scenario = self.scenario.get(m.group(1))
        if scenario is None:
            s, p = _error(
                404, "WorkspaceNotFoundError", f"The workspace {m.group(1)} could not be found.",
            )  # fmt: skip
            return s, {}, p
        if scenario == "forbidden":
            s, p = _error(
                403, "InsufficientAccessError", "The provided credentials have insufficient access to perform the "
                "requested operation", {"code": "InsufficientAccessError", "message": "missing workspaces/query/read"},
            )  # fmt: skip
            return s, {}, p
        if scenario == "throttled":
            s, p = _error(429, "ThrottledError", "Your request was throttled. Please retry later.")
            return s, {"retry-after": self.retry_after}, p
        if scenario == "gateway_timeout":
            s, p = _error(504, "GatewayTimeout", "The query exceeded the time limit.")
            return s, {}, p
        if scenario == "unavailable":
            s, p = _error(503, "ServiceUnavailable", "The service is temporarily unavailable.")
            return s, {}, p
        if scenario == "redirect":
            return 302, {"location": "http://169.254.169.254/metadata"}, b""
        if scenario == "no_content":
            return 204, {}, b""
        if scenario == "malformed":
            return 200, {}, {"tables": [{"name": "PrimaryResult", "columns": "not-a-list", "rows": {}}]}
        if not isinstance(doc, dict) or not isinstance(doc.get("query"), str):
            s, p = _error(400, "BadArgumentError", "The request had some invalid properties", {"code": "QueryMissing"})
            return s, {}, p
        tables = tuple(t for t in TABLES if not (scenario == "no_exceptions_table" and t in ("AppExceptions", "AppDependencies")))  # fmt: skip
        try:
            table = run_kql(doc["query"], doc.get("timespan"), self.data, tables, self.now)
        except KqlError as exc:
            s, p = _error(
                400, "BadArgumentError", "The request had some invalid properties",
                {"code": "SemanticError" if exc.inner.startswith("SEM") else "SyntaxError",
                 "message": "A semantic error occurred." if exc.inner.startswith("SEM") else "A syntax error occurred.",
                 "innererror": {"code": exc.inner, "message": exc.message}},
            )  # fmt: skip
            return s, {}, p
        except (ValueError, AttributeError) as exc:
            s, p = _error(400, "BadArgumentError", f"The request had some invalid properties ({type(exc).__name__})")
            return s, {}, p
        if scenario == "partial":
            table["rows"] = table["rows"][: len(table["rows"]) // 2]
            return 200, {}, {
                "tables": [table],
                "error": {
                    "code": "PartialError",
                    "message": "There were some errors when processing your query.",
                    "details": [{"code": "EngineError", "message": "Query result set exceeded an internal limit on one shard."}],
                },
            }  # fmt: skip
        return 200, {}, {"tables": [table]}


def serve(port: int) -> None:
    fixture = Fixture()

    class Handler(BaseHTTPRequestHandler):
        def _go(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else b""
            status, headers, payload = fixture.handle(self.command, self.path.split("?")[0], dict(self.headers), body)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = _go

        def log_message(self, fmt: str, *args: Any) -> None:  # requests carry the synthetic token only; keep quiet
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(
        f"synthetic Azure Monitor fixture on http://127.0.0.1:{port} (synthetic data only; Ctrl-C to stop)", flush=True
    )
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=8128)
    serve(parser.parse_args().port)
