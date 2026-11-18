"""Stored-evidence provider for read-only incidents: uploaded files (v0.5) and connector snapshots (v0.6).

The investigation agents call the same read tools for every incident (``search_logs``, ``query_metrics``, …). For an
uploaded incident, or one built from a Loki/Prometheus snapshot, those calls are answered here, from the normalized
records stored in ``ops.uploaded_datasets``, instead of by the simulator-backed MCP read server. Tool-call records
name the provider as their server (``opspilot-uploaded-evidence`` or ``opspilot-connected-telemetry``), so traces
never present this evidence as simulator data. A snapshot is answered from what was stored when the incident was
created; investigations never contact the telemetry backend again.

What an upload cannot contain is reported as a tool error rather than invented: there is no live service health, no
runtime configuration, no datastore or queue inspection. Knowledge tools (runbooks, past incidents) are not served
here; the router sends them to the MCP read server, keeping operational evidence and knowledge documents apart.

Tool arguments carry only the opaque evidence-scope ID, service names and time windows. No argument is ever used as a
file path; the raw uploaded files on disk are never read back by this provider.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_agents.ports import ToolGateway, ToolResult
from opspilot_shared.db.models import OpsIncident, OpsUploadedDataset
from opspilot_shared.domain.common import utcnow
from opspilot_shared.domain.evidence import ToolCallRecord, ToolCallStatus
from opspilot_shared.logging import get_logger
from opspilot_shared.redaction import redact
from opspilot_shared.uploads.model import Dataset, EventRecord, EventType, LogRecord, SpanRecord

_log = get_logger(__name__)
SERVER = "opspilot-uploaded-evidence"
CONNECTED_SERVER = "opspilot-connected-telemetry"
EVIDENCE_SOURCE = "upload"
READ_ONLY_SOURCES = ("upload", "connector")
_LEVEL_RANK = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}
_DEPLOY_KINDS = {
    EventType.DEPLOYMENT: "application",
    EventType.ROLLBACK: "rollback",
    EventType.SCHEMA_MIGRATION: "schema_migration",
}
NOT_IN_UPLOAD = {
    "get_service_health": "live service health is not part of uploaded evidence; impact is judged only from the "
    "uploaded metrics and logs",
    "get_service_config": "runtime configuration is not part of uploaded evidence",
    "get_datastore_status": "datastore status is not part of uploaded evidence",
    "inspect_queue": "queue state is not part of uploaded evidence",
}
NOT_IN_SNAPSHOT = {
    "get_service_health": "live service health is not observed: this is a historical snapshot of Loki/Prometheus "
    "telemetry; impact is judged only from its metrics and logs",
    "get_service_config": "runtime configuration is not part of the connected telemetry",
    "get_datastore_status": "datastore status is not part of the connected telemetry",
    "inspect_queue": "queue state is not part of the connected telemetry",
}
NO_CHANGE_HISTORY = (
    "not_available: deployment and configuration-change history is not part of the connected telemetry "
    "(Loki logs and Prometheus metrics); whether a change happened is unknown"
)


class ToolInputError(ValueError):
    pass


def _aware(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ToolInputError(f"{name} must be an ISO-8601 timestamp") from exc
    if dt.tzinfo is None:
        raise ToolInputError(f"{name} must include a timezone")
    return dt


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _short(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:10]


class LoadedUpload:
    __slots__ = ("data", "dataset_id", "incident", "source")

    def __init__(self, dataset_id: uuid.UUID, incident: dict[str, Any], data: Dataset, source: str = "upload") -> None:
        self.dataset_id = dataset_id
        self.incident = incident
        self.data = data
        self.source = source

    @property
    def server(self) -> str:
        return CONNECTED_SERVER if self.source == "connector" else SERVER


def _query_view(q: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "connector", "connector_name", "template_label", "service", "query", "start", "end", "step_seconds")
    return {k: q.get(k) for k in (*keys, "limit", "status", "returned", "truncated", "unit")}


def incident_view(row: OpsIncident, ds: OpsUploadedDataset) -> dict[str, Any]:
    """What ``get_incident`` returns for a read-only incident. ``environment_id`` is the evidence-scope ID that the
    agents pass back to every operational tool."""
    view: dict[str, Any] = {
        "id": str(row.id),
        "reference": row.reference,
        "title": row.title,
        "description": row.description,
        "severity": row.severity,
        "status": row.status,
        "service": row.service,
        "environment_id": str(ds.id),
        "detected_at": _iso(row.detected_at),
        "evidence_source": row.evidence_source,
        "affected_services": list(ds.affected_services or []),
    }
    if row.evidence_source == "connector":  # v0.6: query provenance, for the report (never sent to the model)
        view["telemetry_queries"] = [_query_view(q) for q in ds.queries or []]
        view["snapshot_at"] = _iso(ds.created_at) if ds.created_at else None
    return view


class UploadedEvidenceProvider:
    """Answers read tools for uploaded incidents from their stored dataset."""

    TOOLS = frozenset(
        {
            "get_incident",
            "search_logs",
            "query_metrics",
            "list_service_metrics",
            "list_recent_deployments",
            "get_config_changes",
            "get_service_dependencies",
            *NOT_IN_UPLOAD,
        }
    )

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, cache_size: int = 4) -> None:
        self._sf = session_factory
        self._cache: OrderedDict[str, LoadedUpload] = OrderedDict()
        self._cache_size = cache_size
        self._scopes: dict[str, bool] = {}

    @property
    def server_name(self) -> str:
        return SERVER

    def available_tools(self) -> frozenset[str]:
        return self.TOOLS

    # -- ownership ------------------------------------------------------------------------------------------------
    async def handles(self, tool: str, args: dict[str, Any]) -> bool:
        """True when this call concerns an uploaded incident (decided from the database, never from the caller)."""
        if tool == "get_incident":
            try:
                incident_id = uuid.UUID(str(args.get("incident_id")))
            except ValueError:
                return False
            async with self._sf() as s:
                source = (
                    await s.execute(select(OpsIncident.evidence_source).where(OpsIncident.id == incident_id))
                ).scalar_one_or_none()
            return source in READ_ONLY_SOURCES
        scope = args.get("environment_id")
        if tool not in self.TOOLS or scope is None:
            return False
        key = str(scope)
        if key not in self._scopes:
            try:
                scope_id = uuid.UUID(key)
            except ValueError:
                return False
            async with self._sf() as s:
                found = (
                    await s.execute(select(OpsUploadedDataset.id).where(OpsUploadedDataset.id == scope_id))
                ).scalar_one_or_none()
            self._scopes[key] = found is not None
        return self._scopes[key]

    async def _load(self, *, scope: str | None = None, incident_id: str | None = None) -> LoadedUpload:
        key = scope or f"incident:{incident_id}"
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        async with self._sf() as s:
            stmt = select(OpsUploadedDataset, OpsIncident).join(
                OpsIncident, OpsIncident.id == OpsUploadedDataset.incident_id
            )
            if scope:
                stmt = stmt.where(OpsUploadedDataset.id == uuid.UUID(scope))
            else:
                stmt = stmt.where(OpsUploadedDataset.incident_id == uuid.UUID(str(incident_id)))
            row = (await s.execute(stmt)).one_or_none()
        if row is None:
            raise ToolInputError("not_found: uploaded evidence for this incident no longer exists")
        ds, inc = row
        loaded = LoadedUpload(ds.id, incident_view(inc, ds), Dataset.model_validate(ds.records), inc.evidence_source)
        for k in (str(ds.id), f"incident:{inc.id}"):
            self._cache[k] = loaded
            self._cache.move_to_end(k)
        while len(self._cache) > self._cache_size * 2:
            self._cache.popitem(last=False)
        return loaded

    def forget(self, dataset_id: uuid.UUID, incident_id: uuid.UUID) -> None:
        self._cache.pop(str(dataset_id), None)
        self._cache.pop(f"incident:{incident_id}", None)
        self._scopes.pop(str(dataset_id), None)

    # -- tool calls -----------------------------------------------------------------------------------------------
    async def call(self, tool: str, arguments: dict[str, Any], *, agent: str) -> ToolResult:
        started, t0 = utcnow(), time.perf_counter()
        status, data, error = ToolCallStatus.OK, None, None
        server = SERVER
        try:
            if tool not in self.TOOLS:
                status, error = ToolCallStatus.REJECTED, f"tool {tool!r} is not exposed by {SERVER}"
            elif tool == "get_incident":
                up = await self._load(incident_id=str(arguments["incident_id"]))
                server, data = up.server, up.incident
            else:
                up = await self._load(scope=str(arguments["environment_id"]))
                server = up.server
                if tool in NOT_IN_UPLOAD:
                    missing = NOT_IN_SNAPSHOT if up.source == "connector" else NOT_IN_UPLOAD
                    status, error = ToolCallStatus.ERROR, f"not_available: {missing[tool]}"
                else:
                    data = self._dispatch(tool, arguments, up.data)
        except (ToolInputError, KeyError, ValueError) as exc:
            status, error = ToolCallStatus.ERROR, f"invalid_input: {exc}"
        except Exception as exc:  # storage failure: reported like any tool failure, never raised into the graph
            status, error = ToolCallStatus.ERROR, f"{type(exc).__name__}: {exc}"
            _log.warning("uploaded_evidence_tool_failed", tool=tool, error=error)
        if isinstance(data, dict) and data.get("_error"):
            status, error, data = ToolCallStatus.ERROR, str(data["_error"]), None
        return self.result(tool, arguments, agent, status, data, error, started, t0, server=server)

    def result(
        self,
        tool: str,
        arguments: dict[str, Any],
        agent: str,
        status: ToolCallStatus,
        data: dict[str, Any] | None,
        error: str | None,
        started: datetime | None = None,
        t0: float | None = None,
        *,
        server: str = SERVER,
    ) -> ToolResult:
        record = ToolCallRecord(
            id=f"tc-{uuid.uuid4().hex[:16]}",
            tool=tool,
            server=server,
            agent=agent,
            arguments=redact({k: str(v) if isinstance(v, datetime | uuid.UUID) else v for k, v in arguments.items()}),
            status=status,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1) if t0 is not None else 0.0,
            started_at=started or utcnow(),
            result_summary=_summary(data),
            error=error,
        )
        return ToolResult(tool=tool, ok=status is ToolCallStatus.OK, data=data, error=error, record=record)

    def _dispatch(self, tool: str, a: dict[str, Any], d: Dataset) -> dict[str, Any]:
        if d.collected is not None:  # v0.6 snapshot: what was not collected is unknown, never "nothing found"
            gap = _snapshot_gap(tool, a, d)
            if gap:
                return {"_error": gap}
        handlers: dict[str, Callable[[dict[str, Any], Dataset], dict[str, Any]]] = {
            "search_logs": search_logs,
            "query_metrics": query_metrics,
            "list_service_metrics": list_service_metrics,
            "list_recent_deployments": list_recent_deployments,
            "get_config_changes": get_config_changes,
            "get_service_dependencies": get_service_dependencies,
        }
        return handlers[tool](a, d)


def _snapshot_gap(tool: str, a: dict[str, Any], d: Dataset) -> str | None:
    collected = d.collected or {}
    svc = str(a.get("service") or "")
    if tool in ("list_recent_deployments", "get_config_changes") and not d.events:
        return NO_CHANGE_HISTORY
    if tool == "search_logs" and svc not in collected.get("log", []):
        return f"not_available: no logs were collected for {svc} (no Loki query for it succeeded); its logs are unknown"
    if tool in ("query_metrics", "list_service_metrics") and svc not in collected.get("metric", []):
        return (
            f"not_available: no metrics were collected for {svc} (no Prometheus query for it succeeded); "
            "its metrics are unknown"
        )
    return None


def _summary(data: dict[str, Any] | None) -> str | None:
    if not data:
        return None
    parts = [f"{k}: {len(v)} item(s)" for k, v in data.items() if isinstance(v, list)]
    parts += [f"{k}={v}" for k, v in data.items() if isinstance(v, str | int | float | bool) and len(str(v)) < 60]
    return ", ".join(parts)[:300] or None


# ------------------------------------------------------------------------------------------------- tool handlers
def _window(a: dict[str, Any]) -> tuple[datetime, datetime]:
    start, end = _aware(a["start"], "start"), _aware(a["end"], "end")
    if end < start:
        raise ToolInputError("end is before start")
    return start, end


def _span_index(d: Dataset) -> tuple[dict[str, SpanRecord], dict[str, list[SpanRecord]]]:
    by_id = {s.span_id: s for s in d.spans}
    children: dict[str, list[SpanRecord]] = {}
    for s in d.spans:
        if s.parent_span_id:
            children.setdefault(s.parent_span_id, []).append(s)
    return by_id, children


def _remote_callee(span: SpanRecord, children: dict[str, list[SpanRecord]]) -> str | None:
    """The first other service below ``span`` in its trace (failing descendants first), else ``peer.service``."""
    stack, seen, other_ok = list(children.get(span.span_id, [])), set(), None
    while stack:
        c = stack.pop(0)
        if c.span_id in seen:
            continue
        seen.add(c.span_id)
        if c.service != span.service:
            if c.status == "error":
                return c.service
            other_ok = other_ok or c.service
            continue
        stack.extend(children.get(c.span_id, []))
    peer = span.attributes.get("peer.service")
    return other_ok or (str(peer) if peer else None)


def _span_entry(span: SpanRecord, children: dict[str, list[SpanRecord]]) -> dict[str, Any]:
    text = f"trace span '{span.name}' failed"
    if span.duration_ms is not None:
        text += f" after {span.duration_ms:.0f} ms"
    if span.status_message:
        text += f": {span.status_message}"
    attrs: dict[str, Any] = {"source_ref": span.source, "derived_from": "trace span", "span_id": span.span_id}
    callee = _remote_callee(span, children)
    if callee:
        attrs["upstream"] = callee
    return {
        "ts": _iso(span.ts),
        "service": span.service,
        "level": "ERROR",
        "message": text,
        "logger": None,
        "trace_id": span.trace_id,
        "attributes": attrs,
    }


def _log_entry(r: LogRecord) -> dict[str, Any]:
    attrs = {**r.attributes, "source_ref": r.source}
    if r.level_inferred:
        attrs["level_inferred"] = True
    if r.service_source == "file_default":
        attrs["service_from"] = "declared for the file"
    return {
        "ts": _iso(r.ts),
        "service": r.service,
        "level": r.level,
        "message": r.message,
        "logger": r.logger,
        "trace_id": r.trace_id,
        "attributes": attrs,
    }


def search_logs(a: dict[str, Any], d: Dataset) -> dict[str, Any]:
    start, end = _window(a)
    svc = str(a["service"])
    min_rank = _LEVEL_RANK.get(str(a.get("min_level") or "WARN").upper(), 2)
    contains = str(a.get("contains") or "").lower()
    limit = max(1, min(int(a.get("limit") or 100), 500))
    entries = [
        _log_entry(r) for r in d.logs if r.service == svc and start <= r.ts <= end and _LEVEL_RANK[r.level] >= min_rank
    ]
    if d.spans:
        _, children = _span_index(d)
        entries += [
            _span_entry(s, children)
            for s in d.spans
            if s.service == svc and s.status == "error" and start <= s.ts <= end
        ]
    if contains:
        entries = [e for e in entries if contains in e["message"].lower()]
    entries.sort(key=lambda e: e["ts"], reverse=True)
    return {"entries": entries[:limit], "total_matched": len(entries), "truncated": len(entries) > limit}


def _sources(refs: list[str]) -> str:
    files: dict[str, int] = {}
    for ref in refs:
        f = ref.rsplit(":", 1)[0]
        files[f] = files.get(f, 0) + 1
    return "; ".join(f"{f} ({n} record(s))" for f, n in files.items())


def query_metrics(a: dict[str, Any], d: Dataset) -> dict[str, Any]:
    start, end = _window(a)
    svc, metric = str(a["service"]), str(a["metric"])
    rows = [m for m in d.metrics if m.service == svc and m.metric == metric and start <= m.ts <= end]
    if not any(m.service == svc and m.metric == metric for m in d.metrics):
        return {"_error": f"not_found: no uploaded metric {metric!r} for {svc}"}
    by_ts: dict[datetime, list[float]] = {}
    for m in rows:
        by_ts.setdefault(m.ts, []).append(m.value)
    unit = next((m.unit for m in d.metrics if m.service == svc and m.metric == metric and m.unit), "")
    return {
        "service": svc,
        "metric": metric,
        "unit": unit,
        "points": [{"ts": _iso(ts), "value": sum(v) / len(v)} for ts, v in sorted(by_ts.items())],
        "sources": _sources([m.source for m in rows]),
    }


def list_service_metrics(a: dict[str, Any], d: Dataset) -> dict[str, Any]:
    svc = str(a["service"])
    units: dict[str, str] = {}
    for m in d.metrics:
        if m.service == svc and (m.metric not in units or (m.unit and not units[m.metric])):
            units[m.metric] = m.unit
    return {"service": svc, "metrics": [{"metric": k, "unit": v} for k, v in sorted(units.items())]}


def _in_window(e: EventRecord, a: dict[str, Any]) -> bool:
    start, end = _window(a)
    svc = a.get("service")
    return start <= e.ts <= end and (not svc or e.service == svc)


def _attr(e: EventRecord, *names: str) -> str | None:
    for n in names:
        v = e.attributes.get(n)
        if v not in (None, ""):
            return str(v)[:200]
    return None


def list_recent_deployments(a: dict[str, Any], d: Dataset) -> dict[str, Any]:
    out = []
    for e in d.events:
        if e.event_type not in _DEPLOY_KINDS or not _in_window(e, a):
            continue
        fields = {
            "id": _attr(e, "id", "deployment_id", "deploy_id", "release_id"),
            "version": _attr(e, "version", "new_version", "to_version", "release"),
            "status": _attr(e, "status", "result"),
            "author": _attr(e, "author", "user", "actor", "triggered_by"),
        }
        consumed = {"id", "deployment_id", "deploy_id", "release_id", "version", "new_version", "to_version"}
        consumed |= {"release", "status", "result", "author", "user", "actor", "triggered_by", "previous_version"}
        consumed |= {"from_version", "old_version"}
        out.append(
            {
                "id": fields["id"] or f"upl-{_short(e.source)}",
                "service": e.service,
                "kind": _DEPLOY_KINDS[e.event_type],
                "version": fields["version"] or "unspecified",
                "previous_version": _attr(e, "previous_version", "from_version", "old_version"),
                "started_at": _iso(e.ts),
                "finished_at": None,
                "status": fields["status"] or "unspecified",
                "author": fields["author"] or "unspecified",
                "change_summary": e.summary,
                "metadata": {
                    "source_ref": e.source,
                    "unspecified_fields": [k for k, v in fields.items() if v is None],
                    **{k: v for k, v in e.attributes.items() if k not in consumed},
                },
            }
        )
    return {"deployments": sorted(out, key=lambda x: x["started_at"])}


def get_config_changes(a: dict[str, Any], d: Dataset) -> dict[str, Any]:
    out = []
    for e in d.events:
        if e.event_type is not EventType.CONFIG_CHANGE or not _in_window(e, a):
            continue
        out.append(
            {
                "id": _attr(e, "id", "change_id") or f"upl-{_short(e.source)}",
                "service": e.service,
                "key": _attr(e, "key", "config_key", "setting", "flag", "parameter") or e.summary[:120],
                "old_value": _attr(e, "old_value", "from", "previous_value", "old"),
                "new_value": _attr(e, "new_value", "to", "value", "new"),
                "changed_at": _iso(e.ts),
                "author": _attr(e, "author", "user", "actor") or "unspecified",
            }
        )
    return {"changes": sorted(out, key=lambda x: x["changed_at"])}


def get_service_dependencies(a: dict[str, Any], d: Dataset) -> dict[str, Any]:
    svc = str(a["service"])
    if not any(s.service == svc for s in d.spans):
        return {"_error": f"not_available: no traces were uploaded for {svc}, so its dependencies are unknown"}
    by_id, _ = _span_index(d)
    edges: set[tuple[str, str]] = set()
    for s in d.spans:
        parent = by_id.get(s.parent_span_id or "")
        if parent is not None and parent.service != s.service:
            edges.add((parent.service, s.service))

    def dep(caller: str, callee: str) -> dict[str, Any]:
        return {"service": caller, "depends_on": callee, "kind": "observed_call", "critical": False}

    return {
        "service": svc,
        "downstream": [dep(c, t) for c, t in sorted(edges) if c == svc],
        "upstream": [dep(c, t) for c, t in sorted(edges) if t == svc],
    }


class EvidenceRouter:
    """``ToolGateway`` that sends calls about uploaded incidents to the file-backed provider and everything else
    (simulator incidents, knowledge retrieval) to the MCP read server."""

    def __init__(self, read: ToolGateway, uploads: UploadedEvidenceProvider) -> None:
        self._read = read
        self.uploads = uploads

    @property
    def server_name(self) -> str:
        return self._read.server_name

    def available_tools(self) -> frozenset[str]:
        return self._read.available_tools()

    async def call(self, tool: str, arguments: dict[str, Any], *, agent: str) -> ToolResult:
        try:
            mine = await self.uploads.handles(tool, arguments)
        except Exception as exc:  # cannot tell where the call belongs: fail closed for this call
            _log.warning("evidence_routing_failed", tool=tool, error=str(exc))
            return self.uploads.result(
                tool, arguments, agent, ToolCallStatus.ERROR, None, f"evidence routing failed: {type(exc).__name__}"
            )
        if mine:
            return await self.uploads.call(tool, arguments, agent=agent)
        return await self._read.call(tool, arguments, agent=agent)
