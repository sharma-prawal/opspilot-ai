"""C0-F3: authoritative section coverage in the knowledge node, without weakening any causal gate.

Retrieval may add other sections of the top-ranked *current* runbook; it never creates candidate actions, never
expands non-current documents, and the rollback gates decide admissibility exactly as before.
"""

from typing import Any

from opspilot_agents.nodes import AgentDeps, AgentPolicy, InvestigationNodes
from opspilot_agents.prompts import rca_messages
from opspilot_agents.remediation import validate_step
from opspilot_rag.retrieval import section_role
from tests.fakes.gateway import ScriptedGateway


def chunk(cid: str, title: str, heading: str, text: str, *, status: str = "current", **meta: Any) -> dict[str, Any]:
    return {
        "chunk_id": f"{cid:0<8}-0000-0000-0000-000000000000",
        "document_id": f"doc-{title}",
        "document_version": 4,
        "source_uri": f"runbooks/{title}.md",
        "title": title,
        "doc_type": "runbook",
        "heading_path": f"{title} > {heading}",
        "snippet": text,
        "content": text,
        "content_sha256": "0" * 64,
        "score": 0.5,
        "metadata": {"status": status, **meta},
    }


SYMPTOMS = "Symptoms: p95 latency rises and the pool sits at its maximum."
CAUSE = (
    "A saturated pool means connections are held too long. "
    "If a recent deployment introduced the slow query, revert that deployment."
)
CAPACITY = "Never change a pool size without checking the datastore: replicas x pool + other clients <= 90% of usable."
OBSOLETE = "Raise the pool to 80 per replica and restart the service."


def knowledge_gateway(context: list[dict[str, Any]], results: list[dict[str, Any]] | None = None) -> ScriptedGateway:
    results = results or [
        chunk("aaaa1111", "Pool Runbook", "Pool Runbook", SYMPTOMS),
        chunk("bbbb2222", "Legacy Pool Tuning", "Legacy Pool Tuning", OBSOLETE, status="superseded"),
    ]
    return ScriptedGateway(
        {
            "search_runbooks": lambda a: {"query_id": "q1", "results": results, "context": context, "warnings": []},
            "get_historical_incidents": lambda a: {"query_id": "q2", "results": [], "warnings": []},
        }
    )


def sections() -> list[dict[str, Any]]:
    anchor = "aaaa1111-0000-0000-0000-000000000000"
    return [
        chunk(
            "cccc3333",
            "Pool Runbook",
            "Pool exhaustion is usually a symptom",
            CAUSE,
            expanded_from=anchor,
            section_role="remediation",
        ),
        chunk(
            "dddd4444",
            "Pool Runbook",
            "Capacity check before any pool change",
            CAPACITY,
            expanded_from=anchor,
            section_role="constraints",
        ),
    ]


def state() -> dict[str, Any]:
    return {"incident": {"title": "ledger latency", "service": "ledger"}, "evidence": {}, "tool_calls": []}


async def run_knowledge(gw: ScriptedGateway, policy: AgentPolicy | None = None) -> dict[str, Any]:
    nodes = InvestigationNodes(AgentDeps(chat=None, tools=gw, actions=None, policy=policy or AgentPolicy()))  # type: ignore[arg-type]
    return await nodes.knowledge(state())  # type: ignore[arg-type]


async def test_rollback_guidance_in_another_section_reaches_the_rca_prompt() -> None:
    gw = knowledge_gateway(sections())
    out = await run_knowledge(gw)
    [(_tool, args)] = [c for c in gw.calls if c[0] == "search_runbooks"]
    assert args["expand_sections"] == 4
    ev = out["evidence"]
    added = [e for e in ev.values() if e["data"].get("expanded_from")]
    assert {e["data"]["section_role"] for e in added} == {"remediation", "constraints"}
    anchor = next(e for e in ev.values() if "Symptoms" in e["summary"])
    for e in added:  # cited like any passage: full snapshot, version, lifecycle, just below the anchor
        assert e["citation"]["passage"] in (CAUSE, CAPACITY) and e["citation"]["lifecycle_status"] == "current"
        assert e["relevance"] == round(anchor["relevance"] - 0.05, 2) and e["data"]["rank"] == anchor["data"]["rank"]
    obs = out["observations"][0]
    assert obs["retrieval"]["section_coverage"] == {"Pool Runbook": ["remediation", "constraints"]}
    prompt_ev = sorted(ev.values(), key=lambda e: (-e["relevance"], e["id"]))
    rendered = "\n".join(
        m["content"]
        for m in rca_messages(
            {"title": "t", "service": "ledger", "severity": "high", "detected_at": "2026-11-03T14:00:00+00:00"},
            {"start": "a", "end": "b", "detected_at": "c"},
            [{k: e[k] for k in ("id", "kind", "service", "relevance", "summary")} for e in prompt_ev],
            out["observations"],
            1,
        )
    )
    assert "revert that deployment" in rendered and "90% of usable" in rendered
    assert "remediation_plan" not in out and "proposed_action" not in out  # retrieval proposes nothing


async def test_obsolete_document_never_enters_investigation_context_and_is_never_expanded() -> None:
    """C0-G3 (was: kept, marked and demoted). Normal investigation context never contains superseded/withdrawn
    guidance; the MCP server already excludes it, and the node withholds any that still arrives."""
    legacy_section = chunk(
        "eeee5555", "Legacy Pool Tuning", "Mitigation", OBSOLETE, status="superseded",
        expanded_from="bbbb2222-0000-0000-0000-000000000000", section_role="remediation",
    )  # fmt: skip
    out = await run_knowledge(knowledge_gateway([*sections(), legacy_section]))
    assert not any("Legacy" in e["summary"] or OBSOLETE in e["summary"] for e in out["evidence"].values())
    assert all(e["citation"]["lifecycle_status"] == "current" for e in out["evidence"].values())
    withheld = out["observations"][0]["retrieval"]["withheld_obsolete"]
    assert withheld == ["Legacy Pool Tuning (superseded)", "Legacy Pool Tuning (superseded)"]


async def test_expansion_can_be_disabled_and_is_bounded() -> None:
    gw = knowledge_gateway([])
    await run_knowledge(gw, AgentPolicy(knowledge_section_expansion=0))
    assert gw.calls[0][1]["expand_sections"] == 0
    assert AgentPolicy().knowledge_section_expansion <= 4  # the MCP schema rejects more (integration test)


async def test_document_without_remediation_guidance_adds_no_remediation_coverage() -> None:
    anchor = "aaaa1111-0000-0000-0000-000000000000"
    only_diagnostics = [
        chunk(
            "eeee5555",
            "Pool Runbook",
            "Diagnosis",
            "Check pg_stat_activity for long queries.",
            expanded_from=anchor,
            section_role="diagnostics",
        )
    ]
    out = await run_knowledge(knowledge_gateway(only_diagnostics))
    assert out["observations"][0]["retrieval"]["section_coverage"] == {"Pool Runbook": ["diagnostics"]}
    assert "remediation_plan" not in out and "proposed_action" not in out


def test_section_roles_are_generic() -> None:
    assert section_role("R > Mitigation", "1. Identify long queries") == "remediation"
    assert section_role("R > Pool exhaustion is usually a symptom", CAUSE) == "remediation"
    assert section_role("R > Capacity check before any pool change", CAPACITY) == "constraints"
    assert section_role("R > Common causes", "- A slow query holding connections.") == "causes"
    assert section_role("R > Diagnosis", "Look for lock waits.") == "diagnostics"
    assert section_role("R > Background", "The ledger stores postings.") == "other"


# ----------------------------------------------------------------------------- the gates still decide
def ev(eid: str, kind: str, service: str | None, data: dict[str, Any]) -> dict[str, Any]:
    return {"id": eid, "kind": kind, "service": service, "relevance": 0.8, "summary": eid, "data": data}


REVERT_GUIDANCE = ev("ev-kb-revert", "knowledge", None, {"section_role": "remediation", "expanded_from": "x"})


def dep(dep_id: str, service: str, corr: float) -> dict[str, Any]:
    return ev(
        f"ev-deploy-{dep_id}",
        "deployment",
        service,
        {"id": dep_id, "service": service, "kind": "application", "status": "succeeded", "correlation": corr},
    )


def rollback(dep_id: str, service: str) -> dict[str, Any]:
    return {"action_type": "rollback_deployment", "service": service, "deployment_id": dep_id}


def test_unrelated_recent_deployment_is_still_rejected_despite_revert_guidance() -> None:
    evidence = {e["id"]: e for e in (REVERT_GUIDANCE, dep("dep-1", "api", 0.1))}
    chk = validate_step(rollback("dep-1", "api"), evidence, "api")
    assert not chk.ok and "does not correlate" in chk.reason


def test_provider_outage_does_not_become_a_rollback_despite_revert_guidance() -> None:
    evidence = {
        e["id"]: e
        for e in (
            REVERT_GUIDANCE,
            dep("dep-2", "api", 0.6),
            ev(
                "ev-log-1",
                "log_pattern",
                "api",
                {"level": "ERROR", "count": 95, "attributes": {"upstream": "fx-provider"}},
            ),
            ev("ev-log-2", "log_pattern", "api", {"level": "ERROR", "count": 5, "attributes": {}}),
            ev("ev-dep-1", "dependency", "fx-provider", {"health": {"status": "unhealthy"}}),
        )
    }
    chk = validate_step(rollback("dep-2", "api"), evidence, "api")
    assert not chk.ok and "fx-provider" in chk.reason


def test_multiple_plausible_causes_stay_unresolved_despite_revert_guidance() -> None:
    evidence = {e["id"]: e for e in (REVERT_GUIDANCE, dep("dep-a", "api", 0.8), dep("dep-b", "worker", 0.75))}
    chk = validate_step(rollback("dep-a", "api"), evidence, "api")
    assert not chk.ok and chk.category == "insufficient_evidence"
