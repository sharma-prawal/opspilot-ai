"""Sandbox semantics of INC-002 / INC-003 / NEG-003, exercised through the simulator store and MCP."""

import uuid

import pytest
from mcp import Client
from sqlalchemy import func, select

from opspilot_mcp.read_server import build_read_server
from opspilot_shared.approvals import action_params_hash
from opspilot_shared.db.models import SimQueueMessage
from opspilot_simulator.store import SimulatorStore
from tests.integration.helpers import backend

pytestmark = pytest.mark.integration


async def act(store: SimulatorStore, env: uuid.UUID, action: str, params: dict) -> str:  # type: ignore[type-arg]
    row = await store.execute_action(
        env,
        action_id=uuid.uuid4(),
        action_type=action,
        parameters=params,
        params_hash=action_params_hash(action, params),
    )
    return row.status


async def test_inc002_pool_increase_is_capacity_bound_and_not_a_fix(session_factory) -> None:  # type: ignore[no-untyped-def]
    store = SimulatorStore(session_factory)
    env, _ = await store.create_environment("INC-002")
    ds = await store.datastore_status(env, "ledger-db")
    assert ds["connections_active"] / ds["max_connections"] > 0.9 and ds["long_running_queries"]
    assert (
        await act(store, env, "scale_connection_pool", {"service": "ledger-service", "max_connections": 60}) == "failed"
    )
    assert (
        await act(store, env, "scale_connection_pool", {"service": "ledger-service", "max_connections": 44})
        == "succeeded"
    )
    assert (await store.service_config(env, "ledger-service"))["config"]["db.pool.max"] == 44
    assert (await store.service_health(env, "transaction-api")).status.value == "unhealthy"  # still broken
    assert (
        await act(store, env, "rollback_deployment", {"service": "ledger-service", "deployment_id": "dep-ls-0291"})
        == "succeeded"
    )
    assert (await store.service_health(env, "transaction-api")).status.value == "healthy"
    assert not (await store.datastore_status(env, "ledger-db"))["long_running_queries"]


async def _rows(session_factory, env: uuid.UUID) -> dict[str, int]:  # type: ignore[no-untyped-def]
    async with session_factory() as s:
        return dict(
            (
                await s.execute(
                    select(SimQueueMessage.status, func.count())
                    .where(SimQueueMessage.environment_id == env)
                    .group_by(SimQueueMessage.status)
                )
            ).all()
        )


async def _ids(session_factory, env: uuid.UUID) -> set[str]:  # type: ignore[no-untyped-def]
    async with session_factory() as s:
        return set(
            (await s.execute(select(SimQueueMessage.message_id).where(SimQueueMessage.environment_id == env))).scalars()
        )


async def test_inc003_containment_alone_does_not_recover(session_factory) -> None:  # type: ignore[no-untyped-def]
    store = SimulatorStore(session_factory)
    env, _ = await store.create_environment("INC-003")
    q = await store.inspect_queue(env, "settlement-events")
    assert q["dead_lettered"] > 1000 and q["failures"][0]["error_code"] == "SETTLEMENT_SCHEMA_INVALID"
    assert q["failures"][0]["producer_version"] == "3.18.0"
    assert await act(store, env, "resume_consumer", {"service": "settlement-worker"}) == "failed"  # not paused
    assert await act(store, env, "pause_consumer", {"service": "settlement-worker"}) == "succeeded"
    assert (await store.inspect_queue(env, "settlement-events"))["consumer"]["state"] == "paused"
    # Quarantine while the producer is still bad, then resume: poison keeps arriving.
    assert (
        await act(
            store, env, "quarantine_messages", {"queue": "settlement-events", "error_code": "SETTLEMENT_SCHEMA_INVALID"}
        )
        == "succeeded"
    )
    assert await act(store, env, "resume_consumer", {"service": "settlement-worker"}) == "succeeded"
    env_row = await store.environment(env)
    series = await store.query_metrics(
        env,
        service="settlement-worker",
        metric="validation_failures_per_min",
        start=env_row.sim_now.replace(minute=env_row.sim_now.minute - 5),
        end=env_row.sim_now,
    )
    assert sum(p.value for p in series.points) > 0


async def test_inc003_full_plan_recovers_and_preserves_messages(session_factory) -> None:  # type: ignore[no-untyped-def]
    store = SimulatorStore(session_factory)
    env, _ = await store.create_environment("INC-003")
    before = await _rows(session_factory, env)
    ids_before = await _ids(session_factory, env)
    for action, params in [
        ("pause_consumer", {"service": "settlement-worker"}),
        ("rollback_deployment", {"service": "transaction-api", "deployment_id": "dep-ta-3180"}),
        ("quarantine_messages", {"queue": "settlement-events", "error_code": "SETTLEMENT_SCHEMA_INVALID"}),
        ("resume_consumer", {"service": "settlement-worker"}),
    ]:
        assert await act(store, env, action, params) == "succeeded", action
    after = await _rows(session_factory, env)
    q = await store.inspect_queue(env, "settlement-events")
    assert q["dead_lettered"] == 0 and q["quarantined"] >= before.get("dead_lettered", 0) and not q["failures"]
    assert ids_before <= await _ids(session_factory, env)  # quarantine moves records, never deletes them
    assert after.get("quarantined", 0) >= before.get("dead_lettered", 0)
    env_row = await store.environment(env)
    series = await store.query_metrics(
        env,
        service="settlement-worker",
        metric="validation_failures_per_min",
        start=env_row.sim_now.replace(minute=env_row.sim_now.minute - 5),
        end=env_row.sim_now,
    )
    assert sum(p.value for p in series.points) == 0


async def test_neg003_log_backend_outage_surfaces_as_tool_error(settings, session_factory, embedder) -> None:  # type: ignore[no-untyped-def]
    store = SimulatorStore(session_factory)
    env, _ = await store.create_environment("NEG-003")
    async with Client(build_read_server(backend(settings, session_factory, embedder))) as c:
        bad = await c.call_tool(
            "search_logs",
            {
                "environment_id": str(env),
                "service": "ledger-service",
                "start": "2026-11-03T13:00:00+00:00",
                "end": "2026-11-03T14:30:00+00:00",
            },
        )
        ok = await c.call_tool(
            "search_logs",
            {
                "environment_id": str(env),
                "service": "transaction-api",
                "start": "2026-11-03T13:00:00+00:00",
                "end": "2026-11-03T14:30:00+00:00",
            },
        )
    assert bad.is_error and "backend_unavailable" in bad.content[0].text
    assert not ok.is_error  # the outage is scoped to one service's logs


async def test_all_scenarios_generate_and_answer_keys_stay_out_of_state(session_factory) -> None:  # type: ignore[no-untyped-def]
    from opspilot_simulator.scenarios import SCENARIOS

    store = SimulatorStore(session_factory)
    for key in SCENARIOS:
        env, data = await store.create_environment(key)
        text = str(data.state).lower()
        assert "culprit" not in text and "root_cause" not in text and "dep-" not in text, key
        assert (await store.environment(env)).scenario_key == key
