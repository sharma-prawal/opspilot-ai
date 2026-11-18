"""v0.5: the investigation graph analyzes uploaded files through the file-backed provider, read-only.

Runs the real LangGraph workflow with a scripted model. Operational tools are answered by
``UploadedEvidenceProvider`` from the synthetic example upload; knowledge tools by a stub (no DB needed).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from opspilot_agents.graph import build_graph
from opspilot_agents.nodes import AgentDeps, InvestigationNodes
from opspilot_agents.ports import ToolResult
from opspilot_agents.prompts import PlanOutput, RcaOutput
from opspilot_mcp.file_evidence import SERVER, LoadedUpload, UploadedEvidenceProvider
from opspilot_shared.errors import ApprovalError
from opspilot_shared.uploads.parse import UploadFile, parse_upload
from tests.fakes.gateway import ScriptedGateway
from tests.fakes.models import ScriptedChatModel, _evidence_from

EXAMPLES = Path(__file__).resolve().parents[2] / "apps/web/public/examples/uploads"
KNOWLEDGE = {"search_runbooks", "get_historical_incidents"}


def _kb(args: dict[str, Any]) -> dict[str, Any]:
    return {"query_id": str(uuid.uuid4()), "query": args["query"], "results": [], "context": []}


class Tools:
    """Operational tools -> file-backed provider; knowledge -> stub. Mirrors EvidenceRouter without a database."""

    def __init__(self, provider: UploadedEvidenceProvider) -> None:
        self.provider = provider
        self.kb = ScriptedGateway({t: _kb for t in KNOWLEDGE})
        self.records: list[ToolResult] = []

    @property
    def server_name(self) -> str:
        return "test"

    def available_tools(self) -> frozenset[str]:
        return self.provider.available_tools() | KNOWLEDGE

    async def call(self, tool: str, arguments: dict[str, Any], *, agent: str) -> ToolResult:
        gw = self.kb if tool in KNOWLEDGE else self.provider
        res = await gw.call(tool, arguments, agent=agent)
        self.records.append(res)
        return res


class NoActions(ScriptedGateway):
    def __init__(self) -> None:
        super().__init__({})

    async def call(self, tool: str, arguments: dict[str, Any], *, agent: str) -> ToolResult:  # pragma: no cover
        raise AssertionError(f"action tool {tool} must never be called for an uploaded incident")


def upload(files: list[UploadFile], *, service: str = "checkout-api", affected: list[str] | None = None) -> Any:
    d = parse_upload(files)
    inc_id, ds_id = uuid.uuid4(), uuid.uuid4()
    incident = {
        "id": str(inc_id),
        "reference": "INC-TEST-UPLOAD",
        "title": "Checkout payments failing",
        "description": "Customers see payment errors at checkout.",
        "severity": "SEV2",
        "status": "open",
        "service": service,
        "environment_id": str(ds_id),
        "detected_at": datetime(2026, 11, 12, 9, 16, tzinfo=UTC).isoformat(),
        "evidence_source": "upload",
        "affected_services": affected if affected is not None else [service, "payment-service"],
    }
    provider = UploadedEvidenceProvider(None)  # type: ignore[arg-type]  # cache pre-filled: no DB access
    loaded = LoadedUpload(ds_id, incident, d)
    provider._cache[str(ds_id)] = loaded
    provider._cache[f"incident:{inc_id}"] = loaded
    return provider, inc_id


def example_files() -> list[UploadFile]:
    return [
        UploadFile(p.name, p.read_text(), "checkout-api" if p.suffix == ".log" else None)
        for p in sorted(EXAMPLES.iterdir())
    ]


def rollback_rca(messages: list[Any]) -> dict[str, Any]:
    ev = _evidence_from(messages)
    deploys = sorted((e for e in ev if e["kind"] == "deployment"), key=lambda e: -e["relevance"])
    errors = [e["id"] for e in ev if e["kind"] == "log_pattern" and "ERROR" in e["summary"]][:2]
    top = deploys[0]
    dep_id = re.search(r"id ([\w-]+),", top["summary"]).group(1)  # type: ignore[union-attr]
    return {
        "summary": "payment-service 2.14.0 shrank its HTTP pool; checkout payments time out against it.",
        "hypotheses": [
            {
                "title": f"Deployment {dep_id} of payment-service exhausted its outbound pool",
                "category": "deployment_regression",
                "description": "Errors start two minutes after the deployment and name payment-service.",
                "confidence": 0.85,
                "supporting_evidence_ids": [top["id"], *errors],
            }
        ],
        "evidence_gaps": ["payment-service pool metrics were not uploaded"],
        "followups": [],
        "impact_ongoing": True,
        "decision": "remediate",
        "remediation_plan": [
            {
                "action_type": "rollback_deployment",
                "service": "payment-service",
                "deployment_id": dep_id,
                "rationale": "revert 2.14.0",
            }
        ],
        "escalation": {"required": False},
    }


def plan(_m: list[Any]) -> dict[str, Any]:
    return {
        "category": "unknown",
        "category_confidence": 0.3,
        "rationale": "alert only",
        "capabilities": ["telemetry", "changes", "knowledge"],
    }


async def run(provider: UploadedEvidenceProvider, inc_id: uuid.UUID, rca: Any) -> tuple[dict[str, Any], Tools]:
    tools = Tools(provider)
    chat = ScriptedChatModel({PlanOutput: plan, RcaOutput: rca})
    graph = build_graph(AgentDeps(chat=chat, tools=tools, actions=NoActions()))
    state = await graph.ainvoke({"investigation_id": str(uuid.uuid4()), "incident_id": str(inc_id)})
    return state, tools


async def test_uploaded_example_is_analyzed_read_only() -> None:
    provider, inc_id = upload(example_files())
    state, tools = await run(provider, inc_id, rollback_rca)

    assert state["status"] == "completed"
    outcome = state["outcome"]
    assert outcome["code"] == "analysis_complete" and outcome["read_only"] and outcome["actions_executed"] == 0
    # the model's rollback is kept only as a validated suggestion: nothing was proposed for approval or executed
    assert state["remediation_plan"] == [] and state["proposed_action"] is None and not state.get("executions")
    assert [s["action_type"] for s in state["suggested_remediation"]] == ["rollback_deployment"]
    assert state["suggested_remediation"][0]["parameters"]["deployment_id"] == "deploy-7731"

    # operational evidence came from the uploaded files, under the provider's own name
    ops_calls = [r.record for r in tools.records if r.tool not in KNOWLEDGE]
    assert ops_calls and {c.server for c in ops_calls} == {SERVER}
    ev = state["evidence"]
    anomaly = next(e for e in ev.values() if e["kind"] == "metric_anomaly" and e["service"] == "checkout-api")
    assert "service-metrics.csv" in anomaly["data"]["sources"]
    log = next(e for e in ev.values() if e["kind"] == "log_pattern" and e["data"]["level"] == "ERROR")
    assert log["data"]["attributes"]["source_ref"].startswith(("checkout-api.log:line", "checkout-traces.json:span"))
    deploys = {e["data"]["id"]: e["data"]["correlation"] for e in ev.values() if e["kind"] == "deployment"}
    assert deploys["deploy-7731"] > deploys.get("deploy-7702", 0)  # the unrelated earlier deploy ranks lower
    assert "telemetry:payment-service" in state["completed_tasks"]  # declared affected service was inspected
    # live state the upload cannot contain is reported as missing, not as healthy
    assert any(
        r.tool == "get_service_health" and r.error and "not part of uploaded evidence" in r.error for r in tools.records
    )

    md = state["report"]["markdown"]
    assert "Uploaded evidence — read-only analysis" in md and "Suggested remediation (not executed)" in md
    assert "Recommended next investigation steps" in md and "## Remediation" not in md
    assert "_(source: change-events.json:item 2)_" in md  # citations name the uploaded file and record


async def test_missing_evidence_gives_an_uncertain_result_with_next_steps() -> None:
    logs = "".join(
        f"2026-11-12T09:{m:02d}:00Z ERROR payment authorization failed upstream=payment-service\n" for m in range(5, 15)
    )
    provider, inc_id = upload([UploadFile("errors.log", logs, "checkout-api")], affected=[])

    def unsure(messages: list[Any]) -> dict[str, Any]:
        ev = _evidence_from(messages)
        cite = [e["id"] for e in ev if e["kind"] == "log_pattern"][:1]
        return {
            "summary": "Errors name payment-service, but nothing else was uploaded.",
            "hypotheses": [
                {
                    "title": "payment-service is failing checkout payments",
                    "category": "dependency_degradation",
                    "description": "Only error logs are available.",
                    "confidence": 0.4,
                    "supporting_evidence_ids": cite,
                }
            ],
            "evidence_gaps": ["no metrics", "no change history"],
            "followups": [],
            "impact_ongoing": False,
            "decision": "escalate",
            "remediation_plan": [],
            "escalation": {"required": True, "reason": "evidence insufficient", "to": "payments team"},
        }

    state, _ = await run(provider, inc_id, unsure)
    outcome = state["outcome"]
    assert outcome["code"] == "analysis_inconclusive" and outcome["escalate"] and outcome["impact"] == "unknown"
    md = state["report"]["markdown"]
    assert "Export error-rate and latency metrics for checkout-api" in md
    assert "deployment and configuration-change history" in md and "Upload traces" in md
    assert "no metrics" in md and "recovery was not verified" in md


async def test_read_only_nodes_refuse_approval_and_execution() -> None:
    nodes = InvestigationNodes(AgentDeps(chat=ScriptedChatModel(), tools=ScriptedGateway({}), actions=NoActions()))
    state: Any = {
        "incident": {"service": "api", "evidence_source": "upload"},
        "proposed_action": {"action_id": "a", "params_hash": "h"},
        "approval": {"decision": "approve", "approval_token": "t"},
    }
    with pytest.raises(ApprovalError, match="read-only"):
        await nodes.await_approval(state)
    with pytest.raises(ApprovalError, match="read-only"):
        await nodes.execute(state)
