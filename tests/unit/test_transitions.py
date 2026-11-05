"""C0-G2: the investigation transition policy (single source of truth for status changes)."""

import itertools

from opspilot_shared.domain.investigation import ABSORBING, InvestigationStatus, can_transition

S = InvestigationStatus
ACTIVE = [S.QUEUED, S.RUNNING, S.AWAITING_APPROVAL, S.INTERRUPTED]


def test_terminal_states_are_never_left_by_background_work() -> None:
    for frm, to in itertools.product([S.COMPLETED, S.FAILED, S.CANCELLED], list(S)):
        assert can_transition(frm, to) is False, (frm, to)


def test_absorbing_states_cannot_be_left_even_by_an_operator() -> None:
    for frm, to in itertools.product(ABSORBING, list(S)):
        assert can_transition(frm, to, operator=True) is False, (frm, to)
    assert {s for s in S if s.absorbing} == {S.COMPLETED, S.CANCELLED}


def test_failed_reopens_only_through_operator_resume_to_interrupted() -> None:
    assert can_transition(S.FAILED, S.INTERRUPTED, operator=True) is True
    for to in S:
        if to is not S.INTERRUPTED:
            assert can_transition(S.FAILED, to, operator=True) is False, to


def test_active_states_reach_every_state_except_queued() -> None:
    for frm, to in itertools.product(ACTIVE, list(S)):
        assert can_transition(frm, to) is (to is not S.QUEUED or frm is S.QUEUED), (frm, to)
