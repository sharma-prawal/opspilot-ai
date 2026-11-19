"""Datadog connector (v0.9): logs, metrics and APM spans over the official API, read-only.

One connector serves three signals; each approved template names the one it returns. Endpoints used
(https://docs.datadoghq.com/api/latest/):

- ``GET  /api/v1/validate``: is the API key valid (``{"valid": true}``); the connection test starts here;
- ``POST /api/v2/logs/events/search`` (``logs_read_data``): ``filter`` {from, to, query, indexes}, ``sort``, ``page``
  {limit, cursor}; ``data[]`` of ``{id, type: "log", attributes: {timestamp, status, service, host, message, tags,
  attributes}}``, next cursor in ``meta.page.after``, ``meta.status`` ``done``/``timeout``, ``meta.warnings``;
- ``POST /api/v2/logs/analytics/aggregate`` (``logs_read_data``): log counts grouped by the ``service`` facet, used
  only for bounded service discovery (one window, at most 50 services);
- ``POST /api/v2/query/timeseries`` (``timeseries_query``): ``data`` {type: ``timeseries_request``, attributes:
  {from, to (ms), interval (ms), queries[{data_source: metrics, query, name}], formulas[{formula}]}}; answer
  ``data.attributes`` {series[{group_tags, query_index, unit}], times[], values[][]} and a top-level ``errors``;
- ``POST /api/v2/spans/events/search`` (APM, ``apm_read``): ``data`` {type: ``search_request``, attributes: {filter,
  sort, page}}; ``data[]`` of ``{id, type: "spans", attributes: {trace_id, span_id, parent_id, service,
  resource_name, type, start_timestamp, end_timestamp, env, host, tags, attributes, custom, ...}}``. Documented rate
  limit: 50 requests per minute per organization.

Those four POST paths are the connector's whole POST allowlist: they are search/query endpoints that only read. No
Datadog write, delete, monitor, dashboard or administrative API is reachable (``ReadOnlyHttp`` has no other method
and no other path).

Destinations are fixed: ``https://api.<site>`` for a site in ``SITES`` (the documented sites). Nothing in a request
can name a host. ``DATADOG_LOCAL_API_URL`` exists only for the synthetic fixture (``make datadog-fixture``) and is
refused unless it is a loopback address. Keys are sent as ``DD-API-KEY`` / ``DD-APPLICATION-KEY`` headers, never
appear in info, errors or snapshots, and any echo of them is scrubbed.

Normalization never invents data: missing metric points stay missing (Datadog ``null``), indexed spans are a sample
(retention filters), so a span whose parent was not returned marks its trace as partial, and a span's status is
``error`` only when Datadog says so (``status:error`` filter or an error flag), otherwise ``unset`` (not ``ok``).
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

from opspilot_shared.connectors.base import HttpConnector, step_for
from opspilot_shared.connectors.contract import (
    ConnectionStatus,
    ConnectorError,
    FetchResult,
    FetchWindow,
    QueryProvenance,
    QueryTemplate,
    Signal,
    SignalStatus,
)
from opspilot_shared.connectors.http import is_loopback
from opspilot_shared.connectors.templates import _SERVICE, datadog_metric_parts
from opspilot_shared.uploads.model import LogRecord, MetricRecord, SpanRecord
from opspilot_shared.uploads.parse import infer_level, log_line_fields, map_level, normalize_service, scrub

# Documented Datadog sites: site parameter -> (API host, web app host). https://docs.datadoghq.com/getting_started/site/
SITES: dict[str, tuple[str, str]] = {
    "datadoghq.com": ("api.datadoghq.com", "app.datadoghq.com"),
    "us3.datadoghq.com": ("api.us3.datadoghq.com", "us3.datadoghq.com"),
    "us5.datadoghq.com": ("api.us5.datadoghq.com", "us5.datadoghq.com"),
    "datadoghq.eu": ("api.datadoghq.eu", "app.datadoghq.eu"),
    "ap1.datadoghq.com": ("api.ap1.datadoghq.com", "ap1.datadoghq.com"),
    "ap2.datadoghq.com": ("api.ap2.datadoghq.com", "ap2.datadoghq.com"),
    "uk1.datadoghq.com": ("api.uk1.datadoghq.com", "uk1.datadoghq.com"),
    "ddog-gov.com": ("api.ddog-gov.com", "app.ddog-gov.com"),
    "us2.ddog-gov.com": ("api.us2.ddog-gov.com", "us2.ddog-gov.com"),
}
VALIDATE = "/api/v1/validate"
LOGS_SEARCH = "/api/v2/logs/events/search"
LOGS_AGGREGATE = "/api/v2/logs/analytics/aggregate"
TIMESERIES = "/api/v2/query/timeseries"
SPANS_SEARCH = "/api/v2/spans/events/search"
PERMISSION = {"log": "logs_read_data", "metric": "timeseries_query", "span": "apm_read"}
PRODUCT = {"log": "Log Management", "metric": "Metrics", "span": "APM"}
PAGE_LIMIT = 1000  # records per page asked of Datadog
MAX_PAGES = 5  # pages per query, whatever the record limit
MAX_DISCOVERED = 50
CONCURRENCY = 2  # Datadog requests in flight per connector (spans search: 50 requests/min per organization)
_ENV = re.compile(r"^[a-z0-9][a-z0-9_.:/-]{0,99}$")
_INDEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_TRACE_ID = re.compile(r"^(?:[0-9a-f]{16,32}|[0-9]{1,39})$")
_LOG_LEVELS = {"emergency": "ERROR", "alert": "ERROR", "critical": "ERROR", "error": "ERROR", "warn": "WARN"}
_LOG_LEVELS |= {"warning": "WARN", "notice": "INFO", "info": "INFO", "ok": "INFO", "debug": "DEBUG", "trace": "DEBUG"}


def resolve_site(site: str, local_api_url: str = "") -> tuple[str, str, str | None]:
    """(site, API base URL, web app host or None). Raises ``ConnectorError('not_configured')`` for anything else."""
    key = site.strip().lower()
    if key not in SITES:
        allowed = ", ".join(SITES)
        raise ConnectorError("not_configured", f"unsupported DATADOG_SITE {site.strip()[:60]!r}; use one of: {allowed}")
    local = local_api_url.strip()
    if local:
        try:
            parts = urlsplit(local)
        except ValueError as exc:
            raise ConnectorError("not_configured", f"invalid DATADOG_LOCAL_API_URL: {exc}") from exc
        if parts.scheme not in ("http", "https") or not parts.hostname or not is_loopback(parts.hostname):
            raise ConnectorError(
                "not_configured",
                "DATADOG_LOCAL_API_URL is only for the local synthetic fixture and must be a loopback address "
                "(http://127.0.0.1:<port>); leave it empty to use the Datadog site",
            )
        return key, local, None
    api, app = SITES[key]
    return key, f"https://{api}", app


def _iso_ms(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _epoch_ms(dt: datetime) -> int:
    delta = dt - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else None


def _tz_of(raw: str) -> str:
    if raw.endswith("Z"):
        return "Z"
    m = re.search(r"[+-]\d{2}:\d{2}$", raw)
    return m.group(0) if m else "UTC"


def _flat(obj: Any, prefix: str = "", out: dict[str, Any] | None = None, depth: int = 0) -> dict[str, Any]:
    out = {} if out is None else out
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and depth < 4 and len(out) < 200:
            _flat(v, f"{key}.", out, depth + 1)
        elif len(out) < 200:
            out.setdefault(key, v)
    return out


def _scalar(v: Any) -> Any:
    if isinstance(v, bool | int | float):
        return v
    text, _ = scrub(str(v))
    return text[:300]


def _tags(tags: Any, limit: int = 12) -> dict[str, str]:
    out: dict[str, str] = {}
    for t in tags if isinstance(tags, list) else []:
        if isinstance(t, str) and ":" in t and len(out) < limit:
            k, _, v = t.partition(":")
            out.setdefault(k[:40], scrub(v)[0][:120])
    return out


class DatadogConnector(HttpConnector):
    KIND = "datadog"
    SIGNAL = "log"
    NAME = "Datadog"

    def __init__(
        self,
        *,
        site: str,
        api_key: str,
        app_key: str,
        env: str = "",
        log_indexes: list[str] | None = None,
        max_spans: int = 500,
        local_api_url: str = "",
        **kw: Any,
    ) -> None:
        if not api_key.strip() or not app_key.strip():
            raise ConnectorError(
                "not_configured", "set both DATADOG_API_KEY and DATADOG_APP_KEY (a read-only application key)"
            )
        self.site, url, self.app_host = resolve_site(site, local_api_url)
        self.fixture = bool(local_api_url.strip())
        env = env.strip().lower()
        if env and not _ENV.match(env):
            raise ConnectorError("not_configured", "DATADOG_ENV must be a Datadog env tag value such as prod")
        self.env = env
        indexes = [i.strip() for i in log_indexes or [] if i.strip()]
        if any(not _INDEX.match(i) for i in indexes) or len(indexes) > 10:
            raise ConnectorError("not_configured", "DATADOG_LOG_INDEXES must be up to 10 comma-separated index names")
        self.log_indexes = indexes or ["*"]
        self.max_spans = max(10, min(int(max_spans), 2000))
        self._gate = asyncio.Semaphore(CONCURRENCY)
        super().__init__(
            url=url,
            service_label="service",
            headers={"DD-API-KEY": api_key.strip(), "DD-APPLICATION-KEY": app_key.strip()},
            header_credentials=True,
            max_retries=2,
            max_retry_wait=10.0,
            **kw,
        )
        self._auth_mode = "API key + application key"

    # -- configuration ------------------------------------------------------------------------------------------
    def allowed_paths(self) -> list[str]:
        return [VALIDATE]

    def allowed_post_paths(self) -> list[str]:
        return [LOGS_SEARCH, LOGS_AGGREGATE, TIMESERIES, SPANS_SEARCH]

    @property
    def signals(self) -> tuple[Signal, ...]:
        present = {t.returns for t in self._templates}
        return tuple(s for s in ("log", "metric", "span") if s in present)  # type: ignore[return-value]

    def extra_info(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "fixture": self.fixture,
            "env": self.env or None,
            "log_indexes": self.log_indexes,
            "permissions": {s: PERMISSION[s] for s in self.signals},
            "read_only_endpoints": [f"GET {VALIDATE}", *(f"POST {p}" for p in self.allowed_post_paths())],
            "limits_extra": {"max_spans_per_query": self.max_spans, "max_pages_per_query": MAX_PAGES},
        }

    def selector(self, service: str, signal: Signal) -> str:
        if not _SERVICE.match(service):
            raise ConnectorError("invalid_request", "service must be a lower-case slug such as checkout-api")
        if signal == "metric":
            return f"service:{service}" + (f",env:{self.env}" if self.env else "")
        return f"service:{service}" + (f" env:{self.env}" if self.env else "")

    def render(self, t: QueryTemplate, service: str) -> str:
        return t.query.replace("$selector", self.selector(service, t.returns))

    def link(self, signal: Signal, query: str) -> str | None:
        """Log Explorer search for the query (``/logs?query=``, documented in Datadog's context-links guide). No
        link for metrics and spans: no documented, stable URL scheme was verified for them."""
        if self.app_host is None or signal != "log":
            return None
        return f"https://{self.app_host}/logs?query={quote(query, safe='')}"

    # -- requests -----------------------------------------------------------------------------------------------
    async def _post(self, path: str, body: dict[str, Any], signal: Signal) -> Any:
        async with self._gate:
            try:
                doc, _ = await self.http.post_json(path, body)
            except ConnectorError as exc:
                raise self._explain(exc, signal) from None
        if not isinstance(doc, dict):
            raise ConnectorError("invalid_response", "Datadog did not answer with a JSON object")
        return doc

    def _explain(self, exc: ConnectorError, signal: Signal) -> ConnectorError:
        """Datadog answers 403 both for a bad application key and for a missing permission; say which to check."""
        if exc.status == 403:
            return ConnectorError(
                "permission_denied",
                f"{exc.message.split('. Check')[0]}. The application key is invalid, or it (or its owner) lacks the "
                f"{PERMISSION[signal]} permission for {PRODUCT[signal]}",
                status=403,
            )
        if exc.status == 404:
            return ConnectorError(
                "unsupported", f"HTTP 404: {PRODUCT[signal]} search is not available on this site/account", status=404
            )
        return exc

    def _issues(self, doc: dict[str, Any], prov: QueryProvenance) -> None:
        meta = _meta(doc)
        if meta.get("status") == "timeout":
            prov.truncated = True
            msg = "Datadog reported a query timeout: the results may be partial"
            if msg not in prov.issues:
                prov.issues.append(msg)
        for w in (meta.get("warnings") or [])[:3]:
            if isinstance(w, dict):
                text = self.http.clean(f"Datadog: {w.get('title') or w.get('code')}: {w.get('detail') or ''}", 200)
                if text not in prov.issues:
                    prov.issues.append(text)

    async def _search(
        self, path: str, attributes: dict[str, Any], limit: int, signal: Signal, prov: QueryProvenance, *, wrap: bool
    ) -> list[dict[str, Any]]:
        """Cursor pagination with a record limit and a page ceiling. ``wrap``: spans nest the body in ``data``."""
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        pages = 0
        while True:
            page: dict[str, Any] = {"limit": min(PAGE_LIMIT, limit - len(items))}
            if cursor:
                page["cursor"] = cursor
            attrs = {**attributes, "page": page}
            body = {"data": {"type": "search_request", "attributes": attrs}} if wrap else attrs
            doc = await self._post(path, body, signal)
            pages += 1
            data = doc.get("data")
            if not isinstance(data, list):
                raise ConnectorError("invalid_response", "Datadog search did not return a data list")
            self._issues(doc, prov)
            items.extend(d for d in data if isinstance(d, dict))
            prov.rejected += sum(1 for d in data if not isinstance(d, dict))
            meta = _meta(doc)
            after = (meta.get("page") or {}).get("after") if isinstance(meta.get("page"), dict) else None
            cursor = after if isinstance(after, str) and after else None
            if cursor is None or not data:
                break
            if len(items) >= limit or pages >= MAX_PAGES:
                prov.truncated = True
                prov.issues.append(
                    f"the {limit}-record limit was reached ({pages} page(s)): only the most recent records of the "
                    "window are included"
                    if len(items) >= limit
                    else f"the {MAX_PAGES}-page limit was reached: only the most recent records are included"
                )
                break
        prov.pages = pages
        return items[:limit]

    # -- TelemetryConnector -------------------------------------------------------------------------------------
    async def test(self) -> ConnectionStatus:
        now = datetime.now(UTC)
        t0 = time.perf_counter()
        try:
            doc, _ = await self.http.get_json(VALIDATE)
            if not (isinstance(doc, dict) and doc.get("valid") is True):
                raise ConnectorError("auth_error", "Datadog did not confirm the API key (valid != true)")
        except ConnectorError as exc:
            msg = exc.message
            if exc.kind == "auth_error":
                msg = f"the API key was rejected for site {self.site}: {exc.message.split('. Check')[0]}"
            status = {"auth_error": "auth_error", "rate_limited": "rate_limited", "unavailable": "unavailable"}.get(
                exc.kind, "unavailable" if exc.kind == "timeout" else "error"
            )
            return ConnectionStatus(connector=self.id, status=status, message=msg, checked_at=now)  # type: ignore[arg-type]
        signals: dict[str, SignalStatus] = {}
        for sig in self.signals:
            signals[sig] = await self._probe(sig, now)
        latency = round((time.perf_counter() - t0) * 1000, 1)
        ok = [s for s, st in signals.items() if st.status == "ok"]
        if signals and len(ok) == len(signals):
            status, msg = "ok", f"Datadog ({self.site}) accepted the keys; {', '.join(ok)} can be read"
        elif ok:
            missing = ", ".join(f"{s}: {signals[s].status.replace('_', ' ')}" for s in signals if s not in ok)
            status, msg = "partial", f"Datadog ({self.site}): {', '.join(ok)} readable; {missing}"
        elif signals and all(st.status == "permission_denied" for st in signals.values()):
            status = "auth_error"
            msg = (
                f"the API key is valid but no product could be read: the application key is invalid or lacks "
                f"{', '.join(PERMISSION[s] for s in signals)}"
            )
        elif any(st.status == "rate_limited" for st in signals.values()):
            status, msg = "rate_limited", "Datadog rate-limited the connection test; try again shortly"
        else:
            status, msg = "error", "; ".join(f"{s}: {st.message}" for s, st in signals.items()) or "no templates"
        return ConnectionStatus(
            connector=self.id,
            status=status,  # type: ignore[arg-type]
            message=msg,
            latency_ms=latency,
            checked_at=now,
            signals=signals,
        )

    async def _probe(self, sig: Signal, now: datetime) -> SignalStatus:
        """The cheapest read of each product: one record (or one aggregate) over the last few minutes."""
        frm, to = now - timedelta(minutes=15), now
        scope = f"env:{self.env}" if self.env else "*"
        try:
            if sig == "log":
                body: dict[str, Any] = {
                    "filter": {"from": _iso_ms(frm), "to": _iso_ms(to), "query": scope, "indexes": self.log_indexes},
                    "page": {"limit": 1},
                }
                await self._post(LOGS_SEARCH, body, sig)
            elif sig == "span":
                attrs = {"filter": {"from": _iso_ms(frm), "to": _iso_ms(to), "query": scope}, "page": {"limit": 1}}
                await self._post(SPANS_SEARCH, {"data": {"type": "search_request", "attributes": attrs}}, sig)
            else:
                metric_scope = f"env:{self.env}" if self.env else "*"
                body = {
                    "data": {
                        "type": "timeseries_request",
                        "attributes": {
                            "from": _epoch_ms(now - timedelta(minutes=5)),
                            "to": _epoch_ms(now),
                            "interval": 60_000,
                            "queries": [
                                {
                                    "data_source": "metrics",
                                    "query": f"avg:datadog.agent.running{{{metric_scope}}}",
                                    "name": "a",
                                }
                            ],
                            "formulas": [{"formula": "a"}],
                        },
                    }
                }
                await self._post(TIMESERIES, body, sig)
        except ConnectorError as exc:
            kind = exc.kind
            status = kind if kind in ("permission_denied", "unsupported", "rate_limited", "unavailable") else "error"
            if kind == "timeout":
                status = "unavailable"
            return SignalStatus(status=status, message=exc.message)  # type: ignore[arg-type]
        return SignalStatus(status="ok", message=f"{PRODUCT[sig]} readable ({PERMISSION[sig]})")

    async def services(self, window: FetchWindow) -> list[str]:
        return (await self.discover(window))[0]

    async def discover(self, window: FetchWindow) -> tuple[list[str], list[str]]:
        """Services with indexed logs in the window: one aggregate over the ``service`` facet, top 50 by count.
        Nothing is enumerated organisation-wide; names that are not valid OpsPilot service slugs are reported."""
        self.check_window(window)
        body = {
            "compute": [{"aggregation": "count", "type": "total"}],
            "filter": {
                "from": _iso_ms(window.start),
                "to": _iso_ms(window.end),
                "query": f"env:{self.env}" if self.env else "*",
                "indexes": self.log_indexes,
            },
            "group_by": [
                {
                    "facet": "service",
                    "limit": MAX_DISCOVERED,
                    "missing": "(no service)",
                    "sort": {"type": "measure", "aggregation": "count", "order": "desc"},
                }
            ],
        }
        doc = await self._post(LOGS_AGGREGATE, body, "log")
        data = doc.get("data")
        buckets = data.get("buckets") if isinstance(data, dict) else None
        if not isinstance(buckets, list):
            raise ConnectorError("invalid_response", "Datadog aggregate did not return data.buckets")
        found: list[str] = []
        unusable: list[str] = []
        notes: list[str] = []
        for b in buckets:
            raw = (b.get("by") or {}).get("service") if isinstance(b, dict) else None
            count = _count(b)
            if raw == "(no service)":
                notes.append(f"{count or 'some'} log(s) in the window have no service tag; they cannot be queried")
            elif isinstance(raw, str) and _SERVICE.match(raw):
                found.append(raw)
            elif isinstance(raw, str):
                unusable.append(raw[:60])
        if unusable:
            notes.append(
                f"not usable as OpsPilot service names (lower-case slugs only): {', '.join(sorted(unusable)[:10])}"
            )
        if len(buckets) >= MAX_DISCOVERED:
            notes.append(f"only the {MAX_DISCOVERED} services with the most logs are listed")
        meta = _meta(doc)
        if meta.get("status") == "timeout":
            notes.append("Datadog reported a timeout: the list may be incomplete")
        return sorted(set(found)), notes

    async def fetch(self, template: QueryTemplate, service: str, window: FetchWindow) -> FetchResult:
        self.check_window(window)
        signal = template.returns
        query = self.render(template, service)
        endpoint = {"log": LOGS_SEARCH, "metric": TIMESERIES, "span": SPANS_SEARCH}[signal]
        step = step_for(window) if signal == "metric" else None
        limit = None if signal == "metric" else (self.limits.max_log_lines if signal == "log" else self.max_spans)
        prov = self.provenance(template, service, window, endpoint=endpoint, query=query, step=step, limit=limit)
        prov.site = self.site
        prov.link = self.link(signal, query)
        t0 = time.perf_counter()
        result = FetchResult(provenance=prov)
        try:
            if signal == "log":
                result.logs = await self._logs(query, window, prov)
            elif signal == "metric":
                result.metrics = await self._metrics(template, query, window, prov)
            else:
                result.spans = await self._spans(template, query, window, prov)
        except ConnectorError as exc:
            prov.status, prov.error = "error", exc.as_dict()
            prov.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            return FetchResult(provenance=prov)
        prov.duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        prov.returned = len(result.logs) + len(result.metrics) + len(result.spans)
        prov.status = "ok" if prov.returned else "empty"
        return result

    # -- logs ---------------------------------------------------------------------------------------------------
    async def _logs(self, query: str, window: FetchWindow, prov: QueryProvenance) -> list[LogRecord]:
        search = {
            "filter": {
                "from": _iso_ms(window.start),
                "to": _iso_ms(window.end),
                "query": query,
                "indexes": self.log_indexes,
            },
            "sort": "-timestamp",
        }
        items = await self._search(LOGS_SEARCH, search, self.limits.max_log_lines, "log", prov, wrap=False)
        rows: list[tuple[datetime, str, dict[str, Any], str]] = []
        for item in items:
            a = item.get("attributes")
            ts_raw = a.get("timestamp") if isinstance(a, dict) else None
            ts = _parse_ts(ts_raw)
            if not isinstance(a, dict) or ts is None:
                prov.rejected += 1
                continue
            rows.append((ts, str(ts_raw), a, str(item.get("id") or "")[:200]))
        rows.sort(key=lambda r: (r[0], r[3]))
        out: list[LogRecord] = []
        for n, (ts, ts_raw, a, log_id) in enumerate(rows, start=1):
            message = a.get("message")
            f = log_line_fields(message if isinstance(message, str) and message else "(empty message)")
            prov.redactions += f["redactions"]
            nested = _flat(a.get("attributes"))
            svc = normalize_service(a.get("service"))
            status = str(a.get("status") or "").strip().lower()
            level = _LOG_LEVELS.get(status) or map_level(status) or f["level"]
            attrs: dict[str, Any] = {"datadog.log_id": log_id} if log_id else {}
            if a.get("host"):
                attrs["host"] = _scalar(a["host"])
            for k, v in _tags(a.get("tags")).items():
                if k not in ("service", "env") and len(attrs) < 16:
                    attrs[f"tag.{k}"] = v
            if self.env or _tags(a.get("tags")).get("env"):
                attrs["env"] = _tags(a.get("tags")).get("env") or self.env
            skip = {"dd.trace_id", "dd.span_id", "message", "status", "service", "timestamp"}
            for k, v in nested.items():
                if k in skip or isinstance(v, list | dict) or v is None or len(attrs) >= 24:
                    continue
                attrs[f"attr.{k}"[:60]] = _scalar(v)
            for k, v in f["attributes"].items():
                if len(attrs) < 28:
                    attrs.setdefault(k, v)
            trace = nested.get("dd.trace_id") or f["trace_id"]
            span = nested.get("dd.span_id") or f["span_id"]
            out.append(
                LogRecord(
                    ts=ts,
                    ts_original=ts_raw,
                    tz=_tz_of(ts_raw),
                    service=svc or prov.service,
                    service_source="record" if svc else "query",
                    source=f"{prov.id}:entry {n}",
                    level=level or infer_level(f["message"]),  # type: ignore[arg-type]
                    level_inferred=level is None,
                    message=f["message"],
                    trace_id=str(trace)[:64] if trace else None,
                    span_id=str(span)[:64] if span else None,
                    attributes=attrs,
                )
            )
        return out

    # -- metrics ------------------------------------------------------------------------------------------------
    async def _metrics(
        self, t: QueryTemplate, query: str, window: FetchWindow, prov: QueryProvenance
    ) -> list[MetricRecord]:
        try:
            parts, formula = datadog_metric_parts(query)
        except ValueError as exc:  # a template file that passed check_template can no longer fail here
            raise ConnectorError("invalid_request", f"template {t.id}: {exc}") from exc
        body = {
            "data": {
                "type": "timeseries_request",
                "attributes": {
                    "from": _epoch_ms(window.start),
                    "to": _epoch_ms(window.end),
                    "interval": (prov.step_seconds or 60) * 1000,
                    "queries": [{"data_source": "metrics", "query": q, "name": n} for n, q in parts],
                    "formulas": [{"formula": formula}],
                },
            }
        }
        doc = await self._post(TIMESERIES, body, "metric")
        prov.pages = 1
        errors = doc.get("errors")
        if isinstance(errors, str) and errors.strip():
            prov.issues.append(self.http.clean(f"Datadog: {errors}", 200))
        data = doc.get("data")
        attrs = data.get("attributes") if isinstance(data, dict) else None
        if not isinstance(attrs, dict):
            raise ConnectorError("invalid_response", "Datadog timeseries did not return data.attributes")
        series = attrs.get("series") or []
        times = attrs.get("times") or []
        values = attrs.get("values") or []
        if not (isinstance(series, list) and isinstance(times, list) and isinstance(values, list)):
            raise ConnectorError("invalid_response", "Datadog timeseries series/times/values are not lists")
        if len(values) != len(series):
            raise ConnectorError(
                "invalid_response", f"Datadog returned {len(series)} series but {len(values)} value lists"
            )
        prov.series = len(series)
        if len(series) > self.limits.max_series:
            prov.truncated = True
            prov.issues.append(
                f"{len(series)} series returned; only the first {self.limits.max_series} are kept (aggregate the "
                "template, e.g. without 'by {...}')"
            )
        stamps = [datetime.fromtimestamp(int(t_) / 1000, UTC) if isinstance(t_, int | float) else None for t_ in times]
        valid_stamps = sorted(s for s in stamps if s is not None)
        if len(valid_stamps) >= 2:  # Datadog may widen the interval it was asked for; report what it used
            prov.step_seconds = int((valid_stamps[1] - valid_stamps[0]).total_seconds()) or prov.step_seconds
        missing = 0
        points: list[tuple[datetime, float, str, dict[str, str], str]] = []
        for s, vals in list(zip(series, values, strict=True))[: self.limits.max_series]:
            if not isinstance(s, dict) or not isinstance(vals, list) or len(vals) != len(times):
                prov.rejected += 1
                continue
            labels = _tags(s.get("group_tags"), limit=10)
            unit = _unit(s.get("unit"))
            for ts, raw_ts, v in zip(stamps, times, vals, strict=True):
                if v is None:  # Datadog had no value for this interval: never filled in
                    missing += 1
                    continue
                if (
                    ts is None
                    or not isinstance(v, int | float)
                    or isinstance(v, bool)
                    or v != v
                    or abs(v) == float("inf")
                ):
                    prov.rejected += 1
                    continue
                points.append((ts, float(v), str(raw_ts), labels, unit))
        if missing:
            prov.issues.append(f"{missing} interval(s) had no value (null); they are left out, never filled in")
        if prov.rejected:
            prov.issues.append(f"{prov.rejected} malformed point(s) or series were skipped")
        reported_units = {p[4] for p in points if p[4]}
        if t.unit and reported_units and t.unit not in reported_units and formula == "a":
            prov.issues.append(f"Datadog reports the unit as {', '.join(sorted(reported_units))}")
        points.sort(key=lambda p: p[0])
        out: list[MetricRecord] = []
        for n, (ts, value, raw_ts, labels, unit) in enumerate(points, start=1):
            label_svc = normalize_service(labels.get("service"))
            out.append(
                MetricRecord(
                    ts=ts,
                    ts_original=raw_ts,
                    tz="epoch",
                    service=label_svc or prov.service,
                    service_source="record" if label_svc else "query",
                    source=f"{prov.id}:point {n}",
                    metric=t.metric or t.id,
                    metric_original=t.id,
                    value=value,
                    unit=t.unit or unit,
                    labels=labels,
                )
            )
        return out

    # -- spans --------------------------------------------------------------------------------------------------
    async def _spans(
        self, t: QueryTemplate, query: str, window: FetchWindow, prov: QueryProvenance
    ) -> list[SpanRecord]:
        flt = {"from": _iso_ms(window.start), "to": _iso_ms(window.end), "query": query}
        items = await self._search(
            SPANS_SEARCH, {"filter": flt, "sort": "-timestamp"}, self.max_spans, "span", prov, wrap=True
        )
        error_filter = "status:error" in query
        matched = {"error": error_filter}
        raw = [(it, matched) for it in items]
        if t.expand_traces and items:
            traces: list[str] = []
            for it in items:
                tid = str((it.get("attributes") or {}).get("trace_id") or "") if isinstance(it, dict) else ""
                if _TRACE_ID.match(tid) and tid not in traces:
                    traces.append(tid)
                if len(traces) >= t.expand_traces:
                    break
            room = self.max_spans - len(items)
            if traces and room > 0:
                expand_q = "trace_id:(" + " OR ".join(traces) + ")"
                pages_before = prov.pages or 0
                more = await self._search(
                    SPANS_SEARCH,
                    {"filter": {**flt, "query": expand_q}, "sort": "timestamp"},
                    room,
                    "span",
                    prov,
                    wrap=True,
                )
                prov.pages = pages_before + (prov.pages or 0)
                raw += [(it, {"error": False}) for it in more]
                prov.issues.append(
                    f"other indexed spans of {len(traces)} matched trace(s) were fetched ({len(more)} span(s), "
                    f"query {expand_q[:80]}{'…' if len(expand_q) > 80 else ''})"
                )
        seen: set[tuple[str, str]] = set()
        rows: list[tuple[datetime, str, dict[str, Any], bool, str]] = []
        for it, how in raw:
            a = it.get("attributes") if isinstance(it, dict) else None
            if not isinstance(a, dict):
                prov.rejected += 1
                continue
            trace, span = str(a.get("trace_id") or ""), str(a.get("span_id") or "")
            start_raw = a.get("start_timestamp")
            ts = _parse_ts(start_raw)
            if not trace or not span or ts is None:
                prov.rejected += 1
                continue
            key = (trace, span)
            if key in seen:
                continue
            seen.add(key)
            rows.append((ts, str(start_raw), a, bool(how["error"]), str(it.get("id") or "")[:200]))
        rows.sort(key=lambda r: (r[0], str(r[2].get("span_id"))))
        ids = {str(r[2].get("span_id")) for r in rows}
        out: list[SpanRecord] = []
        partial = 0
        for n, (ts, start_raw, a, matched_error, event_id) in enumerate(rows, start=1):
            svc = normalize_service(a.get("service"))
            parent = str(a.get("parent_id") or "")
            parent_id = None if parent in ("", "0") else parent[:64]
            end = _parse_ts(a.get("end_timestamp"))
            nested = _flat(a.get("attributes"))
            custom = _flat(a.get("custom"))
            duration = (end - ts).total_seconds() * 1000 if end and end >= ts else None
            if duration is None and isinstance(nested.get("duration"), int | float):
                duration = float(nested["duration"]) / 1e6  # Datadog span duration is in nanoseconds
            is_error, message = _span_error(a, nested, custom)
            attrs: dict[str, Any] = {"datadog.span_event_id": event_id} if event_id else {}
            for k in ("resource_name", "env", "host", "type", "ingestion_reason", "retained_by", "single_span"):
                if a.get(k) not in (None, ""):
                    attrs[k] = _scalar(a[k])
            peer = nested.get("peer.service") or custom.get("peer.service")
            if peer:
                attrs["peer.service"] = _scalar(peer)
            for k, v in {**custom, **nested}.items():
                if len(attrs) >= 24 or isinstance(v, list | dict) or v is None or k.startswith("error."):
                    continue
                if k in (
                    "http.status_code",
                    "http.method",
                    "http.route",
                    "db.system",
                    "db.type",
                    "operation_name",
                    "out.host",
                    "component",
                    "span.kind",
                ):
                    attrs[k] = _scalar(v)
            if parent_id and parent_id not in ids:
                attrs["parent_missing"] = True  # the parent span is not in the snapshot: this trace is partial
                partial += 1
            name = str(a.get("resource_name") or nested.get("operation_name") or a.get("type") or "span")[:200]
            out.append(
                SpanRecord(
                    ts=ts,
                    ts_original=start_raw,
                    tz=_tz_of(start_raw),
                    service=svc or prov.service,
                    service_source="record" if svc else "query",
                    source=f"{prov.id}:span {n}",
                    name=scrub(name)[0],
                    trace_id=str(a.get("trace_id"))[:64],
                    span_id=str(a.get("span_id"))[:64],
                    parent_span_id=parent_id,
                    duration_ms=round(duration, 3) if duration is not None else None,
                    status="error" if (matched_error or is_error) else "unset",
                    status_message=message,
                    kind=str(a.get("type"))[:40] if a.get("type") else None,
                    attributes=attrs,
                )
            )
        if partial:
            prov.issues.append(
                f"{partial} span(s) reference a parent span that is not in the snapshot: those traces are partial "
                "(indexed spans are sampled by retention filters); no missing span is reconstructed"
            )
        if out and not any(s.status == "error" for s in out) and not error_filter:
            prov.issues.append("span status is 'unset' unless Datadog marks the span as an error")
        return out


def _meta(doc: dict[str, Any]) -> dict[str, Any]:
    meta = doc.get("meta")
    return meta if isinstance(meta, dict) else {}


def _count(bucket: Any) -> int | None:
    computes = bucket.get("computes") if isinstance(bucket, dict) else None
    if isinstance(computes, dict):
        for v in computes.values():
            if isinstance(v, int | float) and not isinstance(v, bool):
                return int(v)
    return None


def _unit(raw: Any) -> str:
    """Datadog's primary unit (``unit[0]``) as its short name, e.g. ``s`` or ``req``; empty when not stated."""
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        u = raw[0]
        return str(u.get("short_name") or u.get("name") or "")[:20]
    return ""


def _span_error(a: dict[str, Any], nested: dict[str, Any], custom: dict[str, Any]) -> tuple[bool, str | None]:
    """Whether Datadog flags the span as an error, and its error message (credential-like values redacted)."""
    flags = [nested.get("error"), custom.get("error"), nested.get("status"), a.get("status")]
    is_error = any(f in (1, True, "1", "true", "error") for f in flags)
    is_error = is_error or "status:error" in [str(t) for t in a.get("tags") or []]
    message = None
    for src in (custom, nested):
        for k in ("error.message", "error.msg", "error.type"):
            if src.get(k):
                message = scrub(str(src[k]))[0][:300]
                is_error = True
                break
        if message:
            break
    return is_error, message
