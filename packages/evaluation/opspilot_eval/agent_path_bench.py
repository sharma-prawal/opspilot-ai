"""Agent-path retrieval benchmark (audit finding 8).

The document benchmark (``retrieval_bench``) retrieves 30 chunks per query and collapses them into a document
ranking. The agent does something different: its knowledge node calls ``search_runbooks`` (top_k 5, every
non-incident document type) and ``get_historical_incidents`` (top_k 3, incident reports only) over MCP, demotes
non-current documents, turns each chunk into evidence with a relevance score and a prompt excerpt, and the RCA
prompt receives that evidence ordered by relevance.

This benchmark does not re-implement any of that. It runs the agent's own ``knowledge`` node against a real
read-server gateway, with the labelled question as the investigation's knowledge query (the node's query when
no other evidence exists), so queries, tools, filters, candidate depths, chunk limits, lifecycle handling and
excerpts are identical by construction. Passages are scored in the order the RCA prompt would receive them.
Relevance labels are document-level, so a passage counts as relevant when it comes from a relevant document.

Since C0-F3 the knowledge node also asks for up to ``knowledge_section_expansion`` further sections of the top
current runbook; they are part of the passages scored here. Document-level labels cannot tell whether the
*operational* sections (diagnostics, remediation, constraints) are present -- that is asserted separately by
``tests/integration/test_section_coverage.py`` on the rendered RCA context.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from opspilot_agents.nodes import AgentDeps, AgentPolicy, InvestigationNodes
from opspilot_agents.ports import ToolGateway
from opspilot_eval.metrics import latency_summary, mean
from opspilot_eval.retrieval_bench import QUESTIONS, load_questions

KNOWLEDGE_KINDS = ("knowledge", "historical_incident")


def prompt_passages(evidence: dict[str, dict[str, Any]], policy: AgentPolicy) -> list[dict[str, Any]]:
    """Knowledge evidence in RCA prompt order (same ordering and cap as ``InvestigationNodes.rca``)."""
    ranked = sorted(evidence.values(), key=lambda e: (-e["relevance"], e["id"]))[: policy.max_prompt_evidence]
    return [e for e in ranked if e["kind"] in KNOWLEDGE_KINDS and e.get("citation")]


def score_question(q: dict[str, Any], passages: list[dict[str, Any]]) -> dict[str, Any]:
    relevant = set(q["relevant"])
    uris = [p["citation"]["source_uri"] for p in passages]
    runbook_uris = [p["citation"]["source_uri"] for p in passages if p["kind"] == "knowledge"]
    first = next((i for i, u in enumerate(uris, start=1) if u in relevant), None)
    return {
        "id": q["id"],
        "style": q["style"],
        "passages": len(passages),
        "hit": first is not None,
        "doc_recall": len(set(uris) & relevant) / len(relevant) if relevant else 0.0,
        "runbook_path_recall": len(set(runbook_uris) & relevant) / len(relevant) if relevant else 0.0,
        "mrr": 1.0 / first if first else 0.0,
        "precision": sum(u in relevant for u in uris) / len(uris) if uris else 0.0,
        "non_current_passages": sum(1 for p in passages if (p["data"].get("doc_status") or "current") != "current"),
        "excerpt_chars": mean([float(len(p["summary"])) for p in passages]) if passages else 0.0,
        "excerpt_truncated": sum(1 for p in passages if len(p["citation"].get("passage") or "") > len(p["summary"])),
        "top3": uris[:3],
    }


async def run(gateway: ToolGateway, *, path: Path = QUESTIONS, policy: AgentPolicy | None = None) -> dict[str, Any]:
    policy = policy or AgentPolicy()
    nodes = InvestigationNodes(AgentDeps(chat=None, tools=gateway, actions=None, policy=policy))  # type: ignore[arg-type]
    rows: list[dict[str, Any]] = []
    latency: list[float] = []
    tool_calls: list[dict[str, Any]] = []
    for q in load_questions(path):
        state = {"incident": {"title": q["query"], "service": None}, "evidence": {}, "tool_calls": []}
        t0 = time.perf_counter()
        out = await nodes.knowledge(state)  # type: ignore[arg-type]
        latency.append(round((time.perf_counter() - t0) * 1000, 2))
        tool_calls += [{"tool": c["tool"], "arguments": c["arguments"]} for c in out.get("tool_calls", [])]
        rows.append(score_question(q, prompt_passages(out.get("evidence") or {}, policy)))

    def agg(sub: list[dict[str, Any]]) -> dict[str, float]:
        return {
            m: mean([float(r[m]) for r in sub])
            for m in ("hit", "doc_recall", "runbook_path_recall", "mrr", "precision", "passages", "excerpt_chars")
        }

    return {
        "questions": len(rows),
        "path": "InvestigationNodes.knowledge -> MCP search_runbooks(top_k=5, expand_sections) + "
        "get_historical_incidents(top_k=3)",
        "calls_per_question": sorted({c["tool"] for c in tool_calls}),
        "top_k": sorted({(c["tool"], c["arguments"].get("top_k")) for c in tool_calls}),
        "expand_sections": sorted(
            {c["arguments"].get("expand_sections", 0) for c in tool_calls if c["tool"] == "search_runbooks"}
        ),
        "overall": agg(rows),
        "by_style": {s: agg([r for r in rows if r["style"] == s]) for s in ("exact", "paraphrase")},
        "non_current_passages": sum(r["non_current_passages"] for r in rows),
        "excerpt_truncated_passages": sum(r["excerpt_truncated"] for r in rows),
        "latency": latency_summary(latency),
        "per_question": rows,
        "misses": [{"id": r["id"], "style": r["style"], "top3": r["top3"]} for r in rows if not r["hit"]],
    }
