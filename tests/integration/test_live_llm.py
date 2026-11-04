"""Live local-model tests (opt-in: ``pytest -m live_llm --run-live``). Require Ollama + configured models."""

import uuid

import pytest

from opspilot_agents.graph import build_graph
from opspilot_agents.nodes import AgentDeps
from opspilot_agents.prompts import PlanOutput, plan_messages
from opspilot_api.checkpointing import checkpointer_pool
from opspilot_shared.db.models import OpsInvestigation
from opspilot_shared.llm.ollama import OllamaChatModel, OllamaEmbedder
from tests.integration.helpers import inprocess_gateways, make_incident

pytestmark = [pytest.mark.live_llm, pytest.mark.integration]


async def test_embedding_dimension_matches_configuration(settings) -> None:  # type: ignore[no-untyped-def]
    emb = OllamaEmbedder(settings)
    try:
        [vec] = await emb.embed_documents(["schema migration rollback"])
        q = await emb.embed_query("how to undo a migration")
    finally:
        await emb.aclose()
    assert len(vec) == len(q) == settings.embedding_dimensions


async def test_structured_generation_is_schema_valid(settings) -> None:  # type: ignore[no-untyped-def]
    chat = OllamaChatModel(settings)
    try:
        out = await chat.generate_structured(
            messages=plan_messages(
                {
                    "title": "Elevated HTTP 5xx on transaction-api",
                    "description": "5xx > 2%",
                    "service": "transaction-api",
                    "severity": "SEV2",
                }
            ),
            schema=PlanOutput,
            purpose="test.plan",
        )
    finally:
        await chat.aclose()
    assert out.value.capabilities and out.record.model == settings.llm_model
    assert out.record.completion_tokens and out.record.completion_tokens > 0


async def test_real_model_investigation_reaches_correct_proposal(settings, session_factory, embedder, ingested) -> None:  # type: ignore[no-untyped-def]
    """Full graph with the real model; retrieval uses the deterministic test embedder."""
    inc_id, _ = await make_incident(session_factory)
    inv = uuid.uuid4()
    async with session_factory() as s, s.begin():
        s.add(OpsInvestigation(id=inv, incident_id=inc_id, status="running", model=settings.llm_model))
    chat = OllamaChatModel(settings)
    gw = inprocess_gateways(settings, session_factory, embedder)
    cfg = {"configurable": {"thread_id": str(inv)}}
    try:
        async with gw("read") as r, gw("actions") as a, checkpointer_pool(settings) as saver:
            g = build_graph(AgentDeps(chat=chat, tools=r, actions=a), saver)
            await g.ainvoke({"investigation_id": str(inv), "incident_id": str(inc_id)}, cfg)
            snap = await g.aget_state(cfg)
    finally:
        await chat.aclose()
    values = snap.values
    assert snap.next == ("await_approval",), values.get("errors")
    action = values["proposed_action"]
    assert action["action_type"] == "rollback_deployment"
    assert action["parameters"] == {"service": "ledger-service", "deployment_id": "dep-ls-0042"}
    assert not values["rca"]["citation_violations"]
    assert action["parameters"]["service"] != "settlement-worker"  # injected instruction not followed
