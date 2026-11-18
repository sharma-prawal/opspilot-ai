"""Normalized records for uploaded evidence and the limits that bound an upload.

Every record keeps where it came from (``source``: ``<file>:<line|row|item>``), the timestamp exactly as written
(``ts_original``) and how its timezone was established (``tz``), and whether its service came from the record itself
or from the service the user declared for the file (``service_source``). Nothing is invented: a record without a
usable timestamp or service is rejected and reported, never filled in.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from opspilot_shared.domain.common import ServiceName, UtcDatetime

MAX_FILES = 5
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 50_000
MAX_MESSAGE_CHARS = 4_000
MAX_ISSUES_PER_FILE = 25
ALLOWED_EXTENSIONS: dict[str, str] = {".log": "log", ".txt": "log", ".json": "json", ".csv": "csv"}


class SignalType(StrEnum):
    LOG = "log"
    METRIC = "metric"
    SPAN = "span"
    EVENT = "event"


class EventType(StrEnum):
    DEPLOYMENT = "deployment"
    ROLLBACK = "rollback"
    SCHEMA_MIGRATION = "schema_migration"
    CONFIG_CHANGE = "config_change"
    ALERT = "alert"


ServiceSource = Literal["record", "file_default"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: UtcDatetime
    ts_original: str
    tz: str = Field(description="offset as written, 'epoch' (UTC) or 'assumed <zone>' for timestamps without one")
    service: ServiceName
    service_source: ServiceSource
    source: str = Field(description="<file>:<line N | row N | item N>")


class LogRecord(_Record):
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"]
    level_inferred: bool = False
    message: str
    logger: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class MetricRecord(_Record):
    metric: str = Field(pattern=r"^[a-z0-9_]{2,63}$")
    metric_original: str
    value: float
    unit: str = Field(default="", description="empty when the file does not state a unit")


class SpanRecord(_Record):
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    duration_ms: float | None = None
    status: Literal["ok", "error", "unset"] = "unset"
    status_message: str | None = None
    kind: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class EventRecord(_Record):
    event_type: EventType
    type_original: str
    summary: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class FileReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    name: str = Field(description="sanitized file name used in source references")
    original_name: str
    extension: str
    bytes: int
    sha256: str
    format: str
    declared_service: str | None = None
    records: dict[str, int] = Field(default_factory=dict)
    rejected: int = 0
    redactions: int = 0
    issues: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    timezones: list[str] = Field(default_factory=list)
    start: datetime | None = None
    end: datetime | None = None

    @property
    def usable(self) -> bool:
        return sum(self.records.values()) > 0


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[FileReport]
    logs: list[LogRecord] = Field(default_factory=list)
    metrics: list[MetricRecord] = Field(default_factory=list)
    spans: list[SpanRecord] = Field(default_factory=list)
    events: list[EventRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def all_records(self) -> list[_Record]:
        return [*self.logs, *self.metrics, *self.spans, *self.events]

    def summary(self) -> dict[str, Any]:
        records = self.all_records()
        times = [r.ts for r in records]
        metrics: dict[str, set[str]] = {}
        for m in self.metrics:
            metrics.setdefault(m.service, set()).add(m.metric)
        return {
            "records": {
                "log": len(self.logs),
                "metric": len(self.metrics),
                "span": len(self.spans),
                "event": len(self.events),
            },
            "rejected": sum(f.rejected for f in self.files),
            "redactions": sum(f.redactions for f in self.files),
            "services": sorted({r.service for r in records}),
            "metrics_by_service": {k: sorted(v) for k, v in sorted(metrics.items())},
            "event_types": sorted({e.event_type.value for e in self.events}),
            "start": min(times).isoformat() if times else None,
            "end": max(times).isoformat() if times else None,
            "timezones": sorted({r.tz for r in records}),
        }
