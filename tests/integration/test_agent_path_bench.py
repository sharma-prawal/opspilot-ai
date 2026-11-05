"""Audit finding 8 (C0 item K): the agent-path benchmark exercises exactly the agent's retrieval calls."""

import pytest

from opspilot_agents.nodes import AgentPolicy
from opspilot_eval import agent_path_bench
from opspilot_eval.retrieval_bench import HELDOUT
from tests.integration.helpers import inprocess_gateways

pytestmark = pytest.mark.integration


async def test_agent_path_benchmark_uses_the_agents_calls_and_prompt_order(  # type: ignore[no-untyped-def]
    settings, session_factory, embedder, ingested
) -> None:
    async with inprocess_gateways(settings, session_factory, embedder)("read") as gw:
        res = await agent_path_bench.run(gw, path=HELDOUT)
    # Same tools and candidate depths as InvestigationNodes.knowledge, by construction.
    assert res["calls_per_question"] == ["get_historical_incidents", "search_runbooks"]
    assert res["top_k"] == [("get_historical_incidents", 3), ("search_runbooks", 5)]
    policy = AgentPolicy()
    assert res["expand_sections"] == [policy.knowledge_section_expansion]  # C0-F3: same expansion as the agent
    assert res["questions"] == len(res["per_question"]) > 0
    for row in res["per_question"]:
        assert 0 < row["passages"] <= 5 + policy.knowledge_section_expansion + 3 and 0.0 <= row["precision"] <= 1.0
        assert row["hit"] == (row["mrr"] > 0)
    o = res["overall"]
    assert 0.0 <= o["doc_recall"] <= 1.0 and o["excerpt_chars"] > 0


def test_prompt_order_matches_rca_ranking() -> None:
    def ev(i: str, rel: float, kind: str = "knowledge") -> dict:  # type: ignore[type-arg]
        return {"id": i, "relevance": rel, "kind": kind, "citation": {"source_uri": i}, "data": {}, "summary": "s"}

    evidence = {e["id"]: e for e in (ev("b", 0.7), ev("a", 0.7), ev("c", 0.35), ev("m", 0.9, "metric_anomaly"))}
    order = [p["id"] for p in agent_path_bench.prompt_passages(evidence, AgentPolicy())]
    assert order == ["a", "b", "c"]  # (-relevance, id), knowledge only
