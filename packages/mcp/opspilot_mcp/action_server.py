"""MCP **action** server: approval-gated sandbox remediation.

Defence in depth — this server does not trust its caller. Before executing it:
1. verifies the HMAC approval token (signature, expiry) and that it names this action_id;
2. loads the persisted action request and requires status ``approved`` and a matching params hash;
3. **claims** the action (``approved -> executing``) under a row lock, in its own committed transaction.
   The claim is the non-cancellable boundary (audit suspected risk / finding H): cancellation takes the same
   row lock and revokes only ``pending``/``approved`` requests, so either the cancel wins and execution is
   refused, or the claim wins and the cancel is refused. ``executing`` is re-entrant so a crash between claim
   and effect can be retried with the same token;
4. executes with the *persisted* parameters (the caller cannot supply parameters at all);
5. relies on the simulator's per-action idempotency ledger so replays never re-execute.

The claim is the only write this server makes outside the ``sim`` schema (ops.action_requests.status).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy import select

from opspilot_mcp.backend import OpsBackend
from opspilot_mcp.schemas import ExecutionOutcome
from opspilot_shared.approvals import action_params_hash, verify_token
from opspilot_shared.db.models import OpsActionRequest, SimActionExecution
from opspilot_shared.domain.actions import REMEDIATION_CATALOG, ActionType
from opspilot_shared.errors import OpsPilotError
from opspilot_shared.logging import get_logger

_log = get_logger(__name__)
ACTION_TOOLS = frozenset({"execute_remediation", "get_action_execution"})
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)


def _outcome(row: SimActionExecution, *, replayed: bool) -> ExecutionOutcome:
    return ExecutionOutcome(
        action_id=row.action_id,
        action_type=row.action_type,
        status=row.status,
        message=row.message,
        replayed=replayed,
        executed_at=row.executed_at,
        details=row.details,
    )


def build_action_server(backend: OpsBackend) -> MCPServer:
    mcp = MCPServer(
        "opspilot-ops-actions",
        version="0.1.0",
        instructions=(
            "Sandbox remediation. Every call requires an operator approval token issued by the OpsPilot API."
        ),
    )
    key = backend.settings.action_signing_key.get_secret_value()

    @mcp.tool(title="Execute approved remediation", annotations=WRITE)
    async def execute_remediation(
        action_id: uuid.UUID, approval_token: Annotated[str, Field(min_length=20, max_length=2000)]
    ) -> ExecutionOutcome:
        """Execute a previously approved remediation action in the sandbox environment."""
        try:
            # Signature always required. Expiry is enforced below, after the ledger lookup, so a crash-recovered
            # workflow can learn the result of an action that already executed (audit suspected risk).
            claims = verify_token(key, approval_token, allow_expired=True)
        except OpsPilotError as exc:
            _log.warning("action_rejected", action_id=str(action_id), reason=str(exc))
            raise ToolError(f"approval: {exc}") from exc
        if claims.action_id != action_id:
            raise ToolError("approval: token was issued for a different action")
        async with backend.session_factory() as s:
            req = await s.get(OpsActionRequest, action_id)
            prior = await s.get(SimActionExecution, action_id)
        if req is None:
            raise ToolError("approval: no persisted action request")
        if prior is not None:
            return _outcome(prior, replayed=True)
        if claims.expired:
            raise ToolError("approval: approval token expired")
        computed = action_params_hash(req.action_type, req.parameters)
        if not (req.params_hash == claims.params_hash == computed):
            raise ToolError("approval: parameters do not match the approved parameters")
        spec = REMEDIATION_CATALOG.get(ActionType(req.action_type))
        if spec is None or not spec.implemented:
            raise ToolError(f"unsupported action type {req.action_type!r}")
        # Execution claim: authorisation is re-read under a row lock and committed before any effect.
        async with backend.session_factory() as s, s.begin():
            locked = (
                await s.execute(select(OpsActionRequest).where(OpsActionRequest.id == action_id).with_for_update())
            ).scalar_one()
            if locked.status not in ("approved", "executing"):
                raise ToolError(f"approval: action status is {locked.status!r}, not 'approved'")
            locked.status = "executing"
        _log.info("action_claimed", action_id=str(action_id))
        try:
            row = await backend.store.execute_action(
                req.environment_id,
                action_id=action_id,
                action_type=req.action_type,
                parameters=req.parameters,
                params_hash=computed,
            )
        except OpsPilotError as exc:
            raise ToolError(f"{exc.error_class}: {exc}") from exc
        _log.info(
            "action_executed",
            action_id=str(action_id),
            action_type=req.action_type,
            status=row.status,
            approved_by=claims.approved_by,
        )
        return _outcome(row, replayed=False)

    @mcp.tool(title="Get action execution", annotations=ToolAnnotations(read_only_hint=True))
    async def get_action_execution(action_id: uuid.UUID) -> ExecutionOutcome:
        """Execution record for an action, if it has been executed."""
        async with backend.session_factory() as s:
            row = await s.get(SimActionExecution, action_id)
        if row is None:
            raise ToolError("not_found: action has not been executed")
        return _outcome(row, replayed=True)

    return mcp
