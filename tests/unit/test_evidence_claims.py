"""v0.9: deterministic evidence-state checks — a missing change history is never read as "nothing changed"."""

from __future__ import annotations

from typing import Any

import pytest

from opspilot_agents.claims import (
    change_history_unread,
    check_hypotheses,
    is_change_observation,
    negative_change_claims,
)


@pytest.mark.parametrize(
    "text",
    [
        "No internal deployment or configuration change caused the fault; the root cause lies outside our control",
        "There were no recent changes to the service",
        "No changes occurred in the window",
        "The fault was not caused by a recent deployment",
        "Deployments are ruled out as a cause",
        "This rules out a configuration change",
        "Nothing changed before the onset",
        "The service failed without any deployment",
    ],
)
def test_negative_change_claims_are_detected(text: str) -> None:
    assert negative_change_claims(text), text


@pytest.mark.parametrize(
    "text",
    [
        "No deployment or configuration-change history was available",
        "no change history could be read",
        "with no config change data available",
        "inventory-service 3.8.0 deployment introduced table locks",
        "No evidence of database failure",
        "A recent change to reservation_lock_mode is the likely cause",
        # real qwen3.5:9b-q4_K_M output after the fix: a gap, correctly stated
        "Evidence gaps: change history unavailable to rule out recent changes to inventory-db.",
        "We cannot rule out a deployment as the trigger",
        "Change history would be needed to rule out a configuration change",
        "It is unknown whether no change occurred in the window",
        "Unable to confirm that nothing changed",
    ],
)
def test_statements_about_missing_data_or_positive_changes_are_not_flagged(text: str) -> None:
    assert negative_change_claims(text) == [], text


def test_change_observations_in_log_lines() -> None:
    assert is_change_observation("starting inventory-service version=3.8.0 reservation_lock_mode=table")
    assert is_change_observation("config loaded: db_pool_max=40")
    assert not is_change_observation("sent batch of 42 notifications")


def _state(change_status: str, with_change_evidence: bool = False) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    if with_change_evidence:
        evidence["ev-dep"] = {"id": "ev-dep", "kind": "deployment", "data": {}}
    return {
        "evidence": evidence,
        "tool_calls": [{"tool": "list_recent_deployments", "status": change_status}],
    }


def test_only_unknown_change_history_triggers_the_check() -> None:
    hyp = {"title": "No recent deployments; external cause", "description": ""}
    assert check_hypotheses([dict(hyp)], _state("ok"))[0].get("evidence_warnings") is None  # simulator: readable
    assert check_hypotheses([dict(hyp)], _state("error", True))[0].get("evidence_warnings") is None
    flagged = check_hypotheses([dict(hyp)], _state("error"))[0]
    assert flagged["evidence_warnings"] and "absence of evidence only" in flagged["evidence_warnings"][0]
    assert change_history_unread(_state("error")) == ["list_recent_deployments"]
