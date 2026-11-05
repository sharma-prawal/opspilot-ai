"""Audit finding E: approval tokens (and other credentials) must never appear in any output record.

The real API runs an INC-001 investigation through approval and sandbox execution. Every approval token
the dispatcher mints is captured, then every non-checkpoint table, every read endpoint and the structured
log output are searched for the exact token value and for its signature segment.

Checkpoint history is the one documented exception: LangGraph stores the resume value of the approval
step, so earlier checkpoints retain the short-lived, action-bound token. The *latest* state must not.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import structlog
from sqlalchemy import text

from opspilot_api.main import create_app
from opspilot_api.services import commands
from opspilot_api.services.investigations import thread_config
from opspilot_shared import logging as logmod
from opspilot_shared.redaction import REDACTED, contains_secret, redact
from tests.fakes.models import ScriptedChatModel
from tests.integration.helpers import inprocess_gateways

CHECKPOINT_TABLES = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}


def test_policy_redacts_nested_credentials_and_keeps_counters() -> None:
    value = {
        "approval_token": "abc.def",
        "nested": [{"Authorization": "Bearer x"}, {"operator_token": "t", "prompt_tokens": 12}],
        "session_secret": "s",
        "empty_token": None,
        "service": "ledger-service",
    }
    out = redact(value)
    assert out["approval_token"] == REDACTED and out["session_secret"] == REDACTED
    assert out["nested"][0]["Authorization"] == REDACTED and out["nested"][1]["operator_token"] == REDACTED
    assert out["nested"][1]["prompt_tokens"] == 12 and out["service"] == "ledger-service"
    assert out["empty_token"] is None
    assert contains_secret(value) and not contains_secret(out)
    assert value["approval_token"] == "abc.def"  # input is not mutated


def test_structured_logs_redact_sensitive_fields(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = logging.getLogger()
    saved_handlers, saved_level, saved_cfg = root.handlers[:], root.level, structlog.get_config()
    monkeypatch.setattr(logmod, "_CONFIGURED", False)
    try:
        logmod.configure_logging("INFO", "json")
        logmod.get_logger("redaction-test").info("decision", approval_token="sentinel-AAAA.BBBB", actor="sre")
        err = capsys.readouterr().err
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
        structlog.configure(**saved_cfg)
    assert "sentinel-AAAA.BBBB" not in err
    line = json.loads(err.strip().splitlines()[-1])
    assert line["approval_token"] == REDACTED and line["actor"] == "sre"


@pytest.fixture
async def stack(settings, session_factory, embedder, ingested) -> AsyncIterator[tuple[Any, httpx.AsyncClient]]:  # type: ignore[no-untyped-def]
    app = create_app(
        settings,
        chat=ScriptedChatModel(),
        gateways=inprocess_gateways(settings, session_factory, embedder),
        embedder=embedder,
    )
    started, stop = asyncio.Event(), asyncio.Event()

    async def host() -> None:
        async with app.router.lifespan_context(app):
            started.set()
            await stop.wait()

    task = asyncio.create_task(host())
    await asyncio.wait_for(started.wait(), 30)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {settings.operator_token.get_secret_value()}"},
        ) as c:
            yield app, c
    finally:
        stop.set()
        await task


async def poll(c: httpx.AsyncClient, inv: str, until: set[str]) -> dict[str, Any]:
    for _ in range(300):
        body = (await c.get(f"/api/v1/investigations/{inv}")).json()
        if body["status"] in until and not body["executing_in_process"]:
            return body
        await asyncio.sleep(0.2)
    raise AssertionError(f"timeout waiting for {until}")


@pytest.mark.integration
async def test_minted_approval_token_never_appears_in_outputs(  # type: ignore[no-untyped-def]
    stack, session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client = stack
    minted: list[str] = []
    real_issue = commands.issue_token

    def capture(*args: Any, **kwargs: Any) -> str:
        tok = real_issue(*args, **kwargs)
        minted.append(tok)
        return tok

    monkeypatch.setattr(commands, "issue_token", capture)

    inc = (await client.post("/api/v1/incidents/simulate", json={"scenario": "INC-001"})).json()
    inv = (await client.post(f"/api/v1/incidents/{inc['id']}/investigations")).json()["investigation_id"]
    await poll(client, inv, {"awaiting_approval"})
    [action] = [a for a in (await client.get("/api/v1/approvals")).json() if a["investigation_id"] == inv]
    body = {"decision": "approve", "params_hash": action["params_hash"], "decided_by": "sre"}
    assert (await client.post(f"/api/v1/approvals/{action['id']}/decision", json=body)).status_code == 200
    done = await poll(client, inv, {"completed", "failed"})
    assert done["status"] == "completed", done
    assert minted, "the dispatcher should have minted an approval token"
    needles = {n for tok in minted for n in (tok, tok.split(".")[-1])}  # whole token and its signature

    # 1. Every read endpoint for this investigation.
    paths = [
        f"/api/v1/investigations/{inv}",
        f"/api/v1/investigations/{inv}/events",
        f"/api/v1/investigations/{inv}/tool-calls",
        f"/api/v1/investigations/{inv}/evidence",
        f"/api/v1/investigations/{inv}/actions",
        f"/api/v1/investigations/{inv}/report",
        f"/api/v1/investigations/{inv}/workflow",
        f"/api/v1/approvals/{action['id']}",
        "/api/v1/approvals",
        f"/api/v1/incidents/{inc['id']}",
    ]
    for p in paths:
        r = await client.get(p)
        assert r.status_code == 200, p
        assert not any(n in r.text for n in needles), f"token leaked via GET {p}"
    calls = (await client.get(f"/api/v1/investigations/{inv}/tool-calls")).json()
    [execute] = [c for c in calls if c["tool"] == "execute_remediation"]
    assert execute["arguments"]["approval_token"] == REDACTED

    # 2. Every persisted table except LangGraph checkpoint history.
    async with session_factory() as s:
        tables = (
            await s.execute(
                text(
                    "select table_schema, table_name from information_schema.tables "
                    "where table_type = 'BASE TABLE' and table_schema not in ('pg_catalog', 'information_schema')"
                )
            )
        ).all()
        scanned = 0
        for schema, table in tables:
            if table in CHECKPOINT_TABLES:
                continue
            for n in needles:
                hits = (
                    await s.execute(
                        text(f'select count(*) from "{schema}"."{table}" t where row_to_json(t)::text like :pat'),
                        {"pat": f"%{n}%"},
                    )
                ).scalar_one()
                assert hits == 0, f"token persisted in {schema}.{table}"
            scanned += 1
        assert scanned >= 10

    # 3. The latest checkpointed state no longer carries the spent token.
    snap = await app.state.runtime.graph.aget_state(thread_config(uuid.UUID(inv)))
    assert snap.values["approval"]["approval_token"] is None


@pytest.mark.integration
async def test_sanitizer_dry_run_counts_and_apply_redacts_legacy_rows(session_factory) -> None:  # type: ignore[no-untyped-def]
    """Rows written before the fix (verbatim token) are counted by the dry run and redacted only by --apply."""
    from datetime import UTC, datetime

    from opspilot_api.services.sanitize import sanitize_secrets
    from opspilot_shared.db.models import OpsActionRequest, OpsToolInvocation
    from tests.integration.helpers import make_action

    act_id, _, _ = await make_action(session_factory, status="pending")
    async with session_factory() as s:
        act = await s.get(OpsActionRequest, act_id)
        assert act is not None
        inv_id = act.investigation_id
    sentinel = "legacy-SENTINEL-" + uuid.uuid4().hex
    call_id = "tc-" + uuid.uuid4().hex[:20]
    async with session_factory() as s, s.begin():
        s.add(
            OpsToolInvocation(
                id=call_id,
                investigation_id=inv_id,
                tool="execute_remediation",
                server="actions",
                agent="remediation",
                arguments={"action_id": "a-1", "approval_token": sentinel},
                status="ok",
                latency_ms=1.0,
                started_at=datetime.now(UTC),
            )
        )

    async def stored() -> dict[str, Any]:
        async with session_factory() as s:
            row = await s.get(OpsToolInvocation, call_id)
            assert row is not None
            return dict(row.arguments)

    dry = await sanitize_secrets(session_factory)
    assert dry["mode"] == "dry-run" and dry["json_rows_with_secrets"]["ops.tool_invocations.arguments"] >= 1
    assert sentinel not in json.dumps(dry)  # reports counts, never values
    assert (await stored())["approval_token"] == sentinel  # dry run changes nothing

    applied = await sanitize_secrets(session_factory, apply=True)
    assert applied["redacted"] >= 1 and sentinel not in json.dumps(applied)
    assert await stored() == {"action_id": "a-1", "approval_token": REDACTED}  # only the value changed

    again = await sanitize_secrets(session_factory)
    assert again["json_rows_with_secrets"]["ops.tool_invocations.arguments"] == 0
