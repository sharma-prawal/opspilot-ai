"""v0.10: read-only RCAs keep observed facts, evidence-supported hypotheses, verified conclusions and unknowns apart.

Deterministic notes only: the model's summary and hypotheses are never edited or re-ranked. Simulator investigations
are not annotated. Cases come from the real qwen3.5:9b-q4_K_M runs on the synthetic Azure Monitor fixture.
"""

from __future__ import annotations

from typing import Any

import pytest

from opspilot_agents.claims import (
    calibrate_hypotheses,
    calibration_summary_warnings,
    certainty_claims,
    change_wording,
    suggestion_limitations,
)
from opspilot_agents.report import AZURE_EMPTY_LABEL, render_report

CONFIG_LINE = "configuration loaded: db.pool.max_size=5 db.pool.timeout_ms=2000 source=app-config revision=r-1842"


def _obs(eid: str, line: str) -> dict[str, Any]:
    return {
        "id": eid,
        "kind": "log_pattern",
        "service": "payment-service",
        "summary": f"payment-service possible change event in logs: {line}",
        "relevance": 0.5,
        "data": {
            "level": "INFO",
            "count": 1,
            "sample": line,
            "first_seen": "2026-11-16T10:28:11Z",
            "change_observation": True,
            "attributes": {},
        },
    }


def _state(source: str = "connector", *, queries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    ev = {
        "ev-chg-cfg": _obs("ev-chg-cfg", CONFIG_LINE),
        "ev-chg-ver": _obs("ev-chg-ver", "starting payment-service version=2.14.0"),
        "ev-log-pool": {
            "id": "ev-log-pool",
            "kind": "log_pattern",
            "service": "payment-service",
            "relevance": 0.85,
            "summary": "payment-service ERROR x75: Npgsql.NpgsqlException: The connection pool has been exhausted",
            "data": {
                "level": "ERROR",
                "count": 75,
                "sample": "connection pool exhausted",
                "first_seen": "2026-11-16T10:31:35Z",
                "attributes": {},
            },
        },
    }
    incident = {
        "id": "i",
        "reference": "INC-T",
        "title": "Orders failing",
        "service": "orders-api",
        "severity": "SEV2",
        "detected_at": "2026-11-16T10:35:00Z",
        "evidence_source": source,
        "affected_services": ["orders-api", "payment-service"],
        "snapshot_at": "2026-11-20T12:00:00Z",
        "telemetry_queries": queries
        if queries is not None
        else [
            {
                "id": "azure_monitor/exceptions/payment-service",
                "connector": "azure_monitor",
                "connector_name": "Azure Monitor",
                "status": "ok",
                "returned": 3,
                "start": "2026-11-16T07:35:00Z",
                "end": "2026-11-16T11:05:00Z",
                "signal": "log",
                "workspace": "w",
                "tables": ["AppExceptions"],
            },
        ],
    }
    if source == "simulator":
        incident.pop("telemetry_queries")
    return {
        "incident": incident,
        "evidence": ev,
        "window": {"start": "2026-11-16T07:35:00Z", "end": "2026-11-16T11:05:00Z", "onset": "2026-11-16T10:31:00Z"},
        "tool_calls": [{"tool": "list_recent_deployments", "status": "error", "latency_ms": 1.0}],
        "status": "completed",
    }


@pytest.mark.parametrize(
    "text",
    [
        "The root cause is a configuration change that reduced the pool size to 5",  # real run 2 summary
        "The outage was caused by pool exhaustion",
        "This is confirmed by the exceptions",
        "The cause of the 502s is the small pool",
    ],
)
def test_certainty_is_detected(text: str) -> None:
    assert certainty_claims(text), text


@pytest.mark.parametrize(
    "text",
    [
        "The root cause appears to be a configuration error",  # real run 1 summary
        "The root cause is likely the pool size",
        "The errors are probably caused by pool exhaustion",
        "This may be caused by a slow query",
        "It is consistent with a small pool",
        "The cause is unknown without change history",
    ],
)
def test_hedged_statements_are_not_flagged(text: str) -> None:
    assert certainty_claims(text) == [], text


def test_change_wording_ignores_wording_that_already_says_observation() -> None:
    assert change_wording("The deployment ev-chg-ver introduced code that holds connections")
    assert change_wording("a possible deployment was observed") == []
    assert change_wording("the observed configuration change") == []


def test_hypotheses_get_certainty_and_change_indicator_notes_without_edits() -> None:
    hyps = [
        {
            "rank": 1,
            "title": "Configuration change ev-chg-cfg reduced db.pool.max_size to 5",
            "description": "The root cause is the configuration loaded at 10:28Z.",
            "confidence": 0.95,
            "category": "configuration_error",
            "supporting_evidence_ids": ["ev-chg-cfg", "ev-log-pool"],
        },
        {
            "rank": 2,
            "title": "Deployment ev-chg-ver introduced slow queries",
            "description": "A new version may hold connections longer.",
            "confidence": 0.6,
            "category": "deployment_regression",
            "supporting_evidence_ids": ["ev-chg-ver"],
        },
        {
            "rank": 3,
            "title": "orders-db degradation",
            "description": "Possibly a missing index.",
            "confidence": 0.2,
            "category": "dependency_degradation",
            "supporting_evidence_ids": ["ev-log-pool"],
        },
    ]
    before = [(h["title"], h["description"]) for h in hyps]
    calibrate_hypotheses(hyps, _state())
    assert [(h["title"], h["description"]) for h in hyps] == before  # the model's text is never edited
    w1, w2 = hyps[0]["evidence_warnings"], hyps[1]["evidence_warnings"]
    assert any("Stated as established" in w and "95%" in w and "uncalibrated" in w for w in w1)
    assert any("not a verified deployment or configuration-change record" in w and "ev-chg-cfg" in w for w in w1)
    assert any("Change indicator, not change history ('Deployment')" in w and "not proof of cause" in w for w in w2)
    assert "evidence_warnings" not in hyps[2]  # hedged, no change evidence cited


def test_summary_notes_for_certainty_change_wording_and_ongoing() -> None:
    summary = (
        "The incident is ongoing. The root cause is a configuration change (ev-chg-cfg) that reduced the database "
        "connection pool size to 5."
    )
    notes = calibration_summary_warnings(summary, _state())
    assert any("states a cause as established ('The root cause is')" in n for n in notes)
    change = [n for n in notes if "Change indicator, not change history" in n]
    assert change and "ev-chg-cfg" in change[0] and "ev-chg-ver" not in change[0]  # cites what the summary names
    assert any(
        "'Ongoing' describes the end of the collected snapshot window (2026-11-16 11:05Z), not the current live state"
        in n
        for n in notes
    )


def test_simulator_investigations_are_not_annotated() -> None:
    state = _state("simulator")
    hyps = [
        {
            "title": "x",
            "description": "The root cause is the deployment",
            "confidence": 0.9,
            "category": "deployment_regression",
            "supporting_evidence_ids": ["ev-chg-ver"],
        }
    ]
    calibrate_hypotheses(hyps, state)
    assert "evidence_warnings" not in hyps[0]
    assert calibration_summary_warnings("The incident is ongoing; the root cause is the deployment.", state) == []


def test_restart_suggestion_names_the_persistent_configuration_limit() -> None:
    state = _state()
    state["rca"] = {
        "hypotheses": [
            {
                "rank": 1,
                "category": "configuration_error",
                "confidence": 0.95,
                "supporting_evidence_ids": ["ev-chg-cfg", "ev-log-pool"],
            }
        ]
    }
    lim = suggestion_limitations(
        {"action_type": "restart_service", "parameters": {"service": "payment-service"}}, state
    )
    assert lim and "restarting alone does not correct it" in lim[0] and "ev-chg-cfg" in lim[0]
    assert suggestion_limitations({"action_type": "scale_connection_pool"}, state) == []
    state["rca"]["hypotheses"][0] = {
        "rank": 1,
        "category": "dependency_degradation",
        "supporting_evidence_ids": ["ev-log-pool"],
    }
    assert suggestion_limitations({"action_type": "restart_service"}, state) == []


def test_report_separates_facts_hypotheses_verified_and_unknown() -> None:
    state = _state(
        queries=[
            {
                "id": "azure_monitor/exceptions/payment-service",
                "connector": "azure_monitor",
                "status": "ok",
                "connector_name": "Azure Monitor",
                "returned": 3,
                "start": "2026-11-16T07:35:00Z",
                "end": "2026-11-16T11:05:00Z",
                "signal": "log",
                "workspace": "w",
                "tables": ["AppExceptions"],
            },
            {
                "id": "azure_monitor/exceptions/inventory-service",
                "connector": "azure_monitor",
                "status": "empty",
                "connector_name": "Azure Monitor",
                "returned": 0,
                "start": "2026-11-16T07:35:00Z",
                "end": "2026-11-16T11:05:00Z",
                "signal": "log",
                "workspace": "w",
                "tables": ["AppExceptions"],
            },
            {
                "id": "datadog/errors/inventory-service",
                "connector": "datadog",
                "status": "empty",
                "connector_name": "Datadog",
                "returned": 0,
                "start": "2026-11-16T07:35:00Z",
                "end": "2026-11-16T11:05:00Z",
                "signal": "log",
                "site": "datadoghq.com",
            },
        ]
    )
    summary = "The incident is ongoing. The root cause is a configuration change (ev-chg-cfg)."
    hyps = [
        {
            "rank": 1,
            "title": "Pool size 5",
            "description": "The configuration loaded at 10:28Z.",
            "confidence": 0.95,
            "category": "configuration_error",
            "supporting_evidence_ids": ["ev-chg-cfg", "ev-log-pool"],
            "contradicting_evidence_ids": [],
        }
    ]
    state["rca"] = {
        "summary": summary,
        "hypotheses": hyps,
        "evidence_warnings": calibration_summary_warnings(summary, state),
        "impact": {"state": "ongoing", "reasons": ["5 unrecovered anomalous metric(s) on orders-api"]},
    }
    step = {
        "step": 1,
        "action_type": "restart_service",
        "parameters": {"service": "payment-service"},
        "rationale": "Rolling restart",
        "role": "containment",
    }
    state["suggested_remediation"] = [{**step, "limitations": suggestion_limitations(step, state)}]
    md = render_report(state)
    assert "## How to read this report" in md and "**Verified causal conclusions:** none" in md
    assert "Written by the model; the notes below it are deterministic checks" in md
    assert summary in md  # the summary itself is shown unchanged
    assert "> ⚠ The summary states a cause as established" in md
    assert (
        "Impact at the end of the collected snapshot window (2026-11-16 11:05:00Z): **ongoing** — 5 unrecovered "
        "anomalous metric(s) on orders-api. This is not the current live state" in md
    )
    assert "Impact at analysis time" not in md
    assert "> ⚠ Step 1 (`restart_service`): Restarting a service generally reloads its persisted configuration" in md
    coverage = md.split("## Evidence coverage", 1)[1].split("\n## ", 1)[0]
    assert f"| {AZURE_EMPTY_LABEL} | `azure_monitor/exceptions/inventory-service`" in coverage
    assert "this does not show that no such records exist" in coverage
    # other providers' empty queries keep the v0.9 "Searched, nothing found" state
    assert "| Searched, nothing found | `datadog/errors/inventory-service` |" in coverage
    assert "inventory-service` (Azure" not in coverage.split("| Searched, nothing found |", 1)[1].split("\n", 1)[0]
    provenance = md.split("## Telemetry queries (provenance)", 1)[1]
    assert "no accessible matching records (access not independently verified), 0 record(s)" in provenance
    assert "| empty, 0 record(s)" in provenance  # the Datadog row is unchanged


# ---------------------------------------------------------------------------------------------------------------------
# v0.11: details invented by the model and change claims with no change evidence (real qwen3.5:9b-q4_K_M run on the
# synthetic CloudWatch fixture, whose logs show "inventory-service 3.8.0 starting" and "timeout acquiring connection").
def test_invented_versions_quoted_names_and_uncited_deployments_are_noted_without_edits() -> None:
    hyps = [
        {
            "title": "Database connection pool saturation caused payment-service timeouts",
            "description": "This is supported by the high number of 'ConnectionPoolTimeout' errors in the logs.",
            "confidence": 0.95,
            "category": "resource_exhaustion",
            "supporting_evidence_ids": ["ev-log-pool"],
        },
        {
            "title": "A recent deployment introduced a bug that caused excessive connection usage",
            "description": "The deployment of version 2.3.1 may have introduced a logic error (connection leaks).",
            "confidence": 0.65,
            "category": "deployment_regression",
            "supporting_evidence_ids": ["ev-log-pool"],
        },
        {
            "title": "payment-service 2.14.0 holds connections longer",
            "description": "Observed start-up of version=2.14.0 'db.pool.max_size' change.",
            "confidence": 0.4,
            "category": "deployment_regression",
            "supporting_evidence_ids": ["ev-chg-ver"],
        },
    ]
    before = [(h["title"], h["description"]) for h in hyps]
    calibrate_hypotheses(hyps, _state())
    assert [(h["title"], h["description"]) for h in hyps] == before
    assert any(
        "Not found in the collected evidence: 'ConnectionPoolTimeout'" in w for w in hyps[0]["evidence_warnings"]
    )
    w2 = hyps[1]["evidence_warnings"]
    assert any("Change claim without change evidence ('recent deployment')" in w for w in w2)
    assert any("Not found in the collected evidence: version 2.3.1" in w for w in w2)
    # a version and a setting that the evidence does contain are not flagged
    assert not any("Not found" in w for w in hyps[2].get("evidence_warnings", []))
    notes = calibration_summary_warnings("Version 9.9.9 of payment-service exhausted the pool.", _state())
    assert any("version 9.9.9" in n for n in notes)
    sim = _state("simulator")
    sim_h = [{**hyps[1], "evidence_warnings": []}]
    calibrate_hypotheses(sim_h, sim)
    assert sim_h[0]["evidence_warnings"] == []  # simulator RCAs are never annotated


def test_restart_limitation_when_hypothesis_names_a_persistent_setting_in_any_category() -> None:
    """v0.11: a misconfigured limit is often categorized resource_exhaustion; the wording decides, not the category."""
    state = _state()
    restart = {"action_type": "restart_service", "parameters": {"service": "payment-service"}}
    state["rca"] = {
        "hypotheses": [
            {
                "rank": 1,
                "title": "Connection pool max_size reduced to 5 exhausts payment-service",
                "description": "The configured pool size is too small for the load.",
                "category": "resource_exhaustion",
                "supporting_evidence_ids": ["ev-log-pool"],  # cites no configuration line
            }
        ]
    }
    lim = suggestion_limitations(restart, state)
    assert lim and lim[0].startswith(
        "Restarting a service generally reloads its persisted configuration and may not resolve the underlying "
        "configuration problem."
    )
    # symptoms alone (saturation from load) are not a configuration claim
    state["rca"]["hypotheses"][0] = {
        "rank": 1,
        "title": "Database connection pool saturation caused timeouts",
        "description": "A spike in requests overwhelmed the pool.",
        "category": "resource_exhaustion",
        "supporting_evidence_ids": ["ev-log-pool"],
    }
    assert suggestion_limitations(restart, state) == []
    # the suggestion itself is never altered or removed: limitations are a separate list (nodes.propose)
    assert suggestion_limitations({"action_type": "scale_connection_pool"}, state) == []


def test_observed_change_lines_show_the_recorded_message_and_source() -> None:
    from opspilot_agents.claims import change_observations, readable_line

    line = (
        '{"level": "INFO", "service": "inventory-service", "msg": "configuration loaded: db.pool.max_size=8 '
        '(previous 40) source=ssm:/shop/prod/inventory/db", "requestId": "req-003755cd", "traceId": "1-6afdafe9-'
        '624653fc18fe45eb2197e27a"}'
    )
    assert readable_line(line).startswith("configuration loaded: db.pool.max_size=8 (previous 40)")
    assert readable_line("starting payment-service version=2.14.0") == "starting payment-service version=2.14.0"
    ev = _obs("ev-chg-json", line)
    ev["data"]["attributes"] = {"source_ref": "cloudwatch/cw_lifecycle/inventory-service:entry 3"}
    (obs,) = change_observations({"ev-chg-json": ev})
    assert obs["line"].startswith("configuration loaded: db.pool.max_size=8")
    assert obs["source"] == "cloudwatch/cw_lifecycle/inventory-service:entry 3"
    assert ev["data"]["sample"] == line  # the evidence keeps the full original line
    state = _state()
    state["evidence"]["ev-chg-json"] = ev
    hyps = [{"title": "The deployment reduced the pool", "description": "x", "confidence": 0.5,
             "category": "deployment_regression", "supporting_evidence_ids": ["ev-chg-json"]}]  # fmt: skip
    calibrate_hypotheses(hyps, state)
    assert "ev-chg-json: 'configuration loaded: db.pool.max_size=8" in hyps[0]["evidence_warnings"][0]
