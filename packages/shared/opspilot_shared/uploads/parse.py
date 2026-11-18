"""Parse uploaded files (.log/.txt, .json, .csv) into normalized records.

Supported shapes (kept deliberately small):

- **.log / .txt** — one entry per line starting with a timestamp (ISO-8601, epoch, or the common web-server
  ``[18/Nov/2026:10:02:03 +0000]`` form). A level token and ``key=value`` pairs are recognized. Lines without a
  timestamp continue the previous entry (stack traces). Lines that are JSON objects are read as structured records.
- **.json** — an array of objects, an object holding such an array (``records``, ``events``, ``logs``, ``spans`` …),
  JSON Lines, or an OTLP/JSON trace export (``resourceSpans``). Each object becomes a span (trace and span IDs), an
  event (a recognized deployment / rollback / migration / config-change / alert type), a metric sample (metric name
  and numeric value) or a log entry (a message).
- **.csv** — a header row with a timestamp column, then either ``metric,value[,unit]`` columns (long format),
  one numeric column per metric (wide format), or an event-type column (event export).

Nothing is invented. A record without a usable timestamp is rejected (a timestamp without a timezone is read in the
timezone the user chose, and recorded as assumed). A record without a service uses the service the user declared for
the file, or is rejected. Text that looks like a credential is redacted before it is stored.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from pathlib import PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from opspilot_shared.redaction import REDACTED, is_sensitive
from opspilot_shared.uploads.model import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_ISSUES_PER_FILE,
    MAX_MESSAGE_CHARS,
    MAX_RECORDS,
    MAX_TOTAL_BYTES,
    Dataset,
    EventRecord,
    EventType,
    FileReport,
    LogRecord,
    MetricRecord,
    SpanRecord,
)


class UploadError(ValueError):
    """The upload as a whole cannot be accepted (shown to the user as is)."""


@dataclass(frozen=True, slots=True)
class UploadFile:
    name: str
    content: str
    service: str | None = None  # declared by the user for records that do not name one


# --------------------------------------------------------------------------------------------- small helpers
_EPOCH_MIN, _EPOCH_MAX = 946_684_800.0, 4_102_444_800.0  # 2000-01-01 .. 2100-01-01
_HAS_TIME = re.compile(r"\d{1,2}:\d{2}")
_CLF_TS = re.compile(r"^\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4}$")
_SPACE_BEFORE_OFFSET = re.compile(r"\s+(Z|[+-]\d{2}:?\d{2})$")
_SERVICE_RE = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_METRIC_RE = re.compile(r"^[a-z0-9_]{2,63}$")


def resolve_timezone(name: str | None) -> tuple[tzinfo, str]:
    name = (name or "UTC").strip() or "UTC"
    if name.upper() in ("UTC", "Z", "GMT"):
        return UTC, "UTC"
    try:
        return ZoneInfo(name), name
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UploadError(f"unknown timezone {name!r}; use an IANA name such as UTC or Europe/Berlin") from exc


def _epoch(value: float) -> tuple[datetime, str] | None:
    for divisor in (1.0, 1e3, 1e6, 1e9):  # s, ms, µs, ns
        seconds = value / divisor
        if _EPOCH_MIN <= seconds <= _EPOCH_MAX:
            return datetime.fromtimestamp(seconds, UTC), "epoch"
    return None


def parse_timestamp(value: Any, tz: tzinfo, tz_name: str) -> tuple[datetime, str] | None:
    """(UTC datetime, how the timezone was established) or None. Date-only values are rejected (no invented time)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return _epoch(float(value)) if math.isfinite(value) else None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{9,19}(\.\d+)?", text):
        return _epoch(float(text))
    if _CLF_TS.match(text):
        dt = datetime.strptime(text, "%d/%b/%Y:%H:%M:%S %z")
    else:
        if not _HAS_TIME.search(text):
            return None
        iso = _SPACE_BEFORE_OFFSET.sub(r"\1", text)
        iso = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d)", r"\1.\2", iso)
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt, label = dt.replace(tzinfo=tz), f"assumed {tz_name}"
    else:
        off = dt.utcoffset()
        if text.endswith(("Z", "z")) or not off:
            label = "Z" if text.endswith(("Z", "z")) else "+00:00"
        else:
            total = int(off.total_seconds() // 60)
            label = f"{'+' if total >= 0 else '-'}{abs(total) // 60:02d}:{abs(total) % 60:02d}"
    utc = dt.astimezone(UTC)
    if not (_EPOCH_MIN <= utc.timestamp() <= _EPOCH_MAX):
        return None
    return utc, label


def normalize_service(raw: Any) -> str | None:
    if raw is None or isinstance(raw, dict | list):
        return None
    s = re.sub(r"[^a-z0-9-]+", "-", str(raw).strip().lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s).lstrip("0123456789-")[:63]
    return s if _SERVICE_RE.match(s) else None


_UNIT_SUFFIXES = (
    ("_ms", "ms"),
    ("_millis", "ms"),
    ("_seconds", "s"),
    ("_secs", "s"),
    ("_ratio", "ratio"),
    ("_pct", "percent"),
    ("_percent", "percent"),
    ("_per_min", "per_min"),
    ("_per_sec", "per_sec"),
    ("_bytes", "bytes"),
)
_UNIT_ALIASES = {"%": "percent", "pct": "percent", "milliseconds": "ms", "millis": "ms", "seconds": "s", "sec": "s"}


def metric_name(raw: str) -> tuple[str | None, str]:
    """Slug for a metric column/name and the unit it states (``latency (ms)``, ``p95_latency_ms``), else ''."""
    text = raw.strip()
    unit = ""
    m = re.match(r"^(.*?)\s*[(\[]\s*([^)\]]{1,20})\s*[)\]]\s*$", text)
    if m:
        text, unit = m.group(1), m.group(2).strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:63]
    if not unit:
        unit = next((u for suffix, u in _UNIT_SUFFIXES if slug.endswith(suffix)), "")
    unit = _UNIT_ALIASES.get(unit, unit)
    return (slug if _METRIC_RE.match(slug) else None), unit


_LEVELS = {
    "TRACE": "DEBUG",
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "INFORMATION": "INFO",
    "NOTICE": "INFO",
    "WARN": "WARN",
    "WARNING": "WARN",
    "ERROR": "ERROR",
    "ERR": "ERROR",
    "FATAL": "ERROR",
    "CRITICAL": "ERROR",
    "CRIT": "ERROR",
    "SEVERE": "ERROR",
    "PANIC": "ERROR",
    "EMERG": "ERROR",
    "ALERT": "ERROR",
}
_LEVEL_TOKEN = re.compile(r"^[\[(<]?(" + "|".join(sorted(_LEVELS, key=len, reverse=True)) + r")[\])>]?(?=[\s:|\-]|$)")
_ERRORISH = re.compile(r"(?i)\b(error|exception|traceback|fatal|panic|failed|failure|refused|unavailable)\b")
_WARNISH = re.compile(r"(?i)\b(warn|warning|deprecated|retry|retrying|slow)\b")


def map_level(raw: Any) -> str | None:
    if isinstance(raw, int | float) and not isinstance(raw, bool):  # OTel severityNumber
        n = int(raw)
        return "DEBUG" if n <= 8 else "INFO" if n <= 12 else "WARN" if n <= 16 else "ERROR" if n <= 24 else None
    return _LEVELS.get(str(raw).strip().upper()) if raw is not None else None


def infer_level(message: str) -> str:
    return "ERROR" if _ERRORISH.search(message) else "WARN" if _WARNISH.search(message) else "INFO"


_SECRET_KV = re.compile(
    r"(?i)(?<![\w.-])([\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|authorization|cookie|"
    r"credential|private[_-]?key)[\w.-]*)(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|(?:bearer|basic)\s+\S+|[^\s,;&\"']+)"
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/\-]{8,}=*")
_AWS_KEY = re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S)


def scrub(text: str) -> tuple[str, int]:
    """Redact values that look like credentials. Returns the text and how many values were replaced."""
    count = 0

    def kv(m: re.Match[str]) -> str:
        nonlocal count
        if m.group(3).strip("\"'") in ("", REDACTED):
            return m.group(0)
        count += 1
        return f"{m.group(1)}{m.group(2)}{REDACTED}"

    def whole(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return REDACTED

    def scheme(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{m.group(1)} {REDACTED}"

    text = _PEM.sub(whole, text)
    text = _SECRET_KV.sub(kv, text)
    text = _BEARER.sub(scheme, text)
    text = _AWS_KEY.sub(whole, text)
    return text, count


def sanitize_name(name: str, index: int) -> tuple[str, str]:
    """A safe display/storage name (no directories, no unusual characters) and its extension."""
    base = PurePosixPath(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")[:100]
    ext = PurePosixPath(base).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(ALLOWED_EXTENSIONS)
        raise UploadError(f"{name!r}: unsupported file type {ext or '(none)'}; allowed: {allowed}")
    stem = PurePosixPath(base).stem.strip("._-")
    return (f"{stem}{ext}" if stem else f"file-{index + 1}{ext}"), ext


# --------------------------------------------------------------------------------------------- parsing context
_TS_KEYS = (
    "timestamp",
    "@timestamp",
    "time",
    "ts",
    "datetime",
    "date_time",
    "eventtime",
    "event_time",
    "time_utc",
    "timeunixnano",
    "observedtimeunixnano",
    "start_time",
    "starttime",
    "starttimeunixnano",
    "start",
    "date",
)
_SERVICE_KEYS = (
    "service",
    "service.name",
    "service_name",
    "servicename",
    "resource.service.name",
    "app",
    "application",
    "component",
    "svc",
)
_LEVEL_KEYS = ("level", "severity", "severity_text", "severitytext", "log.level", "loglevel", "lvl", "severitynumber")
_MESSAGE_KEYS = ("message", "msg", "log", "body", "text", "event.original")
_TRACE_KEYS = ("trace_id", "traceid", "trace.id", "trace")
_SPAN_KEYS = ("span_id", "spanid", "span.id")
_PARENT_KEYS = ("parent_span_id", "parentspanid", "parent_id", "parentid", "parent.id")
_EVENT_KEYS = ("event_type", "eventtype", "type", "event", "kind", "category")
_SUMMARY_KEYS = ("summary", "description", "message", "msg", "title", "details", "change")
_METRIC_KEYS = ("metric", "metric_name", "metricname", "name")
_UPSTREAM_KEYS = ("upstream", "peer.service", "dependency", "downstream", "target_service", "callee")
_EVENT_TYPES: dict[str, EventType] = {
    "deployment": EventType.DEPLOYMENT,
    "deploy": EventType.DEPLOYMENT,
    "deployed": EventType.DEPLOYMENT,
    "release": EventType.DEPLOYMENT,
    "rollout": EventType.DEPLOYMENT,
    "rollback": EventType.ROLLBACK,
    "schema_migration": EventType.SCHEMA_MIGRATION,
    "migration": EventType.SCHEMA_MIGRATION,
    "db_migration": EventType.SCHEMA_MIGRATION,
    "config_change": EventType.CONFIG_CHANGE,
    "config": EventType.CONFIG_CHANGE,
    "configuration": EventType.CONFIG_CHANGE,
    "config_update": EventType.CONFIG_CHANGE,
    "feature_flag": EventType.CONFIG_CHANGE,
    "flag_change": EventType.CONFIG_CHANGE,
    "alert": EventType.ALERT,
    "alarm": EventType.ALERT,
    "page": EventType.ALERT,
}
_SPAN_KINDS = {1: "INTERNAL", 2: "SERVER", 3: "CLIENT", 4: "PRODUCER", 5: "CONSUMER"}


def event_type(raw: Any) -> EventType | None:
    if not isinstance(raw, str):
        return None
    return _EVENT_TYPES.get(re.sub(r"[^a-z]+", "_", raw.strip().lower()).strip("_"))


def _flatten(obj: dict[str, Any], prefix: str = "", out: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {} if out is None else out
    for k, v in obj.items():
        key = f"{prefix}{k}".lower()
        if isinstance(v, dict) and len(out) < 200:
            _flatten(v, f"{key}.", out)
        else:
            out.setdefault(key, v)
    return out


def _pick(flat: dict[str, Any], keys: Iterable[str], used: set[str]) -> Any:
    for k in keys:
        v = flat.get(k)
        if v not in (None, ""):
            used.add(k)
            return v
    return None


def _scalar_attrs(flat: dict[str, Any], used: set[str], limit: int = 20) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in flat.items():
        if k in used or isinstance(v, dict | list) or v is None:
            continue
        out[k] = v if isinstance(v, bool | int | float) else str(v)[:300]
        if len(out) >= limit:
            break
    return out


@dataclass
class _Ctx:
    report: FileReport
    tz: tzinfo
    tz_name: str
    default_service: str | None
    dataset: Dataset
    budget: list[int]
    services: set[str] = field(default_factory=set)
    tzs: set[str] = field(default_factory=set)
    suppressed: int = 0

    @property
    def full(self) -> bool:
        return self.budget[0] <= 0

    def issue(self, message: str) -> None:
        if len(self.report.issues) < MAX_ISSUES_PER_FILE:
            self.report.issues.append(message)
        else:
            self.suppressed += 1

    def reject(self, where: str, why: str) -> None:
        self.report.rejected += 1
        self.issue(f"{where}: {why}")

    def ts(self, value: Any) -> tuple[datetime, str] | None:
        return parse_timestamp(value, self.tz, self.tz_name)

    def service(self, raw: Any) -> tuple[str, str] | None:
        svc = normalize_service(raw)
        if svc:
            return svc, "record"
        if self.default_service:
            return self.default_service, "file_default"
        return None

    def clean(self, text: str) -> str:
        cleaned, n = scrub(text)
        self.report.redactions += n
        return cleaned[:MAX_MESSAGE_CHARS]

    def clean_attrs(self, attrs: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in attrs.items():
            if is_sensitive(k) and v not in (None, ""):
                self.report.redactions += v != REDACTED
                out[k] = REDACTED
            elif isinstance(v, str):
                out[k] = self.clean(v)[:300]
            else:
                out[k] = v
        return out

    def add(self, record: LogRecord | MetricRecord | SpanRecord | EventRecord) -> None:
        if self.full:
            return
        self.budget[0] -= 1
        kind = {LogRecord: "log", MetricRecord: "metric", SpanRecord: "span", EventRecord: "event"}[type(record)]
        getattr(self.dataset, {"log": "logs", "metric": "metrics", "span": "spans", "event": "events"}[kind]).append(
            record
        )
        self.report.records[kind] = self.report.records.get(kind, 0) + 1
        self.services.add(record.service)
        self.tzs.add(record.tz)
        r = self.report
        r.start = record.ts if r.start is None or record.ts < r.start else r.start
        r.end = record.ts if r.end is None or record.ts > r.end else r.end

    def finish(self) -> None:
        if self.suppressed:
            self.report.issues.append(f"… and {self.suppressed} more issue(s) of the same kinds")
        self.report.services = sorted(self.services)
        self.report.timezones = sorted(self.tzs)


# --------------------------------------------------------------------------------------------- structured records
def _structured(obj: dict[str, Any], ctx: _Ctx, where: str, *, inherited_service: str | None = None) -> None:
    flat = _flatten(obj)
    used: set[str] = set()
    trace = _pick(flat, _TRACE_KEYS, used)
    span = _pick(flat, _SPAN_KEYS, used)
    etype_raw = next((flat[k] for k in _EVENT_KEYS if isinstance(flat.get(k), str) and event_type(flat[k])), None)
    metric_raw = _pick(flat, _METRIC_KEYS, set())
    value = flat.get("value")
    message = _pick(flat, _MESSAGE_KEYS, set())

    raw_ts = _pick(flat, _TS_KEYS, used)
    stamp = ctx.ts(raw_ts)
    if stamp is None:
        ctx.reject(where, "no usable timestamp" if raw_ts is None else f"unreadable timestamp {str(raw_ts)[:40]!r}")
        return
    svc = ctx.service(_pick(flat, _SERVICE_KEYS, used) or inherited_service)
    if svc is None:
        ctx.reject(where, "no service (add a service field or declare the file's service)")
        return
    base = {
        "ts": stamp[0],
        "ts_original": str(raw_ts)[:64],
        "tz": stamp[1],
        "service": svc[0],
        "service_source": svc[1],
        "source": f"{ctx.report.name}:{where}",
    }
    try:
        if trace and span:
            _span_record(flat, used, base, str(trace), str(span), ctx)
        elif etype_raw is not None:
            for k in _EVENT_KEYS:
                if flat.get(k) == etype_raw:
                    used.add(k)
                    break
            summary = _pick(flat, _SUMMARY_KEYS, used) or str(etype_raw)
            ctx.add(
                EventRecord(
                    **base,
                    event_type=event_type(etype_raw) or EventType.ALERT,
                    type_original=str(etype_raw)[:64],
                    summary=ctx.clean(str(summary)),
                    attributes=ctx.clean_attrs(_scalar_attrs(flat, used)),
                )
            )
        elif metric_raw is not None and isinstance(value, int | float) and not isinstance(value, bool) and not message:
            name, unit = metric_name(str(metric_raw))
            if name is None or not math.isfinite(float(value)):
                ctx.reject(where, f"invalid metric name or value ({str(metric_raw)[:40]!r})")
                return
            stated = flat.get("unit") or flat.get("units")
            ctx.add(
                MetricRecord(
                    **base,
                    metric=name,
                    metric_original=str(metric_raw)[:120],
                    value=float(value),
                    unit=_UNIT_ALIASES.get(str(stated).lower(), str(stated).lower()) if stated else unit,
                )
            )
        elif message is not None:
            _log_from_flat(flat, used, base, str(message), ctx, trace)
        else:
            ctx.reject(where, "not a log (message), metric (name + numeric value), span (trace/span id) or event")
    except ValidationError as exc:
        ctx.reject(where, f"invalid record ({exc.errors()[0]['msg']})")


def _span_record(flat: dict[str, Any], used: set[str], base: dict[str, Any], trace: str, span: str, ctx: _Ctx) -> None:
    name = _pick(flat, ("name", "operation", "operationname", "span_name", "spanname"), used) or "span"
    parent = _pick(flat, _PARENT_KEYS, used)
    duration: float | None = None
    for key, factor in (("duration_ms", 1.0), ("durationms", 1.0), ("duration_us", 1e-3), ("duration_ns", 1e-6)):
        v = flat.get(key)
        if isinstance(v, int | float) and not isinstance(v, bool):
            duration = float(v) * factor
            used.add(key)
            break
    if duration is None:
        end_raw = _pick(flat, ("end_time", "endtime", "end", "endtimeunixnano"), used)
        end = ctx.ts(end_raw) if end_raw is not None else None
        if end:
            duration = round((end[0] - base["ts"]).total_seconds() * 1000, 3)
    status_raw = _pick(flat, ("status_code", "status.code", "otel.status_code", "status"), used)
    error_flag = flat.get("error")
    status = "unset"
    if str(status_raw).upper() in ("ERROR", "STATUS_CODE_ERROR", "2") or error_flag is True:
        status = "error"
    elif str(status_raw).upper() in ("OK", "STATUS_CODE_OK", "1"):
        status = "ok"
    kind = _pick(flat, ("kind", "span_kind", "spankind"), used)
    if isinstance(kind, int):
        kind = _SPAN_KINDS.get(kind)
    status_msg = _pick(flat, ("status.message", "status_message", "statusmessage", "error.message"), used)
    ctx.add(
        SpanRecord(
            **base,
            name=ctx.clean(str(name))[:200],
            trace_id=str(trace)[:64],
            span_id=str(span)[:64],
            parent_span_id=str(parent)[:64] if parent else None,
            duration_ms=duration,
            status=status,  # type: ignore[arg-type]
            status_message=ctx.clean(str(status_msg))[:500] if status_msg else None,
            kind=str(kind).replace("SPAN_KIND_", "")[:20] if kind else None,
            attributes=ctx.clean_attrs(_scalar_attrs(flat, used)),
        )
    )


def _log_from_flat(
    flat: dict[str, Any], used: set[str], base: dict[str, Any], message: str, ctx: _Ctx, trace: Any
) -> None:
    for k in _MESSAGE_KEYS:
        if flat.get(k) is not None:
            used.add(k)
            break
    raw_level = _pick(flat, _LEVEL_KEYS, used)
    level = map_level(raw_level)
    inferred = level is None
    attrs = ctx.clean_attrs(_scalar_attrs(flat, used))
    upstream = next((normalize_service(flat[k]) for k in _UPSTREAM_KEYS if flat.get(k)), None)
    if upstream:
        attrs["upstream"] = upstream
    text = ctx.clean(message)
    logger = flat.get("logger") or flat.get("logger_name")
    ctx.add(
        LogRecord(
            **base,
            level=level or infer_level(text),  # type: ignore[arg-type]
            level_inferred=inferred,
            message=text,
            logger=str(logger)[:120] if logger else None,
            trace_id=str(trace)[:64] if trace else None,
            span_id=str(flat.get("span_id") or flat.get("spanid") or "")[:64] or None,
            attributes=attrs,
        )
    )


# --------------------------------------------------------------------------------------------- text logs
_LINE_TS = (
    re.compile(
        r"^\s*\[?(?P<ts>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?(?:\s?(?:Z|[+-]\d{2}:?\d{2}))?)\]?"
        r"(?:\s+|$|(?=[|:\-]))"
    ),
    re.compile(r"^\s*\[?(?P<ts>\d{10}(?:\.\d{1,9})?|\d{13})\]?\s+"),
)
_CLF_LINE = re.compile(
    r"^(?P<host>\S+) \S+ \S+ \[(?P<ts>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\] "
    r'"(?P<req>[^"]*)" (?P<status>\d{3}) (?P<size>\S+)(?P<rest>.*)$'
)
_KV = re.compile(r'(?<![\w.])([A-Za-z_][\w.\-]{0,40})=("(?:[^"\\]|\\.)*"|[^\s,;]+)')
_KV_SERVICE = ("service", "svc", "app", "service.name", "service_name")
_KV_TRACE = ("trace_id", "traceid", "trace", "trace.id")
_KV_SPAN = ("span_id", "spanid", "span.id")


def _text_line(line: str, ctx: _Ctx, lineno: int) -> LogRecord | bool | None:
    """A record, None (rejected), or True when the line has no timestamp (a continuation)."""
    clf = _CLF_LINE.match(line)
    if clf:
        stamp = ctx.ts(clf.group("ts"))
        status = int(clf.group("status"))
        level: str | None = "ERROR" if status >= 500 else "WARN" if status >= 400 else "INFO"
        raw_ts = clf.group("ts")
        rest = f"{clf.group('req')} -> {status}{clf.group('rest')}"
        attrs: dict[str, Any] = {"status": str(status), "client": clf.group("host")}
        inferred = True
    else:
        m = next((p.match(line) for p in _LINE_TS if p.match(line)), None)
        if m is None:
            return True
        raw_ts = m.group("ts")
        stamp = ctx.ts(raw_ts)
        rest = line[m.end() :].lstrip(" |:-\t")
        lm = _LEVEL_TOKEN.match(rest)
        level = _LEVELS[lm.group(1).upper()] if lm else None
        if lm:
            rest = rest[lm.end() :].lstrip(" |:-\t")
        attrs = {}
        inferred = level is None
    where = f"line {lineno}"
    if stamp is None:
        ctx.reject(where, f"unreadable timestamp {raw_ts[:40]!r}")
        return None
    text = ctx.clean(rest) or "(empty message)"
    kv = {k.lower(): v.strip('"') for k, v in _KV.findall(text)}
    svc_raw = next((kv[k] for k in _KV_SERVICE if kv.get(k)), None)
    if level is None and (lv := map_level(kv.get("level") or kv.get("lvl") or kv.get("severity"))):
        level, inferred = lv, False
    svc = ctx.service(svc_raw)
    if svc is None:
        ctx.reject(where, "no service (add service=<name> or declare the file's service)")
        return None
    for k, v in kv.items():
        if k in _KV_SERVICE or k in _KV_TRACE or k in _KV_SPAN or k in ("level", "lvl", "severity"):
            continue
        if len(attrs) < 20:
            attrs[k] = v[:300]
    upstream = next((normalize_service(kv[k]) for k in _UPSTREAM_KEYS if kv.get(k)), None)
    if upstream:
        attrs["upstream"] = upstream
    return LogRecord(
        ts=stamp[0],
        ts_original=raw_ts[:64],
        tz=stamp[1],
        service=svc[0],
        service_source=svc[1],  # type: ignore[arg-type]
        source=f"{ctx.report.name}:{where}",
        level=level or infer_level(text),  # type: ignore[arg-type]
        level_inferred=inferred,
        message=text,
        trace_id=next((kv[k] for k in _KV_TRACE if kv.get(k)), None),
        span_id=next((kv[k] for k in _KV_SPAN if kv.get(k)), None),
        attributes=ctx.clean_attrs(attrs),
    )


def _parse_log_text(content: str, ctx: _Ctx) -> None:
    ctx.report.format = "text log"
    pending: LogRecord | None = None
    continued = 0
    json_lines = 0
    for lineno, raw in enumerate(content.splitlines(), start=1):
        if ctx.full:
            break
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if line.lstrip().startswith("{"):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                obj = None
            if isinstance(obj, dict):
                if pending:
                    ctx.add(pending)
                    pending = None
                json_lines += 1
                _structured(obj, ctx, f"line {lineno}")
                continue
        parsed = _text_line(line, ctx, lineno)
        if parsed is True:
            if pending is not None and continued < 50:
                cleaned = ctx.clean(line)
                pending = pending.model_copy(update={"message": (pending.message + "\n" + cleaned)[:MAX_MESSAGE_CHARS]})
                continued += 1
            elif pending is None:
                ctx.reject(f"line {lineno}", "no timestamp at the start of the line (timestamps are never invented)")
            continue
        if pending:
            ctx.add(pending)
        pending, continued = (parsed if isinstance(parsed, LogRecord) else None), 0
    if pending:
        ctx.add(pending)
    if json_lines and json_lines == sum(ctx.report.records.values()) + ctx.report.rejected:
        ctx.report.format = "JSON lines"


# --------------------------------------------------------------------------------------------- JSON
def _otlp_attrs(items: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for a in items or []:
        if not isinstance(a, dict) or "key" not in a:
            continue
        v = a.get("value") or {}
        out[str(a["key"])] = next(iter(v.values()), None) if isinstance(v, dict) and v else v
    return out


def _parse_otlp(doc: dict[str, Any], ctx: _Ctx) -> None:
    ctx.report.format = "OTLP/JSON traces"
    n = 0
    for rs in doc.get("resourceSpans") or []:
        resource = _otlp_attrs((rs.get("resource") or {}).get("attributes"))
        for ss in rs.get("scopeSpans") or rs.get("instrumentationLibrarySpans") or []:
            for sp in ss.get("spans") or []:
                n += 1
                if ctx.full:
                    return
                if not isinstance(sp, dict):
                    ctx.reject(f"span {n}", "not an object")
                    continue
                status = sp.get("status") or {}
                obj = {
                    **_otlp_attrs(sp.get("attributes")),
                    "trace_id": sp.get("traceId"),
                    "span_id": sp.get("spanId"),
                    "parent_span_id": sp.get("parentSpanId") or None,
                    "name": sp.get("name"),
                    "kind": sp.get("kind"),
                    "start_time": _nanos(sp.get("startTimeUnixNano")),
                    "end_time": _nanos(sp.get("endTimeUnixNano")),
                    "status_code": status.get("code"),
                    "status_message": status.get("message"),
                    "service": resource.get("service.name"),
                }
                _structured({k: v for k, v in obj.items() if v not in (None, "")}, ctx, f"span {n}")


def _nanos(value: Any) -> Any:
    try:
        return int(value) if value not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return value


_ARRAY_KEYS = ("records", "events", "logs", "spans", "metrics", "data", "items", "entries", "results")


def _parse_json(content: str, ctx: _Ctx) -> None:
    text = content.strip()
    try:
        doc: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) > 1 and lines[0].lstrip().startswith("{"):
            ctx.report.format = "JSON lines"
            for lineno, ln in enumerate(text.splitlines(), start=1):
                if ctx.full:
                    break
                if not ln.strip():
                    continue
                try:
                    obj = json.loads(ln)
                except json.JSONDecodeError:
                    ctx.reject(f"line {lineno}", "not valid JSON")
                    continue
                if isinstance(obj, dict):
                    _structured(obj, ctx, f"line {lineno}")
                else:
                    ctx.reject(f"line {lineno}", "not a JSON object")
            return
        ctx.issue(f"not valid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg})")
        ctx.report.format = "invalid JSON"
        return
    if isinstance(doc, dict) and "resourceSpans" in doc:
        _parse_otlp(doc, ctx)
        return
    items: Any = doc
    inherited: str | None = None
    if isinstance(doc, dict):
        key = next((k for k in _ARRAY_KEYS if isinstance(doc.get(k), list)), None)
        if key is None:
            items = [doc]
        else:
            items = doc[key]
            inherited = doc.get("service") if isinstance(doc.get("service"), str) else None
    if not isinstance(items, list):
        ctx.issue("expected an array of objects, an object containing one, JSON lines, or an OTLP trace export")
        ctx.report.format = "unsupported JSON"
        return
    ctx.report.format = "JSON array"
    for i, item in enumerate(items, start=1):
        if ctx.full:
            break
        if isinstance(item, dict):
            _structured(item, ctx, f"item {i}", inherited_service=inherited)
        else:
            ctx.reject(f"item {i}", "not a JSON object")


# --------------------------------------------------------------------------------------------- CSV
def _number(value: str) -> float | None:
    v = value.strip().replace("%", "")
    if not v:
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def _parse_csv(content: str, ctx: _Ctx) -> None:
    sample = content[:4096]
    try:
        dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = csv.reader(io.StringIO(content), dialect)
    header = next(rows, None)
    if not header:
        ctx.issue("missing header row")
        ctx.report.format = "invalid CSV"
        return
    cols = [h.strip().lstrip("﻿") for h in header]
    lower = [c.lower() for c in cols]

    def col(names: Iterable[str]) -> int | None:
        return next((lower.index(n) for n in names if n in lower), None)

    ts_i = col(_TS_KEYS)
    if ts_i is None:
        ctx.issue("no timestamp column (expected one of: timestamp, time, ts, @timestamp, datetime)")
        ctx.report.format = "CSV without timestamps"
        return
    svc_i = col(_SERVICE_KEYS)
    unit_i = col(("unit", "units"))
    metric_i = col(("metric", "metric_name", "metricname"))
    value_i = col(("value",))
    type_i = col(("event_type", "eventtype", "type", "event", "kind", "category"))
    if metric_i is not None and value_i is not None:
        ctx.report.format = "CSV metrics (long)"
        mode = "long"
    elif type_i is not None and value_i is None:
        ctx.report.format = "CSV events"
        mode = "events"
    else:
        ctx.report.format = "CSV metrics (wide)"
        mode = "wide"
    skip = {i for i in (ts_i, svc_i, unit_i) if i is not None}
    wide: list[tuple[int, str, str]] = []
    if mode == "wide":
        for i, c in enumerate(cols):
            if i in skip:
                continue
            name, unit = metric_name(c)
            if name is None:
                ctx.issue(f"column {c!r}: not a usable metric name; ignored")
                continue
            wide.append((i, name, unit))
        if not wide:
            ctx.issue("no metric columns found")
            return
    non_numeric: dict[str, int] = {}
    for rowno, row in enumerate(rows, start=2):
        if ctx.full:
            break
        if not any(cell.strip() for cell in row):
            continue
        where = f"row {rowno}"
        if len(row) < len(cols):
            row = [*row, *([""] * (len(cols) - len(row)))]
        stamp = ctx.ts(row[ts_i])
        if stamp is None:
            ctx.reject(where, f"no usable timestamp ({row[ts_i][:40]!r})")
            continue
        svc = ctx.service(row[svc_i] if svc_i is not None else None)
        if svc is None:
            ctx.reject(where, "no service (add a service column or declare the file's service)")
            continue
        base = {
            "ts": stamp[0],
            "ts_original": row[ts_i].strip()[:64],
            "tz": stamp[1],
            "service": svc[0],
            "service_source": svc[1],
            "source": f"{ctx.report.name}:{where}",
        }
        try:
            if mode == "long":
                assert metric_i is not None and value_i is not None
                name, unit = metric_name(row[metric_i])
                value = _number(row[value_i])
                if name is None or value is None:
                    ctx.reject(where, f"invalid metric name or value ({row[metric_i][:30]!r}, {row[value_i][:20]!r})")
                    continue
                stated = row[unit_i].strip().lower() if unit_i is not None else ""
                ctx.add(
                    MetricRecord(
                        **base,
                        metric=name,
                        metric_original=row[metric_i].strip()[:120],
                        value=value,
                        unit=_UNIT_ALIASES.get(stated, stated) if stated else unit,
                    )
                )
            elif mode == "events":
                assert type_i is not None
                et = event_type(row[type_i])
                if et is None:
                    ctx.reject(where, f"unrecognized event type {row[type_i][:30]!r}")
                    continue
                used = {ts_i, type_i, *([svc_i] if svc_i is not None else [])}
                summary_i = col(_SUMMARY_KEYS)
                attrs = {lower[i]: row[i].strip()[:300] for i in range(len(cols)) if i not in used and i != summary_i}
                attrs = {k: v for k, v in attrs.items() if v}
                ctx.add(
                    EventRecord(
                        **base,
                        event_type=et,
                        type_original=row[type_i].strip()[:64],
                        summary=ctx.clean(row[summary_i] if summary_i is not None else row[type_i]),
                        attributes=ctx.clean_attrs(attrs),
                    )
                )
            else:
                for i, name, unit in wide:
                    if ctx.full:
                        break
                    value = _number(row[i]) if i < len(row) else None
                    if value is None:
                        if row[i].strip():
                            non_numeric[cols[i]] = non_numeric.get(cols[i], 0) + 1
                        continue
                    ctx.add(MetricRecord(**base, metric=name, metric_original=cols[i][:120], value=value, unit=unit))
        except ValidationError as exc:
            ctx.reject(where, f"invalid record ({exc.errors()[0]['msg']})")
    for c, n in non_numeric.items():
        ctx.issue(f"column {c!r}: {n} non-numeric value(s) skipped")


# --------------------------------------------------------------------------------------------- entry point
def parse_upload(files: list[UploadFile], *, timezone: str | None = "UTC") -> Dataset:
    """Validate and normalize an upload. Raises ``UploadError`` only for problems with the upload as a whole."""
    if not files:
        raise UploadError("no files were uploaded")
    if len(files) > MAX_FILES:
        raise UploadError(f"too many files ({len(files)}); at most {MAX_FILES} per incident")
    tz, tz_name = resolve_timezone(timezone)
    sizes = [len(f.content.encode("utf-8")) for f in files]
    for f, size in zip(files, sizes, strict=True):
        if size > MAX_FILE_BYTES:
            raise UploadError(f"{f.name!r} is {size / 1e6:.1f} MB; the limit is {MAX_FILE_BYTES // (1024 * 1024)} MB")
    if sum(sizes) > MAX_TOTAL_BYTES:
        raise UploadError(f"the upload is {sum(sizes) / 1e6:.1f} MB; the limit is {MAX_TOTAL_BYTES // 1024 // 1024} MB")
    names: set[str] = set()
    dataset = Dataset(files=[])
    budget = [MAX_RECORDS]
    for index, (f, size) in enumerate(zip(files, sizes, strict=True)):
        name, ext = sanitize_name(f.name, index)
        while name in names:
            stem, suffix = name.rsplit(".", 1)
            name = f"{stem}-{index + 1}.{suffix}"
        names.add(name)
        declared = normalize_service(f.service) if f.service else None
        if f.service and declared is None:
            raise UploadError(f"{f.name!r}: declared service {f.service!r} is not a valid service name")
        report = FileReport(
            index=index,
            name=name,
            original_name=f.name[:200],
            extension=ext,
            bytes=size,
            sha256=hashlib.sha256(f.content.encode("utf-8")).hexdigest(),
            format="",
            declared_service=declared,
        )
        dataset.files.append(report)
        ctx = _Ctx(report, tz, tz_name, declared, dataset, budget)
        if not f.content.strip():
            report.format = "empty"
            ctx.issue("the file is empty")
        elif "\x00" in f.content:
            report.format = "binary"
            ctx.issue("binary content is not supported; upload text logs, JSON or CSV")
        elif ALLOWED_EXTENSIONS[ext] == "csv":
            _parse_csv(f.content, ctx)
        elif ALLOWED_EXTENSIONS[ext] == "json":
            _parse_json(f.content, ctx)
        else:
            _parse_log_text(f.content, ctx)
        if report.format and not report.usable and report.format not in ("empty", "binary"):
            ctx.issue("no usable records were found in this file")
        ctx.finish()
    if budget[0] <= 0:
        dataset.warnings.append(f"record limit reached: only the first {MAX_RECORDS} records were kept")
    for report in dataset.files:
        if report.redactions:
            dataset.warnings.append(
                f"{report.name}: {report.redactions} value(s) that looked like credentials were redacted"
            )
    return dataset
