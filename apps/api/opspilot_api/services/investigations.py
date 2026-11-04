"""Investigation orchestration: start, background execution, persistence, resume, cancel.

The runner is the single writer of investigation records. It streams the LangGraph run and
persists each node's output (events, tool calls, evidence) as it arrives, so the UI can poll
progress and nothing is lost if the process dies (the checkpoint has the rest).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_api import repositories as repo
from opspilot_shared.db.models import (
    OpsActionRequest,
    OpsEvidence,
    OpsIncident,
    OpsInvestigation,
    OpsToolInvocation,
    OpsWorkflowEvent,
)
from opspilot_shared.domain.common import utcnow
from opspilot_shared.domain.incidents import IncidentStatus
from opspilot_shared.domain.investigation import InvestigationStatus
from opspilot_shared.errors import ConflictError, NotFoundError, OpsPilotError
from opspilot_shared.logging import get_logger, log_context
from opspilot_shared.tracing import get_tracer

_log = get_logger(__name__)
_tracer = get_tracer(__name__)
SENSITIVE_STATE_KEYS = ("approval_token",)


def thread_config(investigation_id: uuid.UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(investigation_id)}, "recursion_limit": 80}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("<redacted>" if k in SENSITIVE_STATE_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class InvestigationRunner:
    """Runs graph segments as bounded background tasks (one per investigation at a time)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], graph: Any, max_concurrency: int) -> None:
        self._sf = session_factory
        self._graph = graph
        self._sem = asyncio.Semaphore(max_concurrency)
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    def is_active(self, investigation_id: uuid.UUID) -> bool:
        t = self._tasks.get(investigation_id)
        return t is not None and not t.done()

    def submit(self, investigation_id: uuid.UUID, graph_input: Any) -> None:
        if self.is_active(investigation_id):
            raise ConflictError("investigation is already executing")
        task = asyncio.create_task(self.run(investigation_id, graph_input), name=f"investigation-{investigation_id}")
        self._tasks[investigation_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(investigation_id, None))

    async def cancel(self, investigation_id: uuid.UUID) -> bool:
        t = self._tasks.get(investigation_id)
        if t and not t.done():
            t.cancel()
            return True
        return False

    async def shutdown(self) -> None:
        for t in list(self._tasks.values()):
            t.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def wait(self, investigation_id: uuid.UUID) -> None:
        t = self._tasks.get(investigation_id)
        if t:
            await asyncio.shield(t)

    async def run(self, investigation_id: uuid.UUID, graph_input: Any) -> None:
        config = thread_config(investigation_id)
        async with self._sem:
            async with self._sf() as s:
                inv = await s.get(OpsInvestigation, investigation_id)
            if inv is None:
                return
            incident_id = inv.incident_id
            with (
                log_context(investigation_id=str(investigation_id), incident_id=str(incident_id)),
                _tracer.start_as_current_span("investigation.run") as span,
            ):
                span.set_attribute("investigation.id", str(investigation_id))
                async with self._sf() as s, s.begin():
                    await repo.set_investigation(
                        s,
                        investigation_id,
                        status=InvestigationStatus.RUNNING.value,
                        started_at=inv.started_at or utcnow(),
                        error=None,
                        error_class=None,
                    )
                    await repo.set_incident_status(s, incident_id, IncidentStatus.INVESTIGATING.value)
                    await repo.add_event(
                        s,
                        investigation_id,
                        "run_started",
                        None,
                        {"resume": isinstance(graph_input, Command) or graph_input is None},
                    )
                try:
                    async for mode, chunk in self._graph.astream(
                        graph_input, config, stream_mode=["updates", "custom"]
                    ):
                        await self._persist(investigation_id, incident_id, mode, chunk)
                    await self._finish_segment(investigation_id, incident_id, config)
                except asyncio.CancelledError:
                    await self._mark(
                        investigation_id, InvestigationStatus.CANCELLED, "cancelled by operator", "cancelled"
                    )
                    raise
                except Exception as exc:
                    error_class = exc.error_class if isinstance(exc, OpsPilotError) else type(exc).__name__
                    _log.exception("investigation_failed", error_class=error_class)
                    await self._mark(investigation_id, InvestigationStatus.FAILED, str(exc)[:2000], error_class)

    async def _mark(
        self, investigation_id: uuid.UUID, status: InvestigationStatus, error: str, error_class: str
    ) -> None:
        async with self._sf() as s, s.begin():
            inv = await s.get(OpsInvestigation, investigation_id)
            await repo.set_investigation(
                s, investigation_id, status=status.value, error=error, error_class=error_class, completed_at=utcnow()
            )
            await repo.add_event(
                s, investigation_id, "run_" + status.value, None, {"error": error, "error_class": error_class}
            )
            if inv:
                await repo.set_incident_status(s, inv.incident_id, IncidentStatus.OPEN.value)

    async def _persist(self, investigation_id: uuid.UUID, incident_id: uuid.UUID, mode: str, chunk: Any) -> None:
        async with self._sf() as s, s.begin():
            if mode == "custom" and isinstance(chunk, dict) and chunk.get("event") == "node_started":
                await repo.set_investigation(s, investigation_id, current_step=chunk["node"])
                await repo.add_event(s, investigation_id, "node_started", chunk["node"], {})
                return
            if mode != "updates":
                return
            for node, update in chunk.items():
                if node == "__interrupt__":
                    for intr in update:
                        await self._on_interrupt(s, investigation_id, incident_id, intr.value)
                    continue
                update = update or {}
                await repo.upsert_evidence(s, investigation_id, update.get("evidence") or {})
                await repo.insert_tool_calls(s, investigation_id, update.get("tool_calls") or [])
                payload = {
                    "tool_calls": [
                        {"id": c["id"], "tool": c["tool"], "status": c["status"], "latency_ms": c["latency_ms"]}
                        for c in update.get("tool_calls") or []
                    ],
                    "llm_calls": update.get("llm_calls") or [],
                    "evidence_ids": list((update.get("evidence") or {}).keys()),
                    "observations": update.get("observations") or [],
                    "errors": update.get("errors") or [],
                    "queued": update.get("task_queue"),
                    "active_task": update.get("active_task"),
                }
                await repo.add_event(s, investigation_id, "node_completed", node, redact(payload))
                if node == "execute" and update.get("remediation"):
                    await self._on_executed(s, investigation_id, update["remediation"])
                if node == "verify" and update.get("verification"):
                    await self._on_verified(s, investigation_id, update["verification"])

    async def _on_interrupt(
        self, s: AsyncSession, investigation_id: uuid.UUID, incident_id: uuid.UUID, value: dict[str, Any]
    ) -> None:
        action = value["action"]
        action_id = uuid.UUID(action["action_id"])
        async with self._sf() as ro:
            inc = await ro.get(OpsIncident, incident_id)
        assert inc is not None
        stmt = (
            pg_insert(OpsActionRequest)
            .values(
                id=action_id,
                investigation_id=investigation_id,
                incident_id=incident_id,
                environment_id=inc.environment_id,
                action_type=action["action_type"],
                parameters=action["parameters"],
                params_hash=action["params_hash"],
                rationale=action["rationale"],
                risk=action["risk"],
                status="pending",
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await s.execute(stmt)  # idempotent: re-running the interrupt never duplicates the request
        await repo.set_investigation(
            s, investigation_id, status=InvestigationStatus.AWAITING_APPROVAL.value, current_step="await_approval"
        )
        await repo.set_incident_status(s, incident_id, IncidentStatus.AWAITING_APPROVAL.value)
        await repo.add_event(s, investigation_id, "approval_requested", "await_approval", {"action": action})
        await repo.audit(
            s,
            actor="agent",
            action="action.requested",
            entity_type="action_request",
            entity_id=str(action_id),
            details=action,
        )

    async def _on_executed(self, s: AsyncSession, investigation_id: uuid.UUID, rem: dict[str, Any]) -> None:
        action_id = rem.get("action_id")
        if not action_id:
            row = (
                (
                    await s.execute(
                        select(OpsActionRequest).where(
                            OpsActionRequest.investigation_id == investigation_id, OpsActionRequest.status == "approved"
                        )
                    )
                )
                .scalars()
                .first()
            )
            action_id = str(row.id) if row else None
        if action_id:
            status = "succeeded" if rem.get("status") == "succeeded" else "failed"
            await repo.transition_action(
                s,
                uuid.UUID(action_id),
                ("approved", "executing"),
                status=status,
                executed_at=utcnow(),
                execution_result=rem,
            )
            await repo.audit(
                s,
                actor="opspilot-actions",
                action=f"action.{status}",
                entity_type="action_request",
                entity_id=action_id,
                details=rem,
            )

    async def _on_verified(self, s: AsyncSession, investigation_id: uuid.UUID, ver: dict[str, Any]) -> None:
        row = (
            (
                await s.execute(
                    select(OpsActionRequest)
                    .where(OpsActionRequest.investigation_id == investigation_id)
                    .order_by(OpsActionRequest.requested_at.desc())
                )
            )
            .scalars()
            .first()
        )
        if row:
            row.verification = ver
            await repo.audit(
                s,
                actor="agent",
                action="action.verified",
                entity_type="action_request",
                entity_id=str(row.id),
                details=ver,
            )

    async def _finish_segment(
        self, investigation_id: uuid.UUID, incident_id: uuid.UUID, config: dict[str, Any]
    ) -> None:
        snapshot = await self._graph.aget_state(config)
        values = snapshot.values
        if snapshot.next:  # paused (interrupt): status already recorded; expose the RCA for the reviewer
            async with self._sf() as s, s.begin():
                await repo.set_investigation(
                    s,
                    investigation_id,
                    result=redact(
                        {
                            k: values.get(k)
                            for k in (
                                "classification",
                                "plan",
                                "rca",
                                "proposed_action",
                                "window",
                                "rejected_proposals",
                                "errors",
                            )
                        }
                    ),
                )
            return
        status = values.get("status")
        final = InvestigationStatus.COMPLETED if status == "completed" else InvestigationStatus.FAILED
        result = redact(
            {
                k: values.get(k)
                for k in (
                    "classification",
                    "plan",
                    "rca",
                    "proposed_action",
                    "approval",
                    "remediation",
                    "verification",
                    "rejected_proposals",
                    "window",
                    "errors",
                )
            }
        )
        incident_status = IncidentStatus.OPEN
        if (values.get("verification") or {}).get("recovered"):
            incident_status = IncidentStatus.MITIGATED
        errs = values.get("errors") or []
        async with self._sf() as s, s.begin():
            await repo.set_investigation(
                s,
                investigation_id,
                status=final.value,
                completed_at=utcnow(),
                result=result,
                report_markdown=(values.get("report") or {}).get("markdown"),
                current_step=values.get("current_step"),
                error=(errs[-1]["message"] if final is InvestigationStatus.FAILED and errs else None),
                error_class=(errs[-1]["error_class"] if final is InvestigationStatus.FAILED and errs else None),
            )
            await repo.set_incident_status(s, incident_id, incident_status.value)
            await repo.add_event(
                s, investigation_id, "run_" + final.value, None, {"incident_status": incident_status.value}
            )


class InvestigationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: InvestigationRunner,
        graph: Any,
        model_name: str,
    ) -> None:
        self._sf = session_factory
        self.runner = runner
        self._graph = graph
        self._model = model_name

    async def start(self, incident_id: uuid.UUID) -> OpsInvestigation:
        async with self._sf() as s, s.begin():
            incident = await s.get(OpsIncident, incident_id)
            if incident is None:
                raise NotFoundError(f"incident {incident_id} not found")
            active = (
                (
                    await s.execute(
                        select(OpsInvestigation).where(
                            OpsInvestigation.incident_id == incident_id,
                            OpsInvestigation.status.in_(["queued", "running", "awaiting_approval"]),
                        )
                    )
                )
                .scalars()
                .first()
            )
            if active:
                raise ConflictError(f"investigation {active.id} is already {active.status} for this incident")
            inv = OpsInvestigation(
                id=uuid.uuid4(), incident_id=incident_id, status=InvestigationStatus.QUEUED.value, model=self._model
            )
            s.add(inv)
            await s.flush()
            await repo.add_event(s, inv.id, "queued", None, {})
            await repo.audit(
                s, actor="operator", action="investigation.started", entity_type="investigation", entity_id=str(inv.id)
            )
        self.runner.submit(inv.id, {"investigation_id": str(inv.id), "incident_id": str(incident_id)})
        return inv

    async def get(self, investigation_id: uuid.UUID) -> OpsInvestigation:
        async with self._sf() as s:
            inv = await s.get(OpsInvestigation, investigation_id)
        if inv is None:
            raise NotFoundError(f"investigation {investigation_id} not found")
        return inv

    async def list_for_incident(self, incident_id: uuid.UUID) -> list[OpsInvestigation]:
        async with self._sf() as s:
            return list(
                (
                    await s.execute(
                        select(OpsInvestigation)
                        .where(OpsInvestigation.incident_id == incident_id)
                        .order_by(OpsInvestigation.created_at.desc())
                    )
                ).scalars()
            )

    async def events(self, investigation_id: uuid.UUID, after: int = 0) -> list[OpsWorkflowEvent]:
        async with self._sf() as s:
            return list(
                (
                    await s.execute(
                        select(OpsWorkflowEvent)
                        .where(OpsWorkflowEvent.investigation_id == investigation_id, OpsWorkflowEvent.id > after)
                        .order_by(OpsWorkflowEvent.id)
                        .limit(500)
                    )
                ).scalars()
            )

    async def tool_calls(self, investigation_id: uuid.UUID) -> list[OpsToolInvocation]:
        async with self._sf() as s:
            return list(
                (
                    await s.execute(
                        select(OpsToolInvocation)
                        .where(OpsToolInvocation.investigation_id == investigation_id)
                        .order_by(OpsToolInvocation.started_at)
                    )
                ).scalars()
            )

    async def evidence(self, investigation_id: uuid.UUID) -> list[OpsEvidence]:
        async with self._sf() as s:
            return list(
                (
                    await s.execute(
                        select(OpsEvidence)
                        .where(OpsEvidence.investigation_id == investigation_id)
                        .order_by(OpsEvidence.relevance.desc(), OpsEvidence.evidence_id)
                    )
                ).scalars()
            )

    async def actions(self, investigation_id: uuid.UUID) -> list[OpsActionRequest]:
        async with self._sf() as s:
            return list(
                (
                    await s.execute(
                        select(OpsActionRequest)
                        .where(OpsActionRequest.investigation_id == investigation_id)
                        .order_by(OpsActionRequest.requested_at)
                    )
                ).scalars()
            )

    async def workflow_state(self, investigation_id: uuid.UUID) -> dict[str, Any]:
        await self.get(investigation_id)
        snap = await self._graph.aget_state(thread_config(investigation_id))
        values = snap.values or {}
        interrupts = [i.value for t in snap.tasks for i in (t.interrupts or ())]
        out: dict[str, Any] = redact(
            {
                "next": list(snap.next),
                "checkpoint_id": (snap.config or {}).get("configurable", {}).get("checkpoint_id"),
                "created_at": snap.created_at,
                "pending_interrupts": interrupts,
                "executing_in_process": self.runner.is_active(investigation_id),
                "status": values.get("status"),
                "current_step": values.get("current_step"),
                "rounds": values.get("rounds"),
                "task_queue": values.get("task_queue"),
                "completed_tasks": values.get("completed_tasks"),
                "classification": values.get("classification"),
                "plan": values.get("plan"),
                "counts": {
                    "evidence": len(values.get("evidence") or {}),
                    "tool_calls": len(values.get("tool_calls") or []),
                    "llm_calls": len(values.get("llm_calls") or []),
                },
            }
        )
        return out

    async def resume(self, investigation_id: uuid.UUID) -> OpsInvestigation:
        """Continue a run that stopped mid-flight (e.g. API restart). Not for approvals."""
        inv = await self.get(investigation_id)
        if self.runner.is_active(investigation_id):
            raise ConflictError("investigation is currently executing")
        if inv.status in (InvestigationStatus.COMPLETED.value, InvestigationStatus.CANCELLED.value):
            raise ConflictError(f"investigation is {inv.status}")
        snap = await self._graph.aget_state(thread_config(investigation_id))
        if any(t.interrupts for t in snap.tasks):
            raise ConflictError("investigation is waiting for an approval decision; use the approvals API")
        if not snap.values:
            graph_input: Any = {"investigation_id": str(inv.id), "incident_id": str(inv.incident_id)}
        elif not snap.next:
            raise ConflictError("workflow already finished")
        else:
            graph_input = None  # continue from the last checkpoint
        async with self._sf() as s, s.begin():
            await repo.add_event(s, investigation_id, "resume_requested", None, {"from_next": list(snap.next)})
        self.runner.submit(investigation_id, graph_input)
        return inv

    async def cancel(self, investigation_id: uuid.UUID, actor: str) -> OpsInvestigation:
        inv = await self.get(investigation_id)
        if InvestigationStatus(inv.status).terminal:
            raise ConflictError(f"investigation is already {inv.status}")
        await self.runner.cancel(investigation_id)
        async with self._sf() as s, s.begin():
            for a in (
                await s.execute(
                    select(OpsActionRequest).where(
                        OpsActionRequest.investigation_id == investigation_id, OpsActionRequest.status == "pending"
                    )
                )
            ).scalars():
                await repo.transition_action(
                    s, a.id, ("pending",), status="cancelled", decided_at=utcnow(), decided_by=actor
                )
                await repo.audit(
                    s, actor=actor, action="action.cancelled", entity_type="action_request", entity_id=str(a.id)
                )
            await repo.set_investigation(
                s, investigation_id, status=InvestigationStatus.CANCELLED.value, completed_at=utcnow()
            )
            await repo.set_incident_status(s, inv.incident_id, IncidentStatus.OPEN.value)
            await repo.add_event(s, investigation_id, "run_cancelled", None, {"by": actor})
        return await self.get(investigation_id)

    async def mark_orphans_interrupted(self) -> int:
        """At start-up: runs recorded as running/queued have no live task in this new process."""
        async with self._sf() as s, s.begin():
            rows = list(
                (
                    await s.execute(select(OpsInvestigation).where(OpsInvestigation.status.in_(["running", "queued"])))
                ).scalars()
            )
            for r in rows:
                r.status = InvestigationStatus.INTERRUPTED.value
                await repo.add_event(s, r.id, "run_interrupted", r.current_step, {"reason": "process restart"})
        return len(rows)
