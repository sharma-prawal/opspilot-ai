"""Approval decisions. All enforcement happens here (backend), never only in the UI.

Checks, in order: action exists and is ``pending``; submitted params_hash equals the stored hash
and the hash recomputed from the stored parameters; the investigation is paused on *this* action
in the checkpoint; then a compare-and-set status transition (race/replay safe). Only then is a
signed, expiring approval token issued and the workflow resumed.
"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opspilot_api import repositories as repo
from opspilot_api.services.investigations import InvestigationRunner, thread_config
from opspilot_shared.approvals import action_params_hash, issue_token
from opspilot_shared.config import Settings
from opspilot_shared.db.models import OpsActionRequest
from opspilot_shared.domain.actions import ApprovalDecisionKind
from opspilot_shared.domain.common import utcnow
from opspilot_shared.errors import ApprovalError, ConflictError, NotFoundError
from opspilot_shared.logging import get_logger

_log = get_logger(__name__)


class ApprovalService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        runner: InvestigationRunner,
        graph: Any,
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._runner = runner
        self._graph = graph
        self._s = settings

    async def list(self, status: str | None = "pending") -> list[OpsActionRequest]:
        stmt = select(OpsActionRequest).order_by(OpsActionRequest.requested_at.desc()).limit(100)
        if status:
            stmt = stmt.where(OpsActionRequest.status == status)
        async with self._sf() as s:
            return list((await s.execute(stmt)).scalars())

    async def get(self, action_id: uuid.UUID) -> OpsActionRequest:
        async with self._sf() as s:
            row = await s.get(OpsActionRequest, action_id)
        if row is None:
            raise NotFoundError(f"action {action_id} not found")
        return row

    async def decide(
        self,
        action_id: uuid.UUID,
        *,
        decision: ApprovalDecisionKind,
        params_hash: str,
        decided_by: str,
        comment: str | None,
    ) -> OpsActionRequest:
        row = await self.get(action_id)
        if row.status != "pending":
            raise ConflictError(f"action is {row.status}; only pending actions can be decided")
        if params_hash != row.params_hash or row.params_hash != action_params_hash(row.action_type, row.parameters):
            await self._audit(decided_by, "action.decision_rejected", action_id, {"reason": "params_hash mismatch"})
            raise ApprovalError("params_hash does not match the proposed action; refresh and review again")

        snap = await self._graph.aget_state(thread_config(row.investigation_id))
        pending = [i.value for t in snap.tasks for i in (t.interrupts or ())]
        if not any(p.get("action", {}).get("action_id") == str(action_id) for p in pending):
            raise ConflictError("the workflow is not paused on this action")
        if self._runner.is_active(row.investigation_id):
            raise ConflictError("workflow is currently executing")

        decided_at = utcnow()
        new_status = "approved" if decision is ApprovalDecisionKind.APPROVE else "rejected"
        async with self._sf() as s, s.begin():
            if not await repo.transition_action(
                s,
                action_id,
                ("pending",),
                status=new_status,
                decided_at=decided_at,
                decided_by=decided_by,
                decision_comment=comment,
            ):
                raise ConflictError("action was decided concurrently")
            await repo.audit(
                s,
                actor=decided_by,
                action=f"action.{new_status}",
                entity_type="action_request",
                entity_id=str(action_id),
                details={
                    "comment": comment,
                    "params_hash": params_hash,
                    "action_type": row.action_type,
                    "parameters": row.parameters,
                },
            )
            await repo.add_event(
                s,
                row.investigation_id,
                "approval_decided",
                "await_approval",
                {"action_id": str(action_id), "decision": decision.value, "decided_by": decided_by},
            )

        resume: dict[str, Any] = {
            "action_id": str(action_id),
            "params_hash": row.params_hash,
            "decision": decision.value,
            "decided_by": decided_by,
            "comment": comment,
            "decided_at": decided_at.isoformat(),
        }
        if decision is ApprovalDecisionKind.APPROVE:
            resume["approval_token"] = issue_token(
                self._s.action_signing_key.get_secret_value(),
                action_id=action_id,
                params_hash=row.params_hash,
                approved_by=decided_by,
                ttl_seconds=self._s.approval_token_ttl_seconds,
            )
        self._runner.submit(row.investigation_id, Command(resume=resume))
        _log.info("approval_decided", action_id=str(action_id), decision=decision.value, decided_by=decided_by)
        return await self.get(action_id)

    async def _audit(self, actor: str, action: str, action_id: uuid.UUID, details: dict[str, Any]) -> None:
        async with self._sf() as s, s.begin():
            await repo.audit(
                s, actor=actor, action=action, entity_type="action_request", entity_id=str(action_id), details=details
            )
