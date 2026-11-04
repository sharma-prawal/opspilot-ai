"""The action server must refuse anything that is not an exactly-approved, signed action."""

import uuid

import pytest
from mcp import Client
from sqlalchemy import func, select

from opspilot_mcp.action_server import build_action_server
from opspilot_shared.approvals import issue_token
from opspilot_shared.db.models import SimActionExecution
from tests.integration.helpers import backend, make_action

pytestmark = pytest.mark.integration


def token(settings, aid, ph, ttl=60):  # type: ignore[no-untyped-def]
    return issue_token(
        settings.action_signing_key.get_secret_value(),
        action_id=aid,
        params_hash=ph,
        approved_by="tester",
        ttl_seconds=ttl,
    )


async def executions(sf, aid) -> int:  # type: ignore[no-untyped-def]
    async with sf() as s:
        return (
            await s.execute(
                select(func.count()).select_from(SimActionExecution).where(SimActionExecution.action_id == aid)
            )
        ).scalar_one()


async def test_pending_action_cannot_execute_even_with_valid_token(settings, session_factory, embedder) -> None:  # type: ignore[no-untyped-def]
    aid, ph, _ = await make_action(session_factory, status="pending")
    async with Client(build_action_server(backend(settings, session_factory, embedder))) as c:
        res = await c.call_tool(
            "execute_remediation", {"action_id": str(aid), "approval_token": token(settings, aid, ph)}
        )
    assert res.is_error and "not 'approved'" in res.content[0].text
    assert await executions(session_factory, aid) == 0


@pytest.mark.parametrize("case", ["forged", "other_action", "wrong_hash", "expired"])
async def test_bad_tokens_refused(case, settings, session_factory, embedder) -> None:  # type: ignore[no-untyped-def]
    aid, ph, _ = await make_action(session_factory, status="approved")
    tok = {
        "forged": issue_token("x" * 32, action_id=aid, params_hash=ph, approved_by="evil", ttl_seconds=60),
        "other_action": token(settings, uuid.uuid4(), ph),
        "wrong_hash": token(settings, aid, "0" * 64),
        "expired": issue_token(
            settings.action_signing_key.get_secret_value(),
            action_id=aid,
            params_hash=ph,
            approved_by="t",
            ttl_seconds=30,
            now=0,
        ),
    }[case]
    async with Client(build_action_server(backend(settings, session_factory, embedder))) as c:
        res = await c.call_tool("execute_remediation", {"action_id": str(aid), "approval_token": tok})
    assert res.is_error and "approval:" in res.content[0].text
    assert await executions(session_factory, aid) == 0


async def test_approved_action_executes_once_and_replays_idempotently(settings, session_factory, embedder) -> None:  # type: ignore[no-untyped-def]
    aid, ph, env = await make_action(session_factory, status="approved")
    b = backend(settings, session_factory, embedder)
    async with Client(build_action_server(b)) as c:
        first = await c.call_tool(
            "execute_remediation", {"action_id": str(aid), "approval_token": token(settings, aid, ph)}
        )
        second = await c.call_tool(
            "execute_remediation", {"action_id": str(aid), "approval_token": token(settings, aid, ph)}
        )
    assert not first.is_error and first.structured_content["status"] == "succeeded"
    assert first.structured_content["replayed"] is False and second.structured_content["replayed"] is True
    assert await executions(session_factory, aid) == 1
    health = await b.store.service_health(env, "ledger-service")
    assert health.status.value == "healthy"  # sandbox actually recovered


async def test_parameters_come_from_persisted_request_not_caller(settings, session_factory, embedder) -> None:  # type: ignore[no-untyped-def]
    """The tool has no parameter argument at all: callers cannot smuggle different parameters."""
    async with Client(build_action_server(backend(settings, session_factory, embedder))) as c:
        tool = {t.name: t for t in (await c.list_tools()).tools}["execute_remediation"]
    assert set(tool.input_schema["properties"]) == {"action_id", "approval_token"}
