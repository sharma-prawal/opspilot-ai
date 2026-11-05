"""C0-F3 regression on the real corpus, retriever and MCP protocol (deterministic hash embeddings).

The independent audit found the RCA context for a pool-exhaustion incident held only the active runbook's
symptom paragraph; the sections saying "revert the deployment that introduced the slow query" and "never change a
pool without the capacity check" were absent, while the obsolete pool-tuning page (raise the pool, restart) had
been correctly demoted. These tests assert the *rendered* guidance, not just the document URI.
"""

from typing import Any

import pytest

from opspilot_agents.nodes import AgentDeps, AgentPolicy, InvestigationNodes
from opspilot_agents.prompts import rca_messages
from opspilot_rag.retrieval import HybridRetriever
from opspilot_shared.domain.knowledge import DocType, RetrievalFilters
from tests.integration.helpers import inprocess_gateways

pytestmark = pytest.mark.integration

POOL_RUNBOOK = "runbooks/db-connection-pool-exhaustion.md"
LEGACY = "runbooks/legacy-ledger-pool-tuning.md"
SYMPTOM_QUERY = "PoolTimeout couldn't get a connection db_pool_in_use sits at db_pool_max ledger-service p95 latency"
RUNBOOKS = RetrievalFilters(doc_types=[DocType.RUNBOOK])


async def test_expansion_adds_sections_of_the_top_current_runbook_only(
    ingested, session_factory, embedder, settings
) -> None:  # type: ignore[no-untyped-def]
    r = HybridRetriever(session_factory, embedder, settings)
    plain = await r.search(SYMPTOM_QUERY, top_k=3, filters=RUNBOOKS, record=False)
    wide = await r.search(SYMPTOM_QUERY, top_k=3, filters=RUNBOOKS, record=False, expand_sections=4)
    assert [h.chunk_id for h in wide.results] == [h.chunk_id for h in plain.results]  # ranking API unchanged
    anchor = next(h for h in wide.results if h.metadata["lifecycle_tier"] == 0)
    assert anchor.source_uri == POOL_RUNBOOK  # premise for the content assertions below
    assert 0 < len(wide.context) <= 4
    assert {(c.document_id, c.document_version) for c in wide.context} == {
        (anchor.document_id, anchor.document_version)
    }
    assert not {c.chunk_id for c in wide.context} & {h.chunk_id for h in wide.results}
    assert all(
        c.metadata["status"] == "current" and c.metadata["expanded_from"] == str(anchor.chunk_id) for c in wide.context
    )
    text = " ".join(c.content or "" for c in [*wide.results, *wide.context] if c.source_uri == POOL_RUNBOOK)
    assert "revert that deployment" in text and "90% of (max_connections" in text


async def test_obsolete_document_is_never_expanded_even_when_it_ranks_well(
    ingested, session_factory, embedder, settings
) -> None:  # type: ignore[no-untyped-def]
    r = HybridRetriever(session_factory, embedder, settings)
    resp = await r.search(
        "legacy ledger pool tuning raise the pool to 80 per replica and restart",
        top_k=5,
        filters=RUNBOOKS,
        record=False,
        expand_sections=4,
    )
    assert all(c.source_uri != LEGACY and c.metadata["status"] == "current" for c in resp.context)
    statuses = [h.metadata["lifecycle_tier"] for h in resp.results]
    assert statuses == sorted(statuses)  # lifecycle ordering retained


def incident_state() -> dict[str, Any]:
    """Pool-exhaustion-shaped evidence; the knowledge query is built from it exactly as in an investigation."""

    def e(eid: str, kind: str, service: str, relevance: float, summary: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"id": eid, "kind": kind, "service": service, "relevance": relevance, "summary": summary, "data": data}

    evidence = [
        e(
            "ev-log-1",
            "log_pattern",
            "ledger-service",
            0.9,
            "PoolTimeout",
            {"level": "ERROR", "count": 400, "signature": "PoolTimeout: couldn't get a connection after <n> sec"},
        ),
        e("ev-ds-1", "datastore", "ledger-db", 0.85, "ledger-db connections 185/200 (94% of usable 197)", {}),
        e(
            "ev-deploy-1",
            "deployment",
            "ledger-service",
            0.9,
            "ledger-service v2",
            {"kind": "application", "change_summary": "Add statement export endpoint"},
        ),
    ]
    return {
        "incident": {"title": "ledger latency", "service": "ledger-service"},
        "evidence": {x["id"]: x for x in evidence},
        "tool_calls": [],
    }


async def test_rendered_rca_context_contains_current_operational_guidance(
    ingested, session_factory, embedder, settings
) -> None:  # type: ignore[no-untyped-def]
    async with inprocess_gateways(settings, session_factory, embedder)("read") as gw:
        nodes = InvestigationNodes(AgentDeps(chat=None, tools=gw, actions=None, policy=AgentPolicy()))  # type: ignore[arg-type]
        st = incident_state()
        out = await nodes.knowledge(st)  # type: ignore[arg-type]
    evidence = {**st["evidence"], **out["evidence"]}
    prompt_ev = sorted(evidence.values(), key=lambda x: (-x["relevance"], x["id"]))[: AgentPolicy().max_prompt_evidence]
    rendered = "\n".join(
        m["content"]
        for m in rca_messages(
            {"title": "t", "service": "ledger-service", "severity": "high", "detected_at": "2026-11-03T14:00:00+00:00"},
            {"start": "a", "end": "b", "detected_at": "c"},
            [{k: x[k] for k in ("id", "kind", "service", "relevance", "summary")} for x in prompt_ev],
            out["observations"],
            1,
        )
    )
    cited = {x["citation"]["source_uri"] for x in prompt_ev if x.get("citation")}
    assert POOL_RUNBOOK in cited  # premise
    assert "revert that deployment" in rendered
    assert "Never change a pool size without checking the datastore" in rendered
    assert LEGACY not in cited  # the obsolete raise-and-restart advice is not in the remediation context
    assert out["observations"][0]["retrieval"]["section_coverage"]


async def test_mcp_schema_bounds_section_expansion(ingested, session_factory, embedder, settings) -> None:  # type: ignore[no-untyped-def]
    async with inprocess_gateways(settings, session_factory, embedder)("read") as gw:
        ok = await gw.call("search_runbooks", {"query": SYMPTOM_QUERY, "expand_sections": 4}, agent="t")
        too_many = await gw.call("search_runbooks", {"query": SYMPTOM_QUERY, "expand_sections": 5}, agent="t")
        default = await gw.call("search_runbooks", {"query": SYMPTOM_QUERY}, agent="t")
    assert ok.ok and ok.data is not None and "context" in ok.data
    assert not too_many.ok
    assert default.ok and default.data is not None and default.data["context"] == []  # opt-in only
