"""Approval requests expire: late decisions are refused and the run ends accurately without side effects."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update

from opspilot_api.main import create_app
from opspilot_shared.db.models import OpsActionRequest, SimActionExecution
from tests.fakes.models import ScriptedChatModel
from tests.integration.helpers import inprocess_gateways

pytestmark = pytest.mark.integration


@pytest.fixture
async def stack(settings, session_factory, embedder, ingested) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:  # type: ignore[no-untyped-def]
    app = create_app(
        settings,
        chat=ScriptedChatModel(),
        embedder=embedder,
        gateways=inprocess_gateways(settings, session_factory, embedder),
    )
    started, stop = asyncio.Event(), asyncio.Event()

    async def host() -> None:
        async with app.router.lifespan_context(app):
            started.set()
            await stop.wait()

    task = asyncio.create_task(host())
    await asyncio.wait_for(started.wait(), 30)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c, app.state.runtime
    finally:
        stop.set()
        await task


async def poll(c: httpx.AsyncClient, inv: str, until: set[str]) -> dict[str, Any]:
    for _ in range(300):
        body = (await c.get(f"/api/v1/investigations/{inv}")).json()
        if body["status"] in until and not body["executing_in_process"]:
            return body  # type: ignore[no-any-return]
        await asyncio.sleep(0.2)
    raise AssertionError(f"timeout waiting for {until}")


async def paused_action(c: httpx.AsyncClient) -> tuple[str, dict[str, Any]]:
    inc = (await c.post("/api/v1/incidents/simulate", json={"scenario": "INC-001"})).json()
    inv = (await c.post(f"/api/v1/incidents/{inc['id']}/investigations")).json()["investigation_id"]
    await poll(c, inv, {"awaiting_approval"})
    [action] = (await c.get(f"/api/v1/investigations/{inv}/actions")).json()
    return inv, action


async def age(session_factory, action_id: str, seconds: int) -> None:  # type: ignore[no-untyped-def]
    async with session_factory() as s, s.begin():
        row = await s.get(OpsActionRequest, uuid.UUID(action_id))
        await s.execute(
            update(OpsActionRequest)
            .where(OpsActionRequest.id == row.id)
            .values(requested_at=row.requested_at - timedelta(seconds=seconds))
        )


async def executions(session_factory, action_id: str) -> int:  # type: ignore[no-untyped-def]
    async with session_factory() as s:
        return int(
            (
                await s.execute(
                    select(func.count())
                    .select_from(SimActionExecution)
                    .where(SimActionExecution.action_id == uuid.UUID(action_id))
                )
            ).scalar_one()
        )


async def test_late_decision_is_refused_and_run_ends_expired(stack, settings, session_factory) -> None:  # type: ignore[no-untyped-def]
    c, _ = stack
    inv, action = await paused_action(c)
    await age(session_factory, action["id"], settings.approval_request_ttl_seconds + 60)
    r = await c.post(
        f"/api/v1/approvals/{action['id']}/decision",
        headers={"Authorization": f"Bearer {settings.operator_token.get_secret_value()}"},
        json={"decision": "approve", "params_hash": action["params_hash"], "decided_by": "late-sre"},
    )
    assert r.status_code == 409 and "expired" in r.json()["error"]["message"]
    done = await poll(c, inv, {"completed", "failed"})
    assert done["status"] == "completed" and done["result"]["outcome"]["code"] == "approval_expired"
    assert done["result"]["outcome"]["escalate"] is True
    assert (await c.get(f"/api/v1/approvals/{action['id']}")).json()["status"] == "expired"
    assert await executions(session_factory, action["id"]) == 0


async def test_sweeper_expires_untouched_requests(stack, settings, session_factory) -> None:  # type: ignore[no-untyped-def]
    c, rt = stack
    inv, action = await paused_action(c)
    await age(session_factory, action["id"], settings.approval_request_ttl_seconds + 60)
    assert await rt.approvals.expire_stale() >= 1
    assert await rt.approvals.expire_stale() == 0  # idempotent: nothing left to expire
    done = await poll(c, inv, {"completed", "failed"})
    assert done["result"]["outcome"]["code"] == "approval_expired"
    assert await executions(session_factory, action["id"]) == 0
