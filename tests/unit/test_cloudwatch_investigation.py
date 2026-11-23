"""v0.11: the unchanged investigation graph analyzes an AWS CloudWatch snapshot, read-only.

The real LangGraph workflow with a scripted model, over a snapshot collected through the real SDK from the synthetic
CloudWatch protocol fixture. The graph is the one that serves uploads and the other connectors; only the evidence
provider's data differs. AWS (here: the fixture) is never contacted during the investigation.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from opspilot_agents.prompts import CONNECTED_TELEMETRY_NOTE, read_only_note
from opspilot_mcp.file_evidence import CONNECTED_SERVER, LoadedUpload, UploadedEvidenceProvider, _query_view
from opspilot_shared.connectors.snapshot import SourceSelection, collect
from tests.fakes.cloudwatch import FixtureServer, W, cw, fixture_server, registry
from tests.fakes.models import _evidence_from
from tests.unit.test_connected_investigation import run
from tests.unit.test_upload_investigation import KNOWLEDGE

TEMPLATES = (
    "cw_errors",
    "cw_timeouts",
    "cw_lifecycle",
    "cw_log_error_count",
    "alb_target_5xx",
    "alb_target_response_p95",
    "ecs_cpu",
    "custom_metrics",
)
SERVICES = ["inventory-service", "checkout-service", "api-gateway", "pricing-service"]


@pytest.fixture
def srv() -> Iterator[FixtureServer]:
    with fixture_server() as s:
        yield s


async def cw_incident(
    srv: FixtureServer, templates: tuple[str, ...] = TEMPLATES, services: list[str] = SERVICES
) -> tuple[UploadedEvidenceProvider, uuid.UUID, dict[str, Any], Any]:
    snap = await collect(registry(srv.url), [SourceSelection("cloudwatch", templates)], services, W)
    inc_id, ds_id = uuid.uuid4(), uuid.uuid4()
    incident = {
        "id": str(inc_id),
        "reference": "INC-TEST-CLOUDWATCH",
        "title": "Checkout failing: inventory timeouts",
        "description": "api-gateway 5xx alarm at 14:12 UTC (synthetic CloudWatch fixture).",
        "severity": "SEV2",
        "status": "open",
        "service": "inventory-service",
        "environment_id": str(ds_id),
        "detected_at": datetime(2026, 11, 18, 14, 12, tzinfo=UTC).isoformat(),
        "evidence_source": "connector",
        "affected_services": services,
        "telemetry_queries": [_query_view(q.model_dump(mode="json")) for q in snap.queries],
        "snapshot_at": datetime(2026, 11, 23, 12, tzinfo=UTC).isoformat(),
    }
    provider = UploadedEvidenceProvider(None)  # type: ignore[arg-type]  # cache pre-filled: no DB access
    loaded = LoadedUpload(ds_id, incident, snap.dataset, "connector", ("cloudwatch",))
    provider._cache[str(ds_id)] = loaded
    provider._cache[f"incident:{inc_id}"] = loaded
    return provider, inc_id, incident, snap


def pool_rca(messages: list[Any]) -> dict[str, Any]:
    ev = _evidence_from(messages)
    logs = [e["id"] for e in ev if e["kind"] == "log_pattern" and "inventory-service" in e["summary"]][:2]
    metrics = [e["id"] for e in ev if e["kind"] == "metric_anomaly"][:2]
    return {
        "summary": "The root cause is a configuration change that shrank inventory-service's database pool.",
        "hypotheses": [
            {
                "title": "inventory-service database pool limited to 8 after the 3.8.0 deployment",
                "category": "resource_exhaustion",
                "description": "Requests time out acquiring pooled connections; checkout and api-gateway fail.",
                "confidence": 0.9,
                "supporting_evidence_ids": [*logs, *metrics],
            },
            {
                "title": "No deployment happened; the database degraded on its own",
                "category": "dependency_degradation",
                "description": "No deployment events were recorded, so nothing changed.",
                "confidence": 0.3,
                "supporting_evidence_ids": logs[:1],
            },
        ],
        "evidence_gaps": ["change history for inventory-service"],
        "followups": [],
        "impact_ongoing": True,
        "decision": "escalate",
        "remediation_plan": [],
        "escalation": {"required": False},
    }


async def test_cloudwatch_snapshot_is_analyzed_read_only_with_citations(srv: FixtureServer) -> None:
    provider, inc_id, _, snap = await cw_incident(srv)
    calls_before = len(srv.state()["calls"])
    records_before = snap.dataset.model_dump_json()
    state, tools = await run(provider, inc_id, pool_rca)
    assert (
        len(srv.state()["calls"]) == calls_before
    )  # the frozen snapshot is the only evidence; AWS is never re-queried
    assert snap.dataset.model_dump_json() == records_before  # and it is never modified

    assert state["status"] == "completed"
    outcome = state["outcome"]
    assert outcome["code"] == "analysis_complete" and outcome["read_only"] and outcome["actions_executed"] == 0
    assert not state.get("remediation_plan") and state.get("proposed_action") is None and not state.get("executions")
    ops = [r.record for r in tools.records if r.tool not in KNOWLEDGE]
    assert ops and {c.server for c in ops} == {CONNECTED_SERVER}

    ev = state["evidence"]
    anomaly = next(e for e in ev.values() if e["kind"] == "metric_anomaly" and e["service"] == "inventory-service")
    assert "cloudwatch/" in anomaly["data"]["sources"]
    log = next(e for e in ev.values() if e["kind"] == "log_pattern" and e["service"] == "inventory-service")
    assert log["data"]["attributes"]["source_ref"].startswith("cloudwatch/")
    by_tool: dict[str, Any] = {}
    for r in tools.records:
        by_tool.setdefault(r.tool, []).append(r)
    deployments = by_tool["list_recent_deployments"][0].error or ""
    assert "AWS CloudWatch Logs Insights events" in deployments and "CloudTrail" in deployments
    assert not any(e["kind"] == "deployment" for e in ev.values())
    observed = [e for e in ev.values() if e["data"].get("change_observation")]
    assert any("max_size=8" in e["data"]["sample"] or "3.8.0" in e["data"]["sample"] for e in observed)

    cited = {i for h in state["rca"]["hypotheses"] for i in h["supporting_evidence_ids"]}
    assert cited and cited <= set(ev)
    hyps = state["rca"]["hypotheses"]
    assert hyps[0]["confidence"] == 0.9  # the model's estimate, kept; never re-ranked
    assert state["rca"]["evidence_warnings"]  # "The root cause is …" stated as established: annotated
    assert any("Unsupported claim" in w for w in hyps[1]["evidence_warnings"])  # "No deployment happened": flagged
    assert state["rca"]["summary"].startswith("The root cause is a configuration change")  # never edited

    md = state["report"]["markdown"]
    assert "snapshot of AWS CloudWatch telemetry (logs, metrics)" in md
    assert "No action was executed through AWS CloudWatch or anywhere else" in md
    assert "## How to read this report" in md and "Verified causal conclusions:** none" in md
    assert "AWS CloudWatch (us-east-1, log, /ecs/shop-prod/inventory-service, query " in md
    assert "_(source: cloudwatch/" in md and "AWS CloudTrail" in md
    coverage = md.split("## Evidence coverage", 1)[1].split("\n## ", 1)[0]
    assert "`cloudwatch/ecs_cpu/api-gateway` was not queried (no mapped CloudWatch resource)" in coverage
    assert "`cloudwatch/cw_errors/pricing-service` failed" in coverage  # log group missing: unknown, not "no errors"
    assert "its absence is not evidence that nothing changed" in coverage
    assert "AKIA" not in md and "opspilot-synthetic-fixture-secret" not in md and cw.FAKE_SECRET not in md


async def test_prompt_names_cloudwatch_limits_and_other_wording_is_unchanged(srv: FixtureServer) -> None:
    _, _, incident, _ = await cw_incident(srv, ("cw_errors", "alb_target_5xx"), ["inventory-service"])
    note = read_only_note(incident)
    assert "(AWS CloudWatch: logs, metrics)" in note
    assert "log-group mapping" in note and "absent, not zero" in note and "not mapped were not observed" in note
    assert "traces" in note  # spans/traces are named unavailable
    v06 = {**incident, "telemetry_queries": [{"connector": "loki", "status": "ok"}, {"connector": "prometheus"}]}
    assert read_only_note(v06) == CONNECTED_TELEMETRY_NOTE


async def test_logs_only_investigation_when_no_metric_resource_is_mapped(srv: FixtureServer) -> None:
    provider, inc_id, _, snap = await cw_incident(srv, ("cw_errors", "ecs_cpu"), ["api-gateway"])
    assert snap.dataset.collected == {"log": ["api-gateway"], "metric": []}
    assert any("no metrics could be collected for api-gateway" in w for w in snap.dataset.warnings)

    def gateway_rca(messages: list[Any]) -> dict[str, Any]:
        out = pool_rca(messages)
        ev = _evidence_from(messages)
        logs = [e["id"] for e in ev if e["kind"] == "log_pattern"][:2]
        out["hypotheses"] = [{**out["hypotheses"][0], "supporting_evidence_ids": logs}]
        return out

    state, _ = await run(provider, inc_id, gateway_rca)
    assert state["status"] == "completed" and state["outcome"]["read_only"]
