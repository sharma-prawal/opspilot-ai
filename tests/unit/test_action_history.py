"""Malformed or mismatched outbox records must never supply authorization."""

import uuid
from datetime import UTC, datetime

import pytest

from opspilot_api.services.action_history import authorization_for
from opspilot_shared.db.models import OpsActionRequest, OpsWorkflowCommand


@pytest.mark.parametrize(
    "change",
    [
        {"decision": "unknown"},
        {"decided_by": ""},
        {"decided_by": None},
        {"decided_by": 12},
        {"decided_at": None},
        {"decided_at": "2026-11-23T10:00:00"},
        {"decided_at": "invalid"},
        {"decided_at": "123"},
        {"action_id": str(uuid.uuid4())},
        {"params_hash": "b" * 64},
    ],
)
def test_invalid_authorization(change):
    row = OpsActionRequest(id=uuid.uuid4(), investigation_id=uuid.uuid4(), params_hash="a" * 64, status="succeeded")
    payload = {
        "action_id": str(row.id),
        "params_hash": row.params_hash,
        "decision": "approve",
        "decided_by": "sre",
        "decided_at": datetime.now(UTC).isoformat(),
        **change,
    }
    command = OpsWorkflowCommand(
        action_id=row.id, investigation_id=row.investigation_id, kind="approval_decision", payload=payload
    )
    assert authorization_for(row, command) is None


def test_wrong_command_identity():
    row = OpsActionRequest(id=uuid.uuid4(), investigation_id=uuid.uuid4(), params_hash="a" * 64)
    payload = {
        "action_id": str(row.id),
        "params_hash": row.params_hash,
        "decision": "approve",
        "decided_by": "sre",
        "decided_at": "2026-11-23T10:00:00Z",
    }
    for changes in [{"action_id": uuid.uuid4()}, {"investigation_id": uuid.uuid4()}, {"kind": "other"}]:
        command = OpsWorkflowCommand(
            **{
                "action_id": row.id,
                "investigation_id": row.investigation_id,
                "kind": "approval_decision",
                "payload": payload,
                **changes,
            }
        )
        assert authorization_for(row, command) is None
    assert authorization_for(row, None) is None


@pytest.mark.parametrize("decision", ["approve", "reject", "expired"])
def test_valid_authorization_uses_original_decision_only(decision):
    row = OpsActionRequest(
        id=uuid.uuid4(),
        investigation_id=uuid.uuid4(),
        params_hash="a" * 64,
        status="succeeded",
        decided_by="execution-overwrite",
    )
    command = OpsWorkflowCommand(
        action_id=row.id,
        investigation_id=row.investigation_id,
        kind="approval_decision",
        status="failed",
        payload={
            "action_id": str(row.id),
            "params_hash": row.params_hash,
            "decision": decision,
            "decided_by": "original-sre",
            "decided_at": "2026-11-23T10:00:00+05:30",
            "approval_token": "do-not-expose",
        },
    )
    authorization = authorization_for(row, command)
    assert authorization is not None
    assert authorization.decision == decision and authorization.decided_by == "original-sre"
    assert set(authorization.model_dump()) == {"decision", "decided_by", "decided_at"}
    assert authorization.decided_at.isoformat() == "2026-11-23T10:00:00+05:30"
