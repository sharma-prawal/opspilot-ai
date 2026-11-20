"""v0.10: the unchanged investigation graph analyzes an Azure Monitor snapshot, read-only.

The real LangGraph workflow with a scripted model, over a snapshot collected from the synthetic Azure Monitor fixture.
The graph is the one that serves uploads, Loki/Prometheus and Datadog snapshots; only the evidence provider's data
differs. Azure is never contacted during the investigation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from opspilot_agents.prompts import CONNECTED_TELEMETRY_NOTE, connected_note, read_only_note
from opspilot_mcp.file_evidence import CONNECTED_SERVER, LoadedUpload, UploadedEvidenceProvider, _query_view
from opspilot_shared.connectors.contract import FetchWindow
from opspilot_shared.connectors.snapshot import SourceSelection, collect
from tests.fakes.azure_monitor import WINDOW, WORKSPACE, WS, FakeAzureMonitor
from tests.fakes.datadog import FakeDatadog
from tests.fakes.models import _evidence_from
from tests.unit.test_connected_investigation import run
from tests.unit.test_datadog_investigation import dd_incident
from tests.unit.test_upload_investigation import KNOWLEDGE

W = FetchWindow(start=datetime.fromisoformat(WINDOW["start"]), end=datetime.fromisoformat(WINDOW["end"]))
DEFAULT = (
    "trace_warnings",
    "trace_lifecycle",
    "exceptions",
    "failed_requests",
    "failed_dependencies",
    "http_requests_per_min",
    "request_failure_ratio",
    "http_5xx_ratio",
    "p95_latency_ms",
    "dependency_failure_ratio",
    "dependency_p95_ms",
)
SERVICES = ["orders-api", "payment-service"]


async def az_incident(
    fake: FakeAzureMonitor, templates: tuple[str, ...] = DEFAULT, **settings: Any
) -> tuple[UploadedEvidenceProvider, uuid.UUID, dict[str, Any]]:
    snap = await collect(fake.registry(**settings), [SourceSelection("azure_monitor", templates)], SERVICES, W)
    inc_id, ds_id = uuid.uuid4(), uuid.uuid4()
    incident = {
        "id": str(inc_id),
        "reference": "INC-TEST-AZURE",
        "title": "Orders failing with 502s",
        "description": "orders-api failed-request alert fired (synthetic Azure Monitor fixture).",
        "severity": "SEV2",
        "status": "open",
        "service": "orders-api",
        "environment_id": str(ds_id),
        "detected_at": datetime(2026, 11, 16, 10, 35, tzinfo=UTC).isoformat(),
        "evidence_source": "connector",
        "affected_services": SERVICES,
        "telemetry_queries": [_query_view(q.model_dump(mode="json")) for q in snap.queries],
        "snapshot_at": datetime(2026, 11, 20, 12, tzinfo=UTC).isoformat(),
    }
    provider = UploadedEvidenceProvider(None)  # type: ignore[arg-type]  # cache pre-filled: no DB access
    loaded = LoadedUpload(ds_id, incident, snap.dataset, "connector", ("azure_monitor",))
    provider._cache[str(ds_id)] = loaded
    provider._cache[f"incident:{inc_id}"] = loaded
    return provider, inc_id, incident


def pool_rca(messages: list[Any]) -> dict[str, Any]:
    ev = _evidence_from(messages)
    logs = [e["id"] for e in ev if e["kind"] == "log_pattern" and "payment-service" in e["summary"]][:2]
    metrics = [e["id"] for e in ev if e["kind"] == "metric_anomaly"][:2]
    deps = [e["id"] for e in ev if e["kind"] == "dependency"][:1]
    return {
        "summary": "payment-service exhausts its database connection pool; orders-api answers 502.",
        "hypotheses": [
            {
                "title": "payment-service connection pool limited to 5 after configuration r-1842",
                "category": "resource_exhaustion",
                "description": "SQL calls to orders-db wait 2 s for pooled connections; payments fail with 503.",
                "confidence": 0.7,
                "supporting_evidence_ids": [*logs, *metrics, *deps],
            }
        ],
        "evidence_gaps": ["deployment and configuration history for payment-service"],
        "followups": [],
        "impact_ongoing": True,
        "decision": "escalate",
        "remediation_plan": [],
        "escalation": {"required": False},
    }


def claims_no_change(messages: list[Any]) -> dict[str, Any]:
    out = pool_rca(messages)
    out["hypotheses"].append(
        {
            "title": "No deployment or configuration change occurred; orders-db degraded on its own",
            "category": "dependency_degradation",
            "description": "No deployment events were recorded, so nothing changed.",
            "confidence": 0.8,
            "supporting_evidence_ids": out["hypotheses"][0]["supporting_evidence_ids"][:1],
        }
    )
    return out


async def test_azure_snapshot_is_analyzed_read_only_with_citations_and_dependencies() -> None:
    fake = FakeAzureMonitor()
    provider, inc_id, _ = await az_incident(fake)
    before = len(fake.requests)
    state, tools = await run(provider, inc_id, pool_rca)
    assert len(fake.requests) == before  # the frozen snapshot is the only evidence; Azure is never re-queried

    assert state["status"] == "completed"
    outcome = state["outcome"]
    assert outcome["code"] == "analysis_complete" and outcome["read_only"] and outcome["actions_executed"] == 0
    assert not state.get("remediation_plan") and state.get("proposed_action") is None and not state.get("executions")
    ops = [r.record for r in tools.records if r.tool not in KNOWLEDGE]
    assert ops and {c.server for c in ops} == {CONNECTED_SERVER}

    ev = state["evidence"]
    anomaly = next(e for e in ev.values() if e["kind"] == "metric_anomaly" and e["service"] == "payment-service")
    assert "azure_monitor/" in anomaly["data"]["sources"]
    log = next(e for e in ev.values() if e["kind"] == "log_pattern" and e["service"] == "payment-service")
    assert log["data"]["attributes"]["source_ref"].startswith("azure_monitor/")
    by_tool: dict[str, Any] = {}
    for r in tools.records:
        by_tool.setdefault(r.tool, []).append(r)
    deps = [r for r in by_tool["get_service_dependencies"] if r.ok]
    assert deps, [r.error for r in by_tool["get_service_dependencies"]]
    edges = {(d["service"], d["depends_on"]) for r in deps for d in (r.data or {}).get("downstream", [])}
    assert ("orders-api", "payment-service") in edges  # observed: orders-api dependency → payment-service request
    assert not any("orders-db" in e for e in edges)  # a SQL Target is never promoted to an observed service
    deployments = by_tool["list_recent_deployments"][0].error or ""
    assert "Azure Monitor Application Insights traces" in deployments and "activity log" in deployments
    assert "historical snapshot of Azure Monitor telemetry" in (by_tool["get_service_health"][0].error or "")
    assert not any(e["kind"] == "deployment" for e in ev.values())

    cited = {i for h in state["rca"]["hypotheses"] for i in h["supporting_evidence_ids"]}
    assert cited and cited <= set(ev)
    md = state["report"]["markdown"]
    assert "snapshot of Azure Monitor telemetry (logs, metrics, Application Insights requests and dependencies)" in md
    assert "No action was executed through Azure Monitor or anywhere else" in md
    assert f"Azure Monitor (workspace {WORKSPACE}, metric, AppRequests)" in md
    assert "_(source: azure_monitor/" in md and "Application Insights (transaction search by OperationId)" in md
    assert "Bearer" not in md and "opspilot-synthetic-fixture-token" not in md
    coverage = md.split("## Evidence coverage", 1)[1].split("\n## ", 1)[0]
    assert "| Incomplete or sampled |" in coverage and "sampled (ItemCount-weighted estimates)" in coverage


async def test_prompt_names_azure_limits_while_v06_and_datadog_wording_is_unchanged() -> None:
    _, _, incident = await az_incident(FakeAzureMonitor())
    note = read_only_note(incident)
    assert "(Azure Monitor: logs, metrics, Application Insights requests and dependencies)" in note
    assert "sampled (ItemCount)" in note and "parent_missing" in note and "recorded name, not an observed" in note
    assert "A lack of exception records is not evidence that no error occurred" in note
    assert "bins without records are absent, not zero" in note
    no_spans = {
        **incident,
        "telemetry_queries": [q for q in incident["telemetry_queries"] if q.get("signal") != "span"],
    }
    assert "change history, traces, live service health" in connected_note(no_spans)
    v06 = {**incident, "telemetry_queries": [{"connector": "loki", "status": "ok"}, {"connector": "prometheus"}]}
    assert read_only_note(v06) == CONNECTED_TELEMETRY_NOTE
    _, _, dd = await dd_incident(FakeDatadog())
    dd_note = read_only_note(dd)
    assert "(Datadog: logs, metrics, APM spans)" in dd_note and "Azure" not in dd_note and "ItemCount" not in dd_note


async def test_unknown_change_history_with_config_lines_is_not_read_as_no_change() -> None:
    fake = FakeAzureMonitor()
    provider, inc_id, _ = await az_incident(fake)
    prompts: list[str] = []

    def capture(messages: list[Any]) -> dict[str, Any]:
        prompts.append("\n".join(str(m.get("content", "")) if isinstance(m, dict) else str(m) for m in messages))
        return claims_no_change(messages)

    state, _ = await run(provider, inc_id, capture)
    ev = state["evidence"]
    observed = [e for e in ev.values() if e["data"].get("change_observation")]
    assert any("version=2.14.0" in e["data"]["sample"] or "max_size=5" in e["data"]["sample"] for e in observed)
    assert "whether anything changed in the window is UNKNOWN" in prompts[-1]
    flagged = next(h for h in state["rca"]["hypotheses"] if h["title"].startswith("No deployment"))
    assert flagged["evidence_warnings"] and "Unsupported claim" in flagged["evidence_warnings"][0]
    assert flagged["confidence"] == 0.8  # annotated, never silently edited
    md = state["report"]["markdown"]
    coverage = md.split("## Evidence coverage", 1)[1].split("\n## ", 1)[0]
    assert "not a verified deployment history and not proof of cause" in coverage
    assert "its absence is not evidence that nothing changed" in coverage


async def test_missing_exceptions_table_leaves_the_signal_partial_not_healthy() -> None:
    fake = FakeAzureMonitor()
    provider, inc_id, incident = await az_incident(fake, azure_monitor_workspace_id=WS["no_exceptions_table"])
    failed = [q for q in incident["telemetry_queries"] if q["status"] == "error"]
    assert {q["id"].split("/")[1] for q in failed} >= {"exceptions", "failed_dependencies"}
    state, _ = await run(provider, inc_id, pool_rca)
    assert state["status"] == "completed" and state["outcome"]["read_only"]
    md = state["report"]["markdown"]
    assert "azure_monitor/exceptions/payment-service` failed" in md  # listed as not collected, not as "no errors"
