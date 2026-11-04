import uuid

import pytest

from opspilot_shared.approvals import action_params_hash, issue_token, verify_token
from opspilot_shared.errors import ApprovalError

KEY = "k" * 32
AID = uuid.uuid4()


def test_roundtrip() -> None:
    tok = issue_token(KEY, action_id=AID, params_hash="h", approved_by="op", ttl_seconds=60, now=1000)
    claims = verify_token(KEY, tok, now=1030)
    assert claims.action_id == AID and claims.params_hash == "h" and claims.approved_by == "op"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t[:-2] + ("AA" if t[-2:] != "AA" else "BB"),  # signature tampered
        lambda t: "eyJhaWQiOiJ4In0" + t[t.index(".") :],  # body swapped
        lambda t: t.replace(".", ""),  # malformed
    ],
)
def test_tampering_rejected(mutate) -> None:  # type: ignore[no-untyped-def]
    tok = issue_token(KEY, action_id=AID, params_hash="h", approved_by="op", ttl_seconds=60, now=1000)
    with pytest.raises(ApprovalError):
        verify_token(KEY, mutate(tok), now=1001)


def test_expired_and_wrong_key() -> None:
    tok = issue_token(KEY, action_id=AID, params_hash="h", approved_by="op", ttl_seconds=60, now=1000)
    with pytest.raises(ApprovalError, match="expired"):
        verify_token(KEY, tok, now=1060)
    with pytest.raises(ApprovalError, match="signature"):
        verify_token("z" * 32, tok, now=1001)


def test_short_key_refused() -> None:
    with pytest.raises(ApprovalError):
        issue_token("short", action_id=AID, params_hash="h", approved_by="op", ttl_seconds=60)


def test_params_hash_canonical() -> None:
    assert action_params_hash("a", {"x": 1, "y": 2}) == action_params_hash("a", {"y": 2, "x": 1})
    assert action_params_hash("a", {"x": 1}) != action_params_hash("b", {"x": 1})
