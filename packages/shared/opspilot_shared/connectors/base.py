"""Shared plumbing for HTTP telemetry connectors (v0.6)."""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from opspilot_shared.connectors.contract import (
    ConnectionStatus,
    ConnectorError,
    ConnectorKind,
    FetchWindow,
    QueryProvenance,
    QueryTemplate,
    Signal,
)
from opspilot_shared.connectors.http import ReadOnlyHttp, validate_base_url
from opspilot_shared.connectors.templates import _SERVICE

MIN_STEP_SECONDS = 15
TARGET_POINTS = 240


class Limits:
    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_window_hours: float = 6.0,
        max_log_lines: int = 2000,
        max_series: int = 20,
        max_response_bytes: int = 5 * 1024 * 1024,
    ) -> None:
        self.timeout = timeout
        self.max_window = timedelta(hours=max_window_hours)
        self.max_log_lines = max_log_lines
        self.max_series = max_series
        self.max_response_bytes = max_response_bytes

    def as_dict(self) -> dict[str, Any]:
        return {
            "timeout_seconds": self.timeout,
            "max_window_hours": self.max_window.total_seconds() / 3600,
            "max_log_lines_per_query": self.max_log_lines,
            "max_series_per_query": self.max_series,
            "max_response_kib": self.max_response_bytes // 1024,
        }


def step_for(window: FetchWindow) -> int:
    """Range-query resolution: about TARGET_POINTS points, a multiple of 15 s, never finer than 15 s."""
    seconds = (window.end - window.start).total_seconds()
    raw = max(MIN_STEP_SECONDS, seconds / TARGET_POINTS)
    return int(math.ceil(raw / MIN_STEP_SECONDS) * MIN_STEP_SECONDS)


class HttpConnector:
    """Common configuration, validation and test logic. Subclasses implement the backend specifics."""

    KIND: ConnectorKind
    SIGNAL: Signal
    NAME: str

    def __init__(
        self,
        *,
        url: str,
        service_label: str,
        templates: list[QueryTemplate],
        limits: Limits,
        headers: dict[str, str] | None = None,
        bearer_token: str = "",
        username: str = "",
        password: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._auth_mode = "bearer token" if bearer_token else "basic auth" if username else "none"
        has_credentials = bool(bearer_token or username or password)
        self.base_url = validate_base_url(url, has_credentials=has_credentials)
        self.service_label = service_label
        self._templates = [t for t in templates if t.connector == self.KIND]
        self.limits = limits
        hdrs = dict(headers or {})
        if bearer_token:
            hdrs["Authorization"] = f"Bearer {bearer_token}"
        self.http = ReadOnlyHttp(
            self.base_url,
            allowed_paths=self.allowed_paths(),
            headers=hdrs,
            auth=(username, password) if username and not bearer_token else None,
            secrets=[bearer_token, password, *(hdrs.values() if headers else [])],
            timeout=limits.timeout,
            max_bytes=limits.max_response_bytes,
            transport=transport,
        )

    # -- subclass hooks -----------------------------------------------------------------------------------------
    def allowed_paths(self) -> list[str]:
        raise NotImplementedError

    def extra_info(self) -> dict[str, Any]:
        return {}

    # -- TelemetryConnector -------------------------------------------------------------------------------------
    @property
    def id(self) -> str:
        return self.KIND

    @property
    def kind(self) -> ConnectorKind:
        return self.KIND

    @property
    def signal(self) -> Signal:
        return self.SIGNAL

    def templates(self) -> list[QueryTemplate]:
        return list(self._templates)

    def template(self, template_id: str) -> QueryTemplate:
        for t in self._templates:
            if t.id == template_id:
                return t
        raise ConnectorError("invalid_request", f"unknown {self.NAME} template {template_id!r}")

    def info(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.NAME,
            "signal": self.signal,
            "configured": True,
            "endpoint": self.base_url,
            "auth": self._auth_mode,
            "service_label": self.service_label,
            "templates": [t.model_dump() for t in self._templates],
            "limits": self.limits.as_dict(),
            **self.extra_info(),
        }

    def check_window(self, window: FetchWindow) -> None:
        if window.start.tzinfo is None or window.end.tzinfo is None:
            raise ConnectorError("invalid_request", "start and end need a timezone")
        if window.end <= window.start:
            raise ConnectorError("invalid_request", "end must be after start")
        if window.end - window.start > self.limits.max_window:
            hours = self.limits.max_window.total_seconds() / 3600
            raise ConnectorError("invalid_request", f"the time window is longer than the {hours:g} h limit")
        if window.end > datetime.now(UTC) + timedelta(minutes=5):
            raise ConnectorError("invalid_request", "the time window ends in the future")

    async def test_paths(self, info_path: str, auth_path: str, params: dict[str, str]) -> ConnectionStatus:
        now = datetime.now(UTC)
        t0 = time.perf_counter()
        version = None
        try:
            try:
                doc, _ = await self.http.get_json(info_path)
                data = doc.get("data", doc) if isinstance(doc, dict) else {}
                version = str(data.get("version"))[:40] if isinstance(data, dict) and data.get("version") else None
            except ConnectorError as exc:
                if exc.kind != "not_found":  # some hosted APIs do not serve build info; the auth probe decides
                    raise
            await self.http.get_json(auth_path, params)
        except ConnectorError as exc:
            status = exc.kind if exc.kind in ("auth_error", "unavailable") else "error"
            if exc.kind == "timeout":
                status = "unavailable"
            return ConnectionStatus(
                connector=self.id,
                status=status,
                message=exc.message,
                checked_at=now,  # type: ignore[arg-type]
            )
        return ConnectionStatus(
            connector=self.id,
            status="ok",
            message=f"{self.NAME} answered" + (f" (version {version})" if version else ""),
            version=version,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            checked_at=now,
        )

    @staticmethod
    def label_values(doc: Any) -> list[str]:
        values = doc.get("data") if isinstance(doc, dict) else None
        if not isinstance(values, list):
            return []
        return sorted({str(v) for v in values if isinstance(v, str) and _SERVICE.match(v)})[:200]

    def provenance(
        self,
        t: QueryTemplate,
        service: str,
        window: FetchWindow,
        *,
        endpoint: str,
        query: str,
        step: int | None = None,
        limit: int | None = None,
    ) -> QueryProvenance:
        return QueryProvenance(
            id=f"{self.id}/{t.id}/{service}",
            connector=self.KIND,
            connector_name=self.NAME,
            endpoint=endpoint,
            template=t.id,
            template_label=t.label,
            service=service,
            query=query,
            start=window.start,
            end=window.end,
            step_seconds=step,
            limit=limit,
            status="empty",
            unit=t.unit,
            fetched_at=datetime.now(UTC),
        )


def from_epoch_ns(raw: Any) -> datetime | None:
    try:
        n = int(str(raw))
    except ValueError:
        return None
    return datetime.fromtimestamp(n // 1_000_000_000, UTC) + timedelta(microseconds=(n % 1_000_000_000) // 1000)


def from_epoch_s(raw: Any) -> datetime | None:
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return datetime.fromtimestamp(f, UTC)


def epoch_ns(dt: datetime) -> str:
    delta = dt - datetime(1970, 1, 1, tzinfo=UTC)
    return str((delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000)


def epoch_s(dt: datetime) -> str:
    return f"{dt.timestamp():.3f}"
