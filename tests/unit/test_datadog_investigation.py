"""v0.9: the unchanged investigation graph analyzes a Datadog snapshot (logs, metrics, APM spans), read-only.

The real LangGraph workflow with a scripted model, over a snapshot collected from the synthetic Datadog fixture. The
graph is the same one that serves uploads and Loki/Prometheus snapshots; only the evidence provider's data differs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from opspilot_agents.prompts import CONNECTED_TELEMETRY_NOTE, connected_note, read_only_note
from opspilot_mcp.file_evidence import CONNECTED_SERVER, LoadedUpload, UploadedEvidenceProvider, _query_view
from opspilot_shared.connectors.contract import FetchWindow
from opspilot_shared.connectors.snapshot import SourceSelection, collect
from tests.fakes.datadog import WINDOW, FakeDatadog
from tests.fakes.models import _evidence_from
from tests.unit.test_connected_investigation import run
from tests.unit.test_upload_investigation import KNOWLEDGE

W = FetchWindow(start=datetime.fromisoformat(WINDOW["start"]), end=datetime.fromisoformat(WINDOW["end"]))
DEFAULT = (
    "errors_warnings",
    "lifecycle",
    "http_5xx_ratio",
    "trace_error_ratio",
    "p95_latency_ms",
    "http_requests_per_min",
    "error_spans",
)


async def dd_incident(fake: FakeDatadog, templates: tuple[str, ...] = DEFAULT) -> Any:
    snap = await collect(
        fake.registry(), [SourceSelection("datadog", templates)], ["orders-api", "inventory-service"], W
    )
    inc_id, ds_id = uuid.uuid4(), uuid.uuid4()
    incident = {
        "id": str(inc_id),
        "reference": "INC-TEST-DATADOG",
        "title": "Orders failing with 504s",
        "description": "orders-api 5xx alert fired (synthetic Datadog fixture).",
        "severity": "SEV2",
        "status": "open",
        "service": "orders-api",
        "environment_id": str(ds_id),
        "detected_at": datetime(2026, 11, 15, 14, 5, tzinfo=UTC).isoformat(),
        "evidence_source": "connector",
        "affected_services": ["orders-api", "inventory-service"],
        "telemetry_queries": [_query_view(q.model_dump(mode="json")) for q in snap.queries],
        "snapshot_at": datetime(2026, 11, 19, 12, tzinfo=UTC).isoformat(),
    }
    provider = UploadedEvidenceProvider(None)  # type: ignore[arg-type]  # cache pre-filled: no DB access
    loaded = LoadedUpload(ds_id, incident, snap.dataset, "connector", ("datadog",))
    provider._cache[str(ds_id)] = loaded
    provider._cache[f"incident:{inc_id}"] = loaded
    return provider, inc_id, incident


def lock_rca(messages: list[Any]) -> dict[str, Any]:
    ev = _evidence_from(messages)
    logs = [e["id"] for e in ev if e["kind"] == "log_pattern" and "inventory-service" in e["summary"]][:2]
    metrics = [e["id"] for e in ev if e["kind"] == "metric_anomaly"][:2]
    deps = [e["id"] for e in ev if e["kind"] == "dependency"][:1]
    return {
        "summary": "inventory-service waits for stock_levels locks; orders-api times out against it.",
        "hypotheses": [
            {
                "title": "Lock contention on stock_levels after inventory-service 3.8.0",
                "category": "dependency_degradation",
                "description": "Reservations wait seconds for table locks; orders-api answers 504.",
                "confidence": 0.7,
                "supporting_evidence_ids": [*logs, *metrics, *deps],
            }
        ],
        "evidence_gaps": ["deployment history for inventory-service"],
        "followups": [],
        "impact_ongoing": True,
        "decision": "escalate",
        "remediation_plan": [],
        "escalation": {"required": False},
    }


async def test_datadog_snapshot_is_analyzed_read_only_with_citations_and_dependencies() -> None:
    fake = FakeDatadog()
    provider, inc_id, _ = await dd_incident(fake)
    before = len(fake.requests)
    state, tools = await run(provider, inc_id, lock_rca)
    assert len(fake.requests) == before  # the frozen snapshot is the only evidence; Datadog is never re-queried

    assert state["status"] == "completed"
    outcome = state["outcome"]
    assert outcome["code"] == "analysis_complete" and outcome["read_only"] and outcome["actions_executed"] == 0
    assert not state.get("remediation_plan") and state.get("proposed_action") is None and not state.get("executions")
    ops = [r.record for r in tools.records if r.tool not in KNOWLEDGE]
    assert ops and {c.server for c in ops} == {CONNECTED_SERVER}

    ev = state["evidence"]
    anomaly = next(e for e in ev.values() if e["kind"] == "metric_anomaly" and e["service"] == "orders-api")
    assert "datadog/" in anomaly["data"]["sources"]
    log = next(e for e in ev.values() if e["kind"] == "log_pattern" and e["service"] == "inventory-service")
    assert log["data"]["attributes"]["source_ref"].startswith("datadog/")
    by_tool: dict[str, Any] = {}
    for r in tools.records:
        by_tool.setdefault(r.tool, []).append(r)
    deps = [r for r in by_tool["get_service_dependencies"] if r.ok]
    assert deps, [r.error for r in by_tool["get_service_dependencies"]]
    downstream = {d["depends_on"] for r in deps for d in (r.data or {}).get("downstream", [])}
    assert "inventory-service" in downstream or "inventory-db" in downstream  # observed span parent/child edges
    assert "Datadog events are not collected" in (by_tool["list_recent_deployments"][0].error or "")
    assert "historical snapshot of Datadog telemetry" in (by_tool["get_service_health"][0].error or "")
    assert not any(e["kind"] == "deployment" for e in ev.values())

    cited = {i for h in state["rca"]["hypotheses"] for i in h["supporting_evidence_ids"]}
    assert cited and cited <= set(ev)  # every citation is persisted evidence
    md = state["report"]["markdown"]
    assert "snapshot of Datadog telemetry (logs, metrics, APM spans)" in md
    assert "## Telemetry queries (provenance)" in md and "Datadog (datadoghq.com, log)" in md
    assert "[open](https://app.datadoghq.com/logs?query=" in md
    assert "_(source: datadog/" in md and "traces may be partial" in md
    assert "fixture-api-key" not in md and "fixture-app-key" not in md


async def test_prompt_names_datadog_signals_and_partial_traces_while_v06_note_is_unchanged() -> None:
    fake = FakeDatadog()
    _, _, incident = await dd_incident(fake)
    note = read_only_note(incident)
    assert note.startswith("Evidence source: a historical, read-only snapshot")
    assert "(Datadog: logs, metrics, APM spans)" in note and "parent_missing" in note
    assert "change history, live service health" in note  # traces are available here, so not listed as missing
    no_spans = {
        **incident,
        "telemetry_queries": [q for q in incident["telemetry_queries"] if q.get("signal") != "span"],
    }
    assert "change history, traces, live service health" in connected_note(no_spans)
    v06 = {**incident, "telemetry_queries": [{"connector": "loki", "status": "ok"}, {"connector": "prometheus"}]}
    assert read_only_note(v06) == CONNECTED_TELEMETRY_NOTE  # Loki/Prometheus prompts are byte-identical to v0.6


async def test_missing_span_permission_keeps_logs_and_metrics_and_leaves_traces_unknown() -> None:
    fake = FakeDatadog()
    fake.fail["/api/v2/spans/events/search"] = 403
    provider, inc_id, incident = await dd_incident(fake)
    state, tools = await run(provider, inc_id, lock_rca)
    assert state["status"] == "completed" and state["outcome"]["read_only"]
    dep_calls = [r for r in tools.records if r.tool == "get_service_dependencies"]
    assert dep_calls and all(not r.ok and "no traces/spans were collected" in (r.error or "") for r in dep_calls)
    assert "change history, traces, live service health" in read_only_note(incident)
    md = state["report"]["markdown"]
    assert "Inspect traces for the failing requests in Datadog APM; no spans were collected." in md
    assert "permission_denied" in md or "error, 0 record(s)" in md
