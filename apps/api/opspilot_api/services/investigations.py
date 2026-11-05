"""Investigation orchestration: start, background execution, persistence, resume, cancel.

The runner is the single writer of investigation records. It streams the LangGraph run and
persists each node's output (events, tool calls, evidence) as it arrives, so the UI can poll
progress and nothing is lost if the process dies (the checkpoint has the rest).
"""

from __future__ import annotations

import asyncio
import contextlib
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
from opspilot_shared.errors import CapacityError, ConflictError, NotFoundError, OpsPilotError, OwnershipError
from opspilot_shared.logging import get_logger, log_context
from opspilot_shared.redaction import redact
from opspilot_shared.tracing import get_tracer

_log = get_logger(__name__)
_tracer = get_tracer(__name__)


def thread_config(investigation_id: uuid.UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(investigation_id)}, "recursion_limit": 80}


class LeaseLostError(RuntimeError):
    """This process no longer owns the investigation's execution lease; it must stop writing (C0-F2)."""


class TerminalStateError(LeaseLostError):
    """The investigation reached a terminal state (e.g. an operator cancellation committed); the segment must stop
    writing and must never move it back to an active state (C0-G2)."""


class Reservation:
    """One admission slot, taken synchronously and handed to ``submit`` (C0-F2).

    A start reserves its slot *before* it writes anything, so admission is decided once: two concurrent
    starts can no longer both commit a row and then have one refused. An unused reservation must be released."""

    __slots__ = ("_runner", "state")

    def __init__(self, runner: InvestigationRunner) -> None:
        self._runner = runner
        self.state = "held"

    def release(self) -> None:
        if self.state == "held":
            self.state = "released"
            self._runner._reserved -= 1

    def consume(self) -> None:
        if self.state != "held":
            raise RuntimeError(f"admission reservation is {self.state}")
        self.state = "used"
        self._runner._reserved -= 1


class InvestigationRunner:
    """Runs graph segments as bounded background tasks (one per investigation at a time).

    Execution ownership is recorded in the database (audit finding G): before a segment runs, the runner
    claims ``run_owner``/``run_lease_until`` with compare-and-set and renews the lease while it runs. A
    second API process cannot run the same workflow concurrently; a crashed owner's lease simply expires.
    The in-process task registry is only a fast path for this process.

    Lease loss is fenced (C0-F2): when a renewal finds another owner, the segment is cancelled without any
    further application writes, and every persistence transaction re-checks ownership under a row lock, so a
    stale owner that resumes after a takeover cannot overwrite the new owner's (or a cancellation's) state.

    Admission (C0-F2): ``reserve()`` takes a slot synchronously; ``submit(..., reservation=...)`` consumes it
    without a second capacity check. Running tasks plus held reservations never exceed ``max_pending``.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        graph: Any,
        max_concurrency: int,
        *,
        lease_seconds: float = 60.0,
        owner: str | None = None,
        max_pending: int | None = None,
    ) -> None:
        self._sf = session_factory
        self._graph = graph
        self._sem = asyncio.Semaphore(max_concurrency)
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._shutting_down = False
        self.suspended: str | None = None  # C0-G4: execution ownership lost; nothing may run in this process
        self._lease = lease_seconds
        self._max_pending = max_pending if max_pending is not None else max(4, max_concurrency)
        self._reserved = 0
        self._lost: set[uuid.UUID] = set()
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    @property
    def lease_seconds(self) -> float:
        return self._lease

    def is_active(self, investigation_id: uuid.UUID) -> bool:
        t = self._tasks.get(investigation_id)
        return t is not None and not t.done()

    @property
    def pending(self) -> int:
        """Graph segments running or waiting for a concurrency slot, plus reserved admissions, in this process."""
        return sum(1 for t in self._tasks.values() if not t.done()) + self._reserved

    def admit(self) -> None:
        """Raise ``CapacityError`` when the bounded queue is full (C0 item P). Does not reserve."""
        if self.pending >= self._max_pending:
            raise CapacityError(f"{self.pending} investigation segment(s) running or queued; retry shortly")

    def reserve(self) -> Reservation:
        """Check and take an admission slot atomically (no await between the check and the increment)."""
        if self.suspended is not None:
            raise OwnershipError(f"this process no longer owns execution: {self.suspended}")
        if self._shutting_down:
            raise CapacityError("process is shutting down; retry shortly")
        self.admit()
        self._reserved += 1
        return Reservation(self)

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

    async def _heartbeat(self, investigation_id: uuid.UUID, segment: asyncio.Task[Any] | None) -> None:
        """Renew the lease; on loss (or when it cannot be renewed before it expires) stop the segment."""
        loop = asyncio.get_running_loop()
        renewed_at = loop.time()
        while True:
            await asyncio.sleep(self._lease / 3)
            try:
                owned = await self.claim(investigation_id)
            except Exception as exc:  # DB blip: keep trying until the lease would have expired
                _log.warning("run_lease_renewal_failed", investigation_id=str(investigation_id), error=str(exc))
                owned = loop.time() - renewed_at < self._lease
            else:
                if owned:
                    renewed_at = loop.time()
            if not owned:
                _log.error("run_lease_lost", investigation_id=str(investigation_id), owner=self.owner)
                self._lost.add(investigation_id)
                if segment is not None:
                    segment.cancel()
                return

    async def _fence(self, s: AsyncSession, investigation_id: uuid.UUID) -> None:
        """Inside a write transaction: lock the row and verify this process still owns the execution lease."""
        row = (
            await s.execute(
                select(OpsInvestigation.run_owner, OpsInvestigation.status)
                .where(OpsInvestigation.id == investigation_id)
                .with_for_update(key_share=True)
            )
        ).one_or_none()
        owner = row.run_owner if row else None
        if owner != self.owner or investigation_id in self._lost:
            self._lost.add(investigation_id)
            raise LeaseLostError(f"execution lease for {investigation_id} is held by {owner or 'nobody'}")
        if row is not None and InvestigationStatus(row.status).terminal:
            raise TerminalStateError(f"investigation {investigation_id} is {row.status}")

    def submit(
        self,
        investigation_id: uuid.UUID,
        graph_input: Any,
        *,
        on_success: Callable[[uuid.UUID], Awaitable[None]] | None = None,
        command_id: uuid.UUID | None = None,
        expect_action_id: str | None = None,
        reservation: Reservation | None = None,
    ) -> None:
        """Start a graph segment. ``on_success(command_id)`` runs only after the segment's results are persisted.

        ``expect_action_id``: deliver a resume only if, once the lease is held, the workflow is still paused on
        that action (closes the window between the dispatcher's check and execution).

        ``reservation``: an admission slot taken earlier with ``reserve()``; it is consumed here without a second
        capacity check. Without one, a slot is reserved now (and refused with ``CapacityError`` when full).
        On failure the caller's reservation is left held for the caller to release."""
        if self.is_active(investigation_id):
            raise ConflictError("investigation is already executing")
        if self.suspended is not None:
            if reservation is not None:
                reservation.release()
            raise OwnershipError(f"this process no longer owns execution: {self.suspended}")
        slot = reservation if reservation is not None else self.reserve()
        slot.consume()  # synchronous from here to registration: the slot becomes the task
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

    async def suspend(self, reason: str) -> None:
        """Execution ownership was lost (C0-G4): refuse all new work and stop running segments (resumable)."""
        self.suspended = reason
        await self.shutdown()

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

    async def finalize(self, investigation_id: uuid.UUID) -> bool:
        """Persist the final application state of a graph that has already finished (crash recovery).
        Returns False when the row was already terminal (nothing written)."""
        async with self._sf() as s:
            inv = await s.get(OpsInvestigation, investigation_id)
        if inv is None:
            return False
        return await self._finish_segment(investigation_id, inv.incident_id, thread_config(investigation_id))

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
            self._lost.discard(investigation_id)
            segment = asyncio.create_task(
                self._run_owned(investigation_id, graph_input, config, on_success, command_id, expect_action_id),
                name=f"segment-{investigation_id}",
            )
            heartbeat = asyncio.create_task(
                self._heartbeat(investigation_id, segment), name=f"lease-{investigation_id}"
            )
            try:
                await segment  # cancelling this task (operator/shutdown) cancels the segment too
            except asyncio.CancelledError:
                me = asyncio.current_task()
                if (me is not None and me.cancelling()) or investigation_id not in self._lost:
                    raise
                # Stopped because another owner took over: not an operator cancellation, nothing to record.
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                await self.release(investigation_id)  # conditional on ownership: never frees a new owner's lease
                self._lost.discard(investigation_id)

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
        if inv is None or inv.status in (InvestigationStatus.COMPLETED.value, InvestigationStatus.CANCELLED.value):
            return  # a cancelled/completed run is never resumed (e.g. a decision delivered after cancellation)
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
                try:
                    await self._fence(s, investigation_id)
                except TerminalStateError:
                    _log.warning("run_skipped_terminal", investigation_id=str(investigation_id))
                    return
                if not await repo.transition_investigation(
                    s,
                    investigation_id,
                    InvestigationStatus.RUNNING.value,
                    reason="segment_start",
                    started_at=inv.started_at or utcnow(),
                    error=None,
                    error_class=None,
                ):
                    return
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
                    await self._persist(investigation_id, incident_id, mode, chunk, fenced=True)
                await self._finish_segment(investigation_id, incident_id, config, fenced=True)
                if on_success is not None and command_id is not None:
                    await on_success(command_id)
            except asyncio.CancelledError:
                if investigation_id in self._lost:
                    _log.error("run_stopped_lease_lost", investigation_id=str(investigation_id))
                    raise
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
            except LeaseLostError:
                _log.error("run_stopped_lease_lost", investigation_id=str(investigation_id))
            except Exception as exc:
                error_class = exc.error_class if isinstance(exc, OpsPilotError) else type(exc).__name__
                _log.exception("investigation_failed", error_class=error_class)
                await self._mark(investigation_id, InvestigationStatus.FAILED, str(exc)[:2000], error_class)

    async def _mark(
        self, investigation_id: uuid.UUID, status: InvestigationStatus, error: str, error_class: str
    ) -> None:
        async with self._sf() as s, s.begin():
            try:
                await self._fence(s, investigation_id)
            except LeaseLostError:
                _log.error("mark_skipped_lease_lost", investigation_id=str(investigation_id), status=status.value)
                return
            inv = await s.get(OpsInvestigation, investigation_id)
            if not await repo.transition_investigation(
                s,
                investigation_id,
                status.value,
                reason=error_class,
                error=error,
                error_class=error_class,
                completed_at=utcnow() if status.terminal else None,
            ):
                return
            await repo.add_event(
                s, investigation_id, "run_" + status.value, None, {"error": error, "error_class": error_class}
            )
            if inv:
                await repo.set_incident_status(s, inv.incident_id, IncidentStatus.OPEN.value)

    async def _persist(
        self, investigation_id: uuid.UUID, incident_id: uuid.UUID, mode: str, chunk: Any, *, fenced: bool = False
    ) -> None:
        async with self._sf() as s, s.begin():
            if fenced:
                await self._fence(s, investigation_id)
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
        # C0-G2: the status transition is checked (row locked) *before* the request is created. A terminal
        # investigation (e.g. cancelled while a stale checkpoint still shows the interrupt) never gets a new
        # approval request and is never moved back to awaiting_approval.
        if not await repo.transition_investigation(
            s,
            investigation_id,
            InvestigationStatus.AWAITING_APPROVAL.value,
            reason="interrupt",
            current_step="await_approval",
        ):
            await repo.add_event(
                s, investigation_id, "stale_interrupt_ignored", "await_approval", {"action_id": str(action_id)}
            )
            return
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
        self, investigation_id: uuid.UUID, incident_id: uuid.UUID, config: dict[str, Any], *, fenced: bool = False
    ) -> bool:
        snapshot = await self._graph.aget_state(config)
        values = snapshot.values
        if snapshot.next:  # paused (interrupt): status already recorded; expose the RCA for the reviewer
            async with self._sf() as s, s.begin():
                if fenced:
                    await self._fence(s, investigation_id)
                current = await repo.locked_status(s, investigation_id)
                if current is None or InvestigationStatus(current).terminal:
                    return False  # C0-G2: a terminal row is never rewritten from a checkpoint
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
            return True
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
            if fenced:
                await self._fence(s, investigation_id)
            if not await repo.transition_investigation(
                s,
                investigation_id,
                final.value,
                reason="graph_finished",
                completed_at=utcnow(),
                result=result,
                report_markdown=(values.get("report") or {}).get("markdown"),
                current_step=values.get("current_step"),
                error=(errs[-1]["message"] if final is InvestigationStatus.FAILED and errs else None),
                error_class=(errs[-1]["error_class"] if final is InvestigationStatus.FAILED and errs else None),
            ):
                return False  # C0-G2: already terminal (e.g. cancelled); the committed decision stands
            await repo.set_incident_status(s, incident_id, incident_status.value)
            await repo.add_event(
                s,
                investigation_id,
                "run_" + final.value,
                None,
                {"incident_status": incident_status.value, "outcome": outcome},
            )
        return True


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
        self._starting: dict[uuid.UUID, asyncio.Event] = {}

    @staticmethod
    async def _active_for(s: AsyncSession, incident_id: uuid.UUID) -> OpsInvestigation | None:
        return (
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

    async def start(self, incident_id: uuid.UUID) -> OpsInvestigation:
        """Create the incident's single active investigation and dispatch it (audit G, C0 item P, C0-F2).

        Invariants
        - One active investigation per incident: the incident row is locked so concurrent starts serialize, and
          the partial unique index ``uq_ops_investigations_one_active_per_incident`` enforces it even for writers
          that bypass this method. A violation is a 409, never a 500. Duplicate requests are effect-idempotent:
          they never create a second row (in-process duplicates are also single-flighted, so they answer 409
          deterministically instead of competing for admission slots).
        - Atomic admission: an admission slot is reserved synchronously *before* anything is written and is
          handed to ``submit`` without a second check. A refused start writes nothing; a failed transaction
          releases its slot.
        - Durable ownership: the row is created with this process's execution lease. If dispatch fails, or the
          process dies before or after dispatch, the lease expires and the maintenance sweep dispatches the
          queued row again (``reconcile``). No transaction is held open while the graph (model inference) runs.
        """
        while (inflight := self._starting.get(incident_id)) is not None:
            await inflight.wait()
        done = self._starting[incident_id] = asyncio.Event()
        try:
            return await self._start(incident_id)
        finally:
            del self._starting[incident_id]
            done.set()

    async def _start(self, incident_id: uuid.UUID) -> OpsInvestigation:
        async with self._sf() as s:  # read-only: an existing run is a conflict, whatever the capacity
            if active := await self._active_for(s, incident_id):
                raise ConflictError(f"investigation {active.id} is already {active.status} for this incident")
        reservation = self.runner.reserve()  # synchronous check-and-reserve, before any write
        try:
            async with self._sf() as s, s.begin():
                incident = await s.get(OpsIncident, incident_id, with_for_update=True)
                if incident is None:
                    raise NotFoundError(f"incident {incident_id} not found")
                if active := await self._active_for(s, incident_id):
                    raise ConflictError(f"investigation {active.id} is already {active.status} for this incident")
                inv = OpsInvestigation(
                    id=uuid.uuid4(),
                    incident_id=incident_id,
                    status=InvestigationStatus.QUEUED.value,
                    model=self._model,
                    run_owner=self.runner.owner,
                    run_lease_until=utcnow() + timedelta(seconds=self.runner.lease_seconds),
                )
                s.add(inv)
                await s.flush()
                await self._started(s, inv)
        except IntegrityError as exc:
            reservation.release()
            if "uq_ops_investigations_one_active_per_incident" not in str(exc.orig):
                raise
            raise ConflictError("an investigation is already active for this incident") from exc
        except BaseException:
            reservation.release()
            raise
        try:
            self.runner.submit(
                inv.id, {"investigation_id": str(inv.id), "incident_id": str(incident_id)}, reservation=reservation
            )
        except Exception:
            # Accepted and durable, but not running: free the slot and the lease so the sweep re-dispatches it.
            reservation.release()
            _log.exception("dispatch_failed", investigation_id=str(inv.id))
            with contextlib.suppress(Exception):
                await self.runner.release(inv.id)
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
            current = await repo.locked_status(s, investigation_id)
            if current == InvestigationStatus.FAILED.value:
                # The only way out of ``failed``: an explicit operator resume (C0-G2 OPERATOR_ONLY).
                await repo.transition_investigation(
                    s, investigation_id, InvestigationStatus.INTERRUPTED.value, operator=True, reason="operator_resume"
                )
            elif current is None or InvestigationStatus(current).terminal:
                raise ConflictError(f"investigation is {current}")
            await repo.add_event(s, investigation_id, "resume_requested", None, {"from_next": list(snap.next)})
        self.runner.submit(investigation_id, graph_input)
        return inv

    async def cancel(self, investigation_id: uuid.UUID, actor: str) -> OpsInvestigation:
        """Cancel an investigation, revoking requests that have not been claimed for execution.

        The action server's execution claim (``approved -> executing``, under the same row lock) is the
        non-cancellable boundary: once an action is claimed, cancellation is refused and the run completes,
        so its effect is always recorded. Decisions are revoked *before* the task is stopped, in one
        transaction, so an accepted-but-undelivered approval can no longer execute."""
        inv = await self.get(investigation_id)
        if InvestigationStatus(inv.status).terminal:
            raise ConflictError(f"investigation is already {inv.status}")
        async with self._sf() as s, s.begin():
            # C0-G2: lock the investigation row first (the same order every writer uses: investigation, then its
            # actions) and decide on the committed status, not on the snapshot read above.
            current = await repo.locked_status(s, investigation_id)
            if current is None or InvestigationStatus(current).terminal:
                raise ConflictError(f"investigation is already {current}")
            locked = list(
                (
                    await s.execute(
                        select(OpsActionRequest)
                        .where(
                            OpsActionRequest.investigation_id == investigation_id,
                            OpsActionRequest.status.in_(["pending", "approved", "executing"]),
                        )
                        .order_by(OpsActionRequest.id)
                        .with_for_update()
                    )
                ).scalars()
            )
            if executing := [a for a in locked if a.status == "executing"]:
                raise ConflictError(
                    f"action {executing[0].id} is executing; cancellation is not possible past the execution claim"
                )
            for a in locked:
                await repo.transition_action(
                    s, a.id, ("pending", "approved"), status="cancelled", decided_at=utcnow(), decided_by=actor
                )
                await repo.audit(
                    s, actor=actor, action="action.cancelled", entity_type="action_request", entity_id=str(a.id)
                )
            # Outstanding decision deliveries are invalidated in the same transaction: a pending/delivering command
            # can never resume a cancelled workflow (delivery also re-checks, and its claim release is conditional).
            revoked = await repo.revoke_commands(s, investigation_id, reason=f"investigation cancelled by {actor}")
            await repo.transition_investigation(
                s,
                investigation_id,
                InvestigationStatus.CANCELLED.value,
                reason="operator_cancel",
                completed_at=utcnow(),
            )
            await repo.set_incident_status(s, inv.incident_id, IncidentStatus.OPEN.value)
            await repo.add_event(s, investigation_id, "run_cancelled", None, {"by": actor, "commands_revoked": revoked})
        await self.runner.cancel(investigation_id)
        return await self.get(investigation_id)

    async def reconcile(self, *, expired_leases_only: bool = False) -> dict[str, int]:
        """Start-up reconciliation of checkpoints, decisions, executions and application rows (audit H3).

        - finished graph, non-terminal row          -> persist the final state (lost final persistence)
        - paused on an interrupt                    -> ensure the action request exists, status awaiting_approval
        - mid-run with an accepted decision pending -> resume from the checkpoint (decision already given)
        - mid-run otherwise                         -> interrupted (operator resumes explicitly)
        then deliver every pending / stale delivery command. Idempotent; safe to run repeatedly.

        Rows whose execution lease is held by another live process are skipped (finding G). The periodic
        sweep passes ``expired_leases_only`` to pick up runs whose owner died after start-up, and rows that have
        no lease at all (C0-F2: e.g. accepted work whose dispatch failed).

        Accepted work that never started (``queued`` with no checkpoint) is dispatched again rather than
        interrupted; when admission is full it stays queued and is retried by the next sweep (``deferred``).
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
                            *(
                                [
                                    or_(
                                        OpsInvestigation.run_lease_until.is_(None),
                                        OpsInvestigation.run_lease_until < utcnow(),
                                    )
                                ]
                                if expired_leases_only
                                else []
                            ),
                        )
                    )
                ).scalars()
            )
        for inv in rows:
            if self.runner.is_active(inv.id) or await self.runner.owned_elsewhere(inv.id):
                continue
            # Every write below is a locked compare-and-set against the transition policy (C0-G2), so a cancellation
            # that commits after this row was selected (or after the checkpoint is read) always wins.
            try:
                snap = await self._graph.aget_state(thread_config(inv.id))
                interrupts = [i.value for t in snap.tasks for i in (t.interrupts or ())]
                if snap.values and not snap.next:
                    bump("finalized" if await self.runner.finalize(inv.id) else "skipped_terminal")
                elif interrupts:
                    async with self._sf() as s, s.begin():
                        for value in interrupts:
                            await self.runner._on_interrupt(s, inv.id, inv.incident_id, value)
                        restored = await repo.locked_status(s, inv.id) == InvestigationStatus.AWAITING_APPROVAL.value
                    bump("awaiting_approval" if restored else "skipped_terminal")
                elif snap.values and self.dispatcher and await self.dispatcher.pending_for(inv.id):
                    self.runner.submit(inv.id, None)
                    bump("resumed")
                elif not snap.values and inv.status == InvestigationStatus.QUEUED.value:
                    try:  # accepted but never started: dispatch it (the run claims the expired/absent lease)
                        self.runner.submit(
                            inv.id, {"investigation_id": str(inv.id), "incident_id": str(inv.incident_id)}
                        )
                    except CapacityError:
                        bump("deferred")
                    else:
                        bump("dispatched")
                elif inv.status in ("running", "queued"):
                    async with self._sf() as s, s.begin():
                        current = await repo.locked_status(s, inv.id)
                        moved = current in ("running", "queued") and await repo.transition_investigation(
                            s,
                            inv.id,
                            InvestigationStatus.INTERRUPTED.value,
                            reason="reconcile_abandoned",
                            run_owner=None,
                            run_lease_until=None,
                        )
                        if moved:
                            await repo.add_event(
                                s, inv.id, "run_interrupted", inv.current_step, {"reason": "process restart"}
                            )
                    bump("interrupted" if moved else "skipped_terminal")
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
