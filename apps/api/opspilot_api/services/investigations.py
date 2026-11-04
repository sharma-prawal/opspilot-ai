"""Investigation orchestration: start, background execution, persistence, resume, cancel.

The runner is the single writer of investigation records. It streams the LangGraph run and
persists each node's output (events, tool calls, evidence) as it arrives, so the UI can poll
progress and nothing is lost if the process dies (the checkpoint has the rest).
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from langgraph.types import Command
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_api import repositories as repo
from opspilot_shared.db.models import (
    ACTIVE_INVESTIGATION_STATUSES,
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
from opspilot_shared.redaction import redact
from opspilot_shared.tracing import get_tracer

_log = get_logger(__name__)
_tracer = get_tracer(__name__)


def thread_config(investigation_id: uuid.UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(investigation_id)}, "recursion_limit": 80}


class InvestigationRunner:
    """Runs graph segments as bounded background tasks (one per investigation at a time).

    Execution ownership is recorded in the database (audit finding G): before a segment runs, the runner
    claims ``run_owner``/``run_lease_until`` with compare-and-set and renews the lease while it runs. A
    second API process cannot run the same workflow concurrently; a crashed owner's lease simply expires.
    The in-process task registry is only a fast path for this process.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        graph: Any,
        max_concurrency: int,
        *,
        lease_seconds: float = 60.0,
        owner: str | None = None,
    ) -> None:
        self._sf = session_factory
        self._graph = graph
        self._sem = asyncio.Semaphore(max_concurrency)
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._shutting_down = False
        self._lease = lease_seconds
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    def is_active(self, investigation_id: uuid.UUID) -> bool:
        t = self._tasks.get(investigation_id)
        return t is not None and not t.done()

    # -- execution ownership lease ----------------------------------------------------
    async def claim(self, investigation_id: uuid.UUID) -> bool:
        """Take (or renew) the execution lease unless another live owner holds it."""
        now = utcnow()
        async with self._sf() as s, s.begin():
            got = (
                await s.execute(
                    update(OpsInvestigation)
                    .where(
                        OpsInvestigation.id == investigation_id,
                        or_(
                            OpsInvestigation.run_owner.is_(None),
                            OpsInvestigation.run_owner == self.owner,
                            OpsInvestigation.run_lease_until < now,
                        ),
                    )
                    .values(run_owner=self.owner, run_lease_until=now + timedelta(seconds=self._lease))
                    .returning(OpsInvestigation.id)
                )
            ).scalar_one_or_none()
        return got is not None

    async def release(self, investigation_id: uuid.UUID) -> None:
        async with self._sf() as s, s.begin():
            await s.execute(
                update(OpsInvestigation)
                .where(OpsInvestigation.id == investigation_id, OpsInvestigation.run_owner == self.owner)
                .values(run_owner=None, run_lease_until=None)
            )

    async def owned_elsewhere(self, investigation_id: uuid.UUID) -> bool:
        """True while another process holds an unexpired execution lease on this investigation."""
        async with self._sf() as s:
            row = (
                await s.execute(
                    select(OpsInvestigation.run_owner, OpsInvestigation.run_lease_until).where(
                        OpsInvestigation.id == investigation_id
                    )
                )
            ).one_or_none()
        if row is None or row.run_owner is None or row.run_owner == self.owner:
            return False
        return row.run_lease_until is not None and row.run_lease_until > utcnow()

    async def _heartbeat(self, investigation_id: uuid.UUID) -> None:
        while True:
            await asyncio.sleep(self._lease / 3)
            if not await self.claim(investigation_id):  # pragma: no cover - lease stolen after expiry
                _log.error("run_lease_lost", investigation_id=str(investigation_id), owner=self.owner)
                return

    def submit(
        self,
        investigation_id: uuid.UUID,
        graph_input: Any,
        *,
        on_success: Callable[[uuid.UUID], Awaitable[None]] | None = None,
        command_id: uuid.UUID | None = None,
        expect_action_id: str | None = None,
    ) -> None:
        """Start a graph segment. ``on_success(command_id)`` runs only after the segment's results are persisted.

        ``expect_action_id``: deliver a resume only if, once the lease is held, the workflow is still paused on
        that action (closes the window between the dispatcher's check and execution)."""
        if self.is_active(investigation_id):
            raise ConflictError("investigation is already executing")
        task = asyncio.create_task(
            self.run(
                investigation_id,
                graph_input,
                on_success=on_success,
                command_id=command_id,
                expect_action_id=expect_action_id,
            ),
            name=f"investigation-{investigation_id}",
        )
        self._tasks[investigation_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(investigation_id, None))

    async def cancel(self, investigation_id: uuid.UUID) -> bool:
        t = self._tasks.get(investigation_id)
        if t and not t.done():
            t.cancel()
            return True
        return False

    async def shutdown(self) -> None:
        # Shutdown interrupts runs (resumable); it is not an operator cancellation (terminal).
        self._shutting_down = True
        for t in list(self._tasks.values()):
            t.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def wait(self, investigation_id: uuid.UUID) -> None:
        t = self._tasks.get(investigation_id)
        if t:
            await asyncio.shield(t)

    async def finalize(self, investigation_id: uuid.UUID) -> None:
        """Persist the final application state of a graph that has already finished (crash recovery)."""
        async with self._sf() as s:
            inv = await s.get(OpsInvestigation, investigation_id)
        if inv is not None:
            await self._finish_segment(investigation_id, inv.incident_id, thread_config(investigation_id))

    async def run(
        self,
        investigation_id: uuid.UUID,
        graph_input: Any,
        *,
        on_success: Callable[[uuid.UUID], Awaitable[None]] | None = None,
        command_id: uuid.UUID | None = None,
        expect_action_id: str | None = None,
    ) -> None:
        config = thread_config(investigation_id)
        async with self._sem:
            if not await self.claim(investigation_id):
                _log.warning("run_skipped_owned_elsewhere", investigation_id=str(investigation_id))
                return
            heartbeat = asyncio.create_task(self._heartbeat(investigation_id), name=f"lease-{investigation_id}")
            try:
                await self._run_owned(investigation_id, graph_input, config, on_success, command_id, expect_action_id)
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                await self.release(investigation_id)

    async def _run_owned(
        self,
        investigation_id: uuid.UUID,
        graph_input: Any,
        config: dict[str, Any],
        on_success: Callable[[uuid.UUID], Awaitable[None]] | None,
        command_id: uuid.UUID | None,
        expect_action_id: str | None,
    ) -> None:
        async with self._sf() as s:
            inv = await s.get(OpsInvestigation, investigation_id)
        if inv is None:
            return
        if expect_action_id is not None:
            snap = await self._graph.aget_state(config)
            waiting = [i.value for t in snap.tasks for i in (t.interrupts or ())]
            if not any((w.get("action") or {}).get("action_id") == expect_action_id for w in waiting):
                _log.warning("resume_skipped_not_waiting", action_id=expect_action_id)
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
                async for mode, chunk in self._graph.astream(graph_input, config, stream_mode=["updates", "custom"]):
                    await self._persist(investigation_id, incident_id, mode, chunk)
                await self._finish_segment(investigation_id, incident_id, config)
                if on_success is not None and command_id is not None:
                    await on_success(command_id)
            except asyncio.CancelledError:
                if self._shutting_down:
                    await self._mark(
                        investigation_id,
                        InvestigationStatus.INTERRUPTED,
                        "process shutting down; resumable from checkpoint",
                        "interrupted",
                    )
                else:
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
                s,
                investigation_id,
                status=status.value,
                error=error,
                error_class=error_class,
                completed_at=utcnow() if status.terminal else None,
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
            .returning(OpsActionRequest.id)
        )
        # Idempotent: re-running the interrupt (or reconciling after a restart) never duplicates the request.
        created = (await s.execute(stmt)).scalar_one_or_none() is not None
        await repo.set_investigation(
            s, investigation_id, status=InvestigationStatus.AWAITING_APPROVAL.value, current_step="await_approval"
        )
        await repo.set_incident_status(s, incident_id, IncidentStatus.AWAITING_APPROVAL.value)
        if created:
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
                                "remediation_plan",
                                "executions",
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
                    "remediation_plan",
                    "executions",
                    "verification",
                    "outcome",
                    "rejected_proposals",
                    "window",
                    "errors",
                )
            }
        )
        outcome = (values.get("outcome") or {}).get("code")
        incident_status = {"mitigated": IncidentStatus.MITIGATED, "no_action_required": IncidentStatus.RESOLVED}.get(
            outcome or "", IncidentStatus.OPEN
        )
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
                s,
                investigation_id,
                "run_" + final.value,
                None,
                {"incident_status": incident_status.value, "outcome": outcome},
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
        self.dispatcher: Any = None  # CommandDispatcher, wired by the runtime (avoids an import cycle)

    async def start(self, incident_id: uuid.UUID) -> OpsInvestigation:
        """Create the incident's single active investigation (audit finding G).

        The incident row is locked so concurrent starts serialize, and the partial unique index
        ``uq_ops_investigations_one_active_per_incident`` enforces the invariant even for writers that
        bypass this method. A violation is reported as a conflict, never as a server error."""
        try:
            async with self._sf() as s, s.begin():
                incident = await s.get(OpsIncident, incident_id, with_for_update=True)
                if incident is None:
                    raise NotFoundError(f"incident {incident_id} not found")
                active = (
                    (
                        await s.execute(
                            select(OpsInvestigation).where(
                                OpsInvestigation.incident_id == incident_id,
                                OpsInvestigation.status.in_(ACTIVE_INVESTIGATION_STATUSES),
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
                await self._started(s, inv)
        except IntegrityError as exc:
            if "uq_ops_investigations_one_active_per_incident" not in str(exc.orig):
                raise
            raise ConflictError("an investigation is already active for this incident") from exc
        self.runner.submit(inv.id, {"investigation_id": str(inv.id), "incident_id": str(incident_id)})
        return inv

    async def _started(self, s: AsyncSession, inv: OpsInvestigation) -> None:
        await repo.add_event(s, inv.id, "queued", None, {})
        await repo.audit(
            s, actor="operator", action="investigation.started", entity_type="investigation", entity_id=str(inv.id)
        )

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
        if self.runner.is_active(investigation_id) or await self.runner.owned_elsewhere(investigation_id):
            raise ConflictError("investigation is currently executing")
        if inv.status in (InvestigationStatus.COMPLETED.value, InvestigationStatus.CANCELLED.value):
            raise ConflictError(f"investigation is {inv.status}")
        snap = await self._graph.aget_state(thread_config(investigation_id))
        if any(t.interrupts for t in snap.tasks):
            # A decision that was accepted but never delivered (crash) is redelivered instead of stranded.
            pending = await self.dispatcher.pending_for(investigation_id) if self.dispatcher else []
            if pending:
                for cmd in pending:
                    await self.dispatcher.deliver(cmd.id)
                return inv
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

    async def reconcile(self, *, expired_leases_only: bool = False) -> dict[str, int]:
        """Start-up reconciliation of checkpoints, decisions, executions and application rows (audit H3).

        - finished graph, non-terminal row          -> persist the final state (lost final persistence)
        - paused on an interrupt                    -> ensure the action request exists, status awaiting_approval
        - mid-run with an accepted decision pending -> resume from the checkpoint (decision already given)
        - mid-run otherwise                         -> interrupted (operator resumes explicitly)
        then deliver every pending / stale delivery command. Idempotent; safe to run repeatedly.

        Rows whose execution lease is held by another live process are skipped (finding G). The periodic
        sweep passes ``expired_leases_only`` to pick up runs whose owner died after start-up.
        """
        counts: dict[str, int] = {}

        def bump(k: str) -> None:
            counts[k] = counts.get(k, 0) + 1

        async with self._sf() as s:
            rows = list(
                (
                    await s.execute(
                        select(OpsInvestigation).where(
                            OpsInvestigation.status.in_(["queued", "running"])
                            if expired_leases_only
                            else OpsInvestigation.status.in_(ACTIVE_INVESTIGATION_STATUSES),
                            *([OpsInvestigation.run_lease_until < utcnow()] if expired_leases_only else []),
                        )
                    )
                ).scalars()
            )
        for inv in rows:
            if self.runner.is_active(inv.id) or await self.runner.owned_elsewhere(inv.id):
                continue
            try:
                snap = await self._graph.aget_state(thread_config(inv.id))
                interrupts = [i.value for t in snap.tasks for i in (t.interrupts or ())]
                if snap.values and not snap.next:
                    await self.runner.finalize(inv.id)
                    bump("finalized")
                elif interrupts:
                    async with self._sf() as s, s.begin():
                        for value in interrupts:
                            await self.runner._on_interrupt(s, inv.id, inv.incident_id, value)
                    bump("awaiting_approval")
                elif snap.values and self.dispatcher and await self.dispatcher.pending_for(inv.id):
                    self.runner.submit(inv.id, None)
                    bump("resumed")
                elif inv.status in ("running", "queued"):
                    async with self._sf() as s, s.begin():
                        await repo.set_investigation(
                            s,
                            inv.id,
                            status=InvestigationStatus.INTERRUPTED.value,
                            run_owner=None,
                            run_lease_until=None,
                        )
                        await repo.add_event(
                            s, inv.id, "run_interrupted", inv.current_step, {"reason": "process restart"}
                        )
                    bump("interrupted")
            except Exception:
                _log.exception("reconcile_failed", investigation_id=str(inv.id))
                bump("errors")
        if self.dispatcher is not None and not expired_leases_only:
            for k, v in (await self.dispatcher.dispatch_due()).items():
                counts[f"command_{k}"] = v
        if counts:
            _log.info("reconciled", **counts)
        return counts

    async def mark_orphans_interrupted(self) -> int:
        """Deprecated: superseded by ``reconcile`` (kept for compatibility with older callers)."""
        return (await self.reconcile()).get("interrupted", 0)
