"""Connected observability (v0.6; Datadog v0.9): connector status, preview and incident creation.

A connected incident is backed by a read-only *snapshot*: the selected query templates are run for the incident's
services over one bounded window, normalized into the same evidence records as an upload and stored in
``ops.uploaded_datasets`` together with each query's provenance. The investigation then reads only that snapshot
(``opspilot-connected-telemetry``), so its evidence, citations and report are reproducible and the backend is never
contacted during an investigation. Deleting the incident deletes the snapshot.

Backend failures (authentication, unavailable, timeouts, rejected queries) are reported per query and never raised
as HTTP authentication errors, so a connector's 401 cannot be mistaken for the operator's own session expiring.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_api import repositories as repo
from opspilot_api.services.incidents import to_contract
from opspilot_api.services.uploads import LOOKAHEAD, LOOKBACK, samples
from opspilot_shared.connectors.contract import ConnectorError, FetchWindow
from opspilot_shared.connectors.registry import ConnectorRegistry
from opspilot_shared.connectors.snapshot import MAX_QUERIES, Snapshot, SourceSelection, collect
from opspilot_shared.db.models import OpsIncident, OpsUploadedDataset
from opspilot_shared.domain.common import utcnow
from opspilot_shared.domain.incidents import Incident, IncidentStatus
from opspilot_shared.errors import ConflictError, ValidationFailure
from opspilot_shared.logging import get_logger

_log = get_logger(__name__)


def _raise(exc: ConnectorError) -> None:
    if exc.kind == "not_configured":
        raise ConflictError(exc.message) from exc
    raise ValidationFailure(exc.message) from exc


def _window(req: Any) -> FetchWindow:
    return FetchWindow(start=req.start, end=req.end)


def _services(req: Any) -> list[str]:
    return list(dict.fromkeys([req.service, *req.affected_services]))


def coverage_warnings(snap: Snapshot, req: Any) -> list[str]:
    warnings = list(snap.dataset.warnings)
    when: datetime | None = req.incident_time
    if when is not None:
        if not req.start <= when <= req.end:
            warnings.append("the incident time is outside the selected window")
        else:
            lo, hi = when - LOOKBACK, when + LOOKAHEAD
            if req.start > lo or req.end < hi:
                warnings.append(
                    "the investigation examines 3 h before to 30 min after the incident time; the selected window "
                    f"covers {max(req.start, lo):%H:%M}Z to {min(req.end, hi):%H:%M}Z of that range"
                )
    records = snap.dataset.all_records()
    if records and not any(r.service == req.service for r in records):
        warnings.append(f"no record belongs to the affected service {req.service}")
    return warnings


MAX_CHART_SERIES = 12
MAX_CHART_POINTS = 400


def chart_series(snap: Snapshot) -> list[dict[str, Any]]:
    """v0.9: the metric points exactly as returned, per (service, metric), for preview charts. Nothing is resampled
    or filled in: a series with more points than a chart can show is listed without points."""
    steps = {q.id: q.step_seconds for q in snap.queries}
    groups: dict[tuple[str, str], list[Any]] = {}
    for m in snap.dataset.metrics:
        groups.setdefault((m.service, m.metric), []).append(m)
    out: list[dict[str, Any]] = []
    for (service, metric), rows in sorted(groups.items())[:MAX_CHART_SERIES]:
        rows.sort(key=lambda r: r.ts)
        query = rows[0].source.rsplit(":", 1)[0]
        too_many = len(rows) > MAX_CHART_POINTS or len({tuple(sorted(r.labels.items())) for r in rows}) > 1
        out.append(
            {
                "service": service,
                "metric": metric,
                "unit": rows[0].unit,
                "query": query,
                "step_seconds": steps.get(query),
                "count": len(rows),
                "points": [] if too_many else [[r.ts.isoformat(), r.value] for r in rows],
                "omitted": "more than one series or too many points to chart" if too_many else None,
            }
        )
    return out


class ConnectedService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], registry: ConnectorRegistry) -> None:
        self._sf = session_factory
        self.registry = registry

    # -- connectors ---------------------------------------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        return {**self.registry.describe(), "max_queries": MAX_QUERIES}

    async def test(self, connector_id: str) -> dict[str, Any]:
        try:
            connector = self.registry.get(connector_id)
        except ConnectorError as exc:
            if exc.kind != "not_configured":
                _raise(exc)
            return {"connector": connector_id, "status": "not_configured", "message": exc.message}
        status = await connector.test()
        _log.info("connector_tested", connector=connector_id, status=status.status)
        return status.model_dump(mode="json")

    async def services(self, connector_id: str, start: datetime, end: datetime) -> dict[str, Any]:
        notes: list[str] = []
        try:
            connector = self.registry.get(connector_id)
            window = FetchWindow(start=start, end=end)
            discover = getattr(connector, "discover", None)  # v0.9: discovery that also reports what it left out
            if discover is not None:
                values, notes = await discover(window)
            else:
                values = await connector.services(window)
        except ConnectorError as exc:
            if exc.kind in ("not_configured", "invalid_request"):
                _raise(exc)
            return {"connector": connector_id, "services": [], "error": exc.as_dict(), "notes": []}
        return {"connector": connector_id, "services": values, "error": None, "notes": notes}

    # -- snapshot -----------------------------------------------------------------------------------------------
    async def _collect(self, req: Any) -> Snapshot:
        sources = [SourceSelection(s.connector, tuple(s.templates)) for s in req.sources]
        if len({s.connector for s in sources}) != len(sources):
            raise ValidationFailure("each connector can be selected once")
        try:
            return await collect(self.registry, sources, _services(req), _window(req))
        except ConnectorError as exc:
            _raise(exc)
            raise  # unreachable

    def _view(self, snap: Snapshot, req: Any) -> dict[str, Any]:
        d = snap.dataset
        return {
            "usable": snap.usable,
            "summary": {**d.summary(), "redactions": snap.redactions()},
            "queries": [q.model_dump(mode="json") for q in snap.queries],
            "collected": d.collected,
            "warnings": coverage_warnings(snap, req),
            "samples": samples(d),
            "series": chart_series(snap),
        }

    async def preview(self, req: Any) -> dict[str, Any]:
        snap = await self._collect(req)
        return self._view(snap, req)

    async def create(self, req: Any, *, actor: str = "operator") -> Incident:
        snap = await self._collect(req)
        d = snap.dataset
        failed = [q for q in snap.queries if q.status == "error"]
        if not snap.usable:
            reasons = "; ".join(f"{q.id}: {(q.error or {}).get('kind', 'no data')}" for q in failed) or "no data"
            raise ValidationFailure(f"the selected queries returned no usable records ({reasons})")
        if not any(r.service == req.service for r in (*d.logs, *d.metrics, *d.spans)):
            raise ValidationFailure(
                f"no log, metric or span for the affected service {req.service!r} was returned; check the service "
                "name and the window"
            )
        view = self._view(snap, req)
        incident_id, dataset_id = uuid.uuid4(), uuid.uuid4()
        async with self._sf() as s, s.begin():
            row = OpsIncident(
                id=incident_id,
                reference=await repo.next_incident_reference(s, utcnow()),
                title=req.title,
                description=req.description,
                severity=req.severity.value,
                status=IncidentStatus.OPEN.value,
                service=req.service,
                evidence_source="connector",
                environment_id=None,
                detected_at=req.incident_time,
            )
            s.add(row)
            await s.flush()
            s.add(
                OpsUploadedDataset(
                    id=dataset_id,
                    incident_id=incident_id,
                    affected_services=_services(req),
                    timezone="UTC",
                    files=[],
                    queries=view["queries"],
                    summary={
                        **view["summary"],
                        "samples": view["samples"],
                        "warnings": view["warnings"],
                        "collected": d.collected,
                        "window": {"start": req.start.isoformat(), "end": req.end.isoformat()},
                        "connectors": sorted({q.connector for q in snap.queries}),
                    },
                    records=d.model_dump(mode="json"),
                    storage_dir=None,
                )
            )
            await repo.audit(
                s,
                actor=actor,
                action="incident.connected",
                entity_type="incident",
                entity_id=str(incident_id),
                details={
                    "dataset_id": str(dataset_id),
                    "queries": [
                        {"id": q.id, "status": q.status, "returned": q.returned, "endpoint": q.endpoint}
                        for q in snap.queries
                    ],
                    "records": view["summary"]["records"],
                },
            )
            await s.flush()
            await s.refresh(row)
        _log.info("incident_connected", incident_id=str(incident_id), records=view["summary"]["records"])
        return to_contract(row)
