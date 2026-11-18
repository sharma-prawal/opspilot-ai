"""Uploaded incident evidence (v0.5): preview, create, inspect, delete and purge.

Files arrive as text in a JSON request (the web BFF only relays JSON). They are parsed and normalized by
``opspilot_shared.uploads`` and stored in two places, both local:

- the normalized records and per-file reports in ``ops.uploaded_datasets`` (read by the file-backed evidence
  provider during an investigation);
- a copy of each raw file under ``UPLOAD_DIR/<dataset id>/`` with a server-generated name, kept for provenance only.
  Nothing reads these files back; they are never executed or served.

Deleting an uploaded incident removes its files, records, investigations and their LangGraph checkpoints.
"""

from __future__ import annotations

import contextlib
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_api import repositories as repo
from opspilot_api.services.incidents import to_contract
from opspilot_shared.config import Settings
from opspilot_shared.db.models import ACTIVE_INVESTIGATION_STATUSES, OpsIncident, OpsInvestigation, OpsUploadedDataset
from opspilot_shared.domain.common import utcnow
from opspilot_shared.domain.incidents import Incident, IncidentStatus
from opspilot_shared.errors import ConflictError, NotFoundError, ValidationFailure
from opspilot_shared.logging import get_logger
from opspilot_shared.uploads.model import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_RECORDS,
    MAX_TOTAL_BYTES,
    Dataset,
)
from opspilot_shared.uploads.parse import UploadError, UploadFile, parse_timestamp, parse_upload, resolve_timezone

_log = get_logger(__name__)
LOOKBACK = timedelta(hours=3)  # the investigation window (AgentPolicy.lookback_hours) before the incident time
LOOKAHEAD = timedelta(minutes=30)
LIMITS = {
    "max_files": MAX_FILES,
    "max_file_bytes": MAX_FILE_BYTES,
    "max_total_bytes": MAX_TOTAL_BYTES,
    "max_records": MAX_RECORDS,
    "extensions": [".log", ".txt", ".json", ".csv"],
}


def _files(req: Any) -> list[UploadFile]:
    return [UploadFile(name=f.name, content=f.content, service=f.service) for f in req.files]


def _parse(req: Any) -> Dataset:
    try:
        return parse_upload(_files(req), timezone=req.timezone)
    except UploadError as exc:
        raise ValidationFailure(str(exc)) from exc


def _incident_time(raw: str | None, timezone: str) -> datetime | None:
    if not raw:
        return None
    tz, name = resolve_timezone(timezone)
    stamp = parse_timestamp(raw, tz, name)
    if stamp is None:
        raise ValidationFailure(f"incident time {raw!r} is not a date and time (e.g. 2026-11-12T09:15)")
    return stamp[0]


def samples(d: Dataset, n: int = 5) -> dict[str, list[dict[str, Any]]]:
    logs = sorted(d.logs, key=lambda r: ({"ERROR": 0, "WARN": 1}.get(r.level, 2), r.ts))[:n]
    spans = sorted(d.spans, key=lambda r: (r.status != "error", r.ts))[:n]
    return {
        "log": [r.model_dump(mode="json") for r in logs],
        "metric": [r.model_dump(mode="json") for r in d.metrics[:n]],
        "span": [r.model_dump(mode="json") for r in spans],
        "event": [r.model_dump(mode="json") for r in d.events[:n]],
    }


def coverage_warnings(
    d: Dataset, incident_time: datetime | None, service: str | None, affected: list[str]
) -> list[str]:
    warnings = list(d.warnings)
    records = d.all_records()
    if not records:
        return warnings
    services = {r.service for r in records}
    for svc in [service, *affected]:
        if svc and svc not in services:
            warnings.append(f"no uploaded record belongs to {svc}; check the service names in your files")
    if incident_time is not None:
        start, end = incident_time - LOOKBACK, incident_time + LOOKAHEAD
        outside = sum(1 for r in records if not start <= r.ts <= end)
        first, last = min(r.ts for r in records), max(r.ts for r in records)
        if last < start or first > end:
            warnings.append(
                f"the incident time is outside the uploaded data ({first:%Y-%m-%d %H:%M}Z to {last:%Y-%m-%d %H:%M}Z); "
                "the analysis looks 3 h before to 30 min after the incident time"
            )
        elif outside:
            warnings.append(
                f"{outside} record(s) fall outside the analysis window (3 h before to 30 min after the incident time) "
                "and will not be examined (change events are searched further back)"
            )
    if not d.metrics:
        warnings.append("no metrics uploaded: impact cannot be measured, so conclusions will stay uncertain")
    return warnings


class UploadService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        checkpointer: Any | None = None,
        provider: Any | None = None,
    ) -> None:
        self._sf = session_factory
        self._root = Path(settings.upload_dir)
        self._retention = settings.upload_retention_days
        self._checkpointer = checkpointer
        self._provider = provider

    # -- preview (stateless) --------------------------------------------------------------------------------------
    def preview(self, req: Any) -> dict[str, Any]:
        d = _parse(req)
        when = _incident_time(req.incident_time, req.timezone)
        return {
            "usable": any(f.usable for f in d.files),
            "files": [f.model_dump(mode="json") for f in d.files],
            "summary": d.summary(),
            "warnings": coverage_warnings(d, when, req.service, list(req.affected_services)),
            "samples": samples(d),
            "limits": LIMITS,
        }

    # -- create -----------------------------------------------------------------------------------------------------
    async def create(self, req: Any, *, actor: str = "operator") -> Incident:
        d = _parse(req)
        if not any(f.usable for f in d.files):
            problems = "; ".join(f"{f.name}: {f.issues[0] if f.issues else 'no records'}" for f in d.files)
            raise ValidationFailure(f"no usable records in the uploaded files ({problems})")
        detected = _incident_time(req.incident_time, req.timezone)
        assert detected is not None
        affected = list(dict.fromkeys([req.service, *req.affected_services]))
        own = [r for r in (*d.logs, *d.metrics, *d.spans) if r.service == req.service]
        if not own:
            raise ValidationFailure(
                f"no uploaded log, metric or trace belongs to the affected service {req.service!r}; "
                f"services found: {', '.join(d.summary()['services']) or 'none'}"
            )
        incident_id, dataset_id = uuid.uuid4(), uuid.uuid4()
        storage = self._store_files(dataset_id, req, d)
        summary = {
            **d.summary(),
            "samples": samples(d),
            "warnings": coverage_warnings(d, detected, req.service, list(req.affected_services)),
        }
        try:
            async with self._sf() as s, s.begin():
                row = OpsIncident(
                    id=incident_id,
                    reference=await repo.next_incident_reference(s, utcnow()),
                    title=req.title,
                    description=req.description,
                    severity=req.severity.value,
                    status=IncidentStatus.OPEN.value,
                    service=req.service,
                    evidence_source="upload",
                    environment_id=None,
                    detected_at=detected,
                )
                s.add(row)
                await s.flush()
                s.add(
                    OpsUploadedDataset(
                        id=dataset_id,
                        incident_id=incident_id,
                        affected_services=affected,
                        timezone=req.timezone,
                        files=[f.model_dump(mode="json") for f in d.files],
                        summary=summary,
                        records=d.model_dump(mode="json"),
                        storage_dir=str(storage) if storage else None,
                    )
                )
                await repo.audit(
                    s,
                    actor=actor,
                    action="incident.uploaded",
                    entity_type="incident",
                    entity_id=str(incident_id),
                    details={
                        "dataset_id": str(dataset_id),
                        "files": [{"name": f.name, "bytes": f.bytes, "sha256": f.sha256} for f in d.files],
                        "records": summary["records"],
                    },
                )
                await s.flush()
                await s.refresh(row)
        except BaseException:
            if storage:
                shutil.rmtree(storage, ignore_errors=True)
            raise
        _log.info("incident_uploaded", incident_id=str(incident_id), records=summary["records"])
        return to_contract(row)

    def _store_files(self, dataset_id: uuid.UUID, req: Any, d: Dataset) -> Path | None:
        """Raw copies under UPLOAD_DIR/<dataset id>/ with server-generated names (never a user-supplied path)."""
        root = self._root.resolve()
        target = (root / str(dataset_id)).resolve()
        if target.parent != root:
            raise ValidationFailure("invalid storage location")
        try:
            target.mkdir(parents=True, mode=0o700, exist_ok=False)
            for f, report in zip(req.files, d.files, strict=True):
                path = (target / f"{report.index + 1:02d}-{report.name}").resolve()
                if path.parent != target:
                    raise ValidationFailure("invalid file name")
                path.write_text(f.content, encoding="utf-8")
                path.chmod(0o600)
        except OSError as exc:
            shutil.rmtree(target, ignore_errors=True)
            _log.warning("upload_storage_failed", error=str(exc))
            raise ValidationFailure(f"could not store the uploaded files locally: {exc.strerror}") from exc
        return target

    # -- inspect ----------------------------------------------------------------------------------------------------
    async def dataset(self, incident_id: uuid.UUID) -> dict[str, Any]:
        async with self._sf() as s:
            ds = (
                await s.execute(select(OpsUploadedDataset).where(OpsUploadedDataset.incident_id == incident_id))
            ).scalar_one_or_none()
        if ds is None:
            raise NotFoundError(f"incident {incident_id} has no uploaded evidence")
        return {
            "dataset_id": str(ds.id),
            "incident_id": str(incident_id),
            "timezone": ds.timezone,
            "affected_services": ds.affected_services,
            "files": ds.files,
            "summary": ds.summary,
            "created_at": ds.created_at.isoformat(),
            "retention_days": self._retention,
        }

    # -- delete / purge ---------------------------------------------------------------------------------------------
    async def discard(self, incident_id: uuid.UUID, *, actor: str = "operator") -> dict[str, Any]:
        async with self._sf() as s, s.begin():
            inc = await s.get(OpsIncident, incident_id, with_for_update=True)
            if inc is None:
                raise NotFoundError(f"incident {incident_id} not found")
            if inc.evidence_source != "upload":
                raise ConflictError("only incidents created from uploaded files can be deleted")
            active = (
                await s.execute(
                    select(OpsInvestigation.id).where(
                        OpsInvestigation.incident_id == incident_id,
                        OpsInvestigation.status.in_(ACTIVE_INVESTIGATION_STATUSES),
                    )
                )
            ).first()
            if active:
                raise ConflictError("an investigation is still running for this incident; cancel it first")
        return (await self._delete([incident_id], actor=actor))[0]

    async def purge(self, *, older_than_days: int | None = None, actor: str = "maintenance") -> dict[str, Any]:
        cutoff = utcnow() - timedelta(days=older_than_days or self._retention)
        async with self._sf() as s:
            ids = list(
                (
                    await s.execute(
                        select(OpsIncident.id).where(
                            OpsIncident.evidence_source == "upload", OpsIncident.created_at < cutoff
                        )
                    )
                ).scalars()
            )
            busy = set(
                (
                    await s.execute(
                        select(OpsInvestigation.incident_id).where(
                            OpsInvestigation.incident_id.in_(ids),
                            OpsInvestigation.status.in_(ACTIVE_INVESTIGATION_STATUSES),
                        )
                    )
                ).scalars()
            )
        removed = await self._delete([i for i in ids if i not in busy], actor=actor)
        return {"cutoff": cutoff.isoformat(), "deleted": len(removed), "skipped_active": len(busy), "items": removed}

    def _remove_dir(self, storage_dir: str) -> bool:
        """Remove one dataset directory, only if it is directly under UPLOAD_DIR."""
        path = Path(storage_dir).resolve()
        if path.parent != self._root.resolve() or not path.is_dir():
            return False
        shutil.rmtree(path, ignore_errors=True)
        return True

    async def _delete(self, incident_ids: list[uuid.UUID], *, actor: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for incident_id in incident_ids:
            async with self._sf() as s:
                ds = (
                    await s.execute(select(OpsUploadedDataset).where(OpsUploadedDataset.incident_id == incident_id))
                ).scalar_one_or_none()
                investigations = list(
                    (
                        await s.execute(select(OpsInvestigation.id).where(OpsInvestigation.incident_id == incident_id))
                    ).scalars()
                )
            # Checkpoints hold evidence derived from the uploaded files: delete them with the incident.
            if self._checkpointer is not None:
                for inv in investigations:
                    await self._checkpointer.adelete_thread(str(inv))
            async with self._sf() as s, s.begin():
                await s.execute(delete(OpsIncident).where(OpsIncident.id == incident_id))  # cascades
                await repo.audit(
                    s,
                    actor=actor,
                    action="incident.upload_deleted",
                    entity_type="incident",
                    entity_id=str(incident_id),
                    details={"investigations": len(investigations)},
                )
            files_removed = bool(ds is not None and ds.storage_dir and self._remove_dir(ds.storage_dir))
            if ds is not None and self._provider is not None:
                with contextlib.suppress(Exception):
                    self._provider.forget(ds.id, incident_id)
            out.append(
                {
                    "incident_id": str(incident_id),
                    "investigations": len(investigations),
                    "checkpoints_deleted": self._checkpointer is not None,
                    "files_removed": files_removed,
                }
            )
        return out
