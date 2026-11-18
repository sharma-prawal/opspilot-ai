"""v0.6: the investigation graph analyzes a Loki/Prometheus snapshot through the stored-evidence provider, read-only.

Runs the real LangGraph workflow with a scripted model over a snapshot collected from the fake Loki/Prometheus APIs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from opspilot_agents.graph import build_graph
from opspilot_agents.nodes import AgentDeps
from opspilot_agents.prompts import PlanOutput, RcaOutput
from opspilot_mcp.file_evidence import CONNECTED_SERVER, LoadedUpload, UploadedEvidenceProvider, _query_view
from opspilot_shared.connectors.contract import FetchWindow
from opspilot_shared.connectors.snapshot import SourceSelection, collect
from tests.fakes.models import ScriptedChatModel, _evidence_from
from tests.fakes.telemetry import FakeTelemetry, window_dt
from tests.unit.test_upload_investigation import KNOWLEDGE, NoActions, Tools, plan

SOURCES = [
    SourceSelection("loki", ("errors_warnings", "lifecycle")),
    SourceSelection("prometheus", ("http_5xx_ratio", "p95_latency_ms", "db_pool_in_use", "db_pool_max")),
]


async def snapshot_incident(fake: FakeTelemetry, sources: list[SourceSelection] = SOURCES) -> Any:
    start, end = window_dt()
    snap = await collect(
        fake.registry(), sources, ["checkout-api", "payment-service"], FetchWindow(start=start, end=end)
    )
    inc_id, ds_id = uuid.uuid4(), uuid.uuid4()
    incident = {
        "id": str(inc_id),
        "reference": "INC-TEST-CONNECTED",
        "title": "Checkout payments failing",
        "description": "Checkout error-rate alert fired.",
        "severity": "SEV2",
        "status": "open",
        "service": "checkout-api",
        "environment_id": str(ds_id),
        "detected_at": datetime(2026, 11, 12, 9, 16, tzinfo=UTC).isoformat(),
        "evidence_source": "connector",
        "affected_services": ["checkout-api", "payment-service"],
        "telemetry_queries": [_query_view(q.model_dump(mode="json")) for q in snap.queries],
        "snapshot_at": datetime(2026, 11, 18, 12, tzinfo=UTC).isoformat(),
    }
    provider = UploadedEvidenceProvider(None)  # type: ignore[arg-type]  # cache pre-filled: no DB access
    loaded = LoadedUpload(ds_id, incident, snap.dataset, "connector")
    provider._cache[str(ds_id)] = loaded
    provider._cache[f"incident:{inc_id}"] = loaded
    return provider, inc_id


def pool_rca(messages: list[Any]) -> dict[str, Any]:
    ev = _evidence_from(messages)
    logs = [e["id"] for e in ev if e["kind"] == "log_pattern" and "payment-service" in e["summary"]][:2]
    metrics = [e["id"] for e in ev if e["kind"] == "metric_anomaly"][:2]
    return {
        "summary": "payment-service waits for database connections; checkout payments time out.",
        "hypotheses": [
            {
                "title": "payment-service database pool exhausted",
                "category": "resource_exhaustion",
                "description": "Pool in use equals the pool size; authorizations time out waiting for connections.",
                "confidence": 0.8,
                "supporting_evidence_ids": [*logs, *metrics],
            }
        ],
        "evidence_gaps": ["deployment history for payment-service"],
        "followups": [],
        "impact_ongoing": True,
        "decision": "escalate",
        "remediation_plan": [],
        "escalation": {"required": False},
    }


async def run(provider: UploadedEvidenceProvider, inc_id: uuid.UUID, rca: Any) -> tuple[dict[str, Any], Tools]:
    tools = Tools(provider)
    chat = ScriptedChatModel({PlanOutput: plan, RcaOutput: rca})
    graph = build_graph(AgentDeps(chat=chat, tools=tools, actions=NoActions()))
    state = await graph.ainvoke({"investigation_id": str(uuid.uuid4()), "incident_id": str(inc_id)})
    return state, tools


async def test_connected_snapshot_is_analyzed_read_only_with_citations() -> None:
    fake = FakeTelemetry()
    provider, inc_id = await snapshot_incident(fake)
    before = len(fake.requests)
    state, tools = await run(provider, inc_id, pool_rca)
    assert len(fake.requests) == before  # the investigation reads the stored snapshot, never the backends

    assert state["status"] == "completed"
    outcome = state["outcome"]
    assert outcome["code"] == "analysis_complete" and outcome["read_only"] and outcome["actions_executed"] == 0
    assert "connected-telemetry snapshot" in outcome["summary"]
    assert not state.get("remediation_plan") and state.get("proposed_action") is None and not state.get("executions")

    ops_calls = [r.record for r in tools.records if r.tool not in KNOWLEDGE]
    assert ops_calls and {c.server for c in ops_calls} == {CONNECTED_SERVER}
    ev = state["evidence"]
    anomaly = next(e for e in ev.values() if e["kind"] == "metric_anomaly" and e["service"] == "checkout-api")
    assert "prometheus/http_5xx_ratio/checkout-api" in anomaly["data"]["sources"]
    log = next(e for e in ev.values() if e["kind"] == "log_pattern" and e["service"] == "payment-service")
    assert log["data"]["attributes"]["source_ref"].startswith("loki/")
    # what Loki/Prometheus cannot contain is unknown, never "no change" or "healthy"
    by_tool = {r.tool: r for r in tools.records}
    assert "not part of the connected telemetry" in (by_tool["list_recent_deployments"].error or "")
    assert "historical snapshot" in (by_tool["get_service_health"].error or "")
    assert not any(e["kind"] == "deployment" for e in ev.values())

    md = state["report"]["markdown"]
    assert "Connected telemetry — read-only analysis" in md and "Suggested remediation (not executed)" in md
    assert "## Telemetry queries (provenance)" in md and "`prometheus/http_5xx_ratio/checkout-api`" in md
    assert "_(source: loki/" in md  # citations name the query and entry
    assert "change events are not part of Loki/Prometheus telemetry" in md
    assert "historical snapshot, not live state" in md and "## Remediation" not in md


async def test_failed_metric_queries_leave_impact_unknown() -> None:
    fake = FakeTelemetry()
    fake.fail["/api/v1/query_range"] = 503  # Prometheus unavailable while the snapshot was taken
    provider, inc_id = await snapshot_incident(fake)

    def unsure(messages: list[Any]) -> dict[str, Any]:
        ev = _evidence_from(messages)
        cite = [e["id"] for e in ev if e["kind"] == "log_pattern"][:1]
        return {
            "summary": "Only logs are available.",
            "hypotheses": [
                {
                    "title": "payment-service is failing checkout payments",
                    "category": "dependency_degradation",
                    "description": "Errors only.",
                    "confidence": 0.45,
                    "supporting_evidence_ids": cite,
                }
            ],
            "evidence_gaps": ["metrics"],
            "followups": [],
            "impact_ongoing": False,
            "decision": "escalate",
            "remediation_plan": [],
            "escalation": {"required": True, "reason": "evidence insufficient", "to": "payments team"},
        }

    state, tools = await run(provider, inc_id, unsure)
    assert state["outcome"]["code"] == "analysis_inconclusive" and state["outcome"]["impact"] == "unknown"
    metric_calls = [r for r in tools.records if r.tool in ("list_service_metrics", "query_metrics")]
    assert metric_calls and all(not r.ok and "metrics are unknown" in (r.error or "") for r in metric_calls)
    md = state["report"]["markdown"]
    assert "Add or select Prometheus templates that measure errors and latency for checkout-api" in md
    assert "error, 0 record(s)" in md  # the failed queries are listed in the provenance table


async def test_rca_prompt_says_change_history_is_unknown_not_absent() -> None:
    """qwen3.5 run, 2026-11-18: with an empty change list the model wrote "no changes occurred in the window".
    The digest must state that the change history could not be read."""
    fake = FakeTelemetry()
    provider, inc_id = await snapshot_incident(fake)
    seen: list[str] = []

    def capture(messages: list[Any]) -> dict[str, Any]:
        seen.append("\n".join(str(m.get("content", "")) if isinstance(m, dict) else str(m) for m in messages))
        return pool_rca(messages)

    await run(provider, inc_id, capture)
    prompt = seen[-1]
    assert "whether anything changed in the window is UNKNOWN" in prompt
    assert '"change_history": "unavailable (get_config_changes, list_recent_deployments failed)' in prompt


def test_digest_with_readable_change_history_is_unchanged() -> None:
    from opspilot_agents.synthesis import evidence_digest

    state = {
        "incident": {"service": "api", "evidence_source": "simulator"},
        "evidence": {},
        "tool_calls": [{"tool": "list_recent_deployments", "status": "ok"}],
    }
    digest = evidence_digest(state)
    assert "change_history" not in digest and not any("UNKNOWN" in n for n in digest["key_findings"])
