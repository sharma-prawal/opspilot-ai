from __future__ import annotations

from enum import StrEnum


class InvestigationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"  # process stopped mid-run; resumable from checkpoint

    @property
    def terminal(self) -> bool:
        return self in {InvestigationStatus.COMPLETED, InvestigationStatus.FAILED, InvestigationStatus.CANCELLED}

    @property
    def absorbing(self) -> bool:
        """No transition ever leaves these states (enforced in code and by a database trigger, C0-G2)."""
        return self in ABSORBING


ABSORBING = frozenset({InvestigationStatus.COMPLETED, InvestigationStatus.CANCELLED})

# C0-G2: the single transition policy for investigation status. Every status write goes through
# ``repositories.transition_investigation`` (a locked compare-and-set against this table). Terminal states are never
# left by background work (reconciliation, checkpoint restoration, outbox delivery, expiry, shutdown); ``completed``
# and ``cancelled`` are absorbing outright. ``failed`` may be reopened only by an explicit operator resume
# (``OPERATOR_ONLY``), which moves it to ``interrupted`` first.
_S = InvestigationStatus
_ACTIVE_TARGETS = frozenset({_S.RUNNING, _S.AWAITING_APPROVAL, _S.INTERRUPTED, _S.COMPLETED, _S.FAILED, _S.CANCELLED})
LEGAL_TRANSITIONS: dict[InvestigationStatus, frozenset[InvestigationStatus]] = {
    _S.QUEUED: _ACTIVE_TARGETS,
    _S.RUNNING: _ACTIVE_TARGETS,
    _S.AWAITING_APPROVAL: _ACTIVE_TARGETS,
    _S.INTERRUPTED: _ACTIVE_TARGETS,
    _S.FAILED: frozenset(),
    _S.COMPLETED: frozenset(),
    _S.CANCELLED: frozenset(),
}
OPERATOR_ONLY: frozenset[tuple[InvestigationStatus, InvestigationStatus]] = frozenset({(_S.FAILED, _S.INTERRUPTED)})


def can_transition(current: str, target: str, *, operator: bool = False) -> bool:
    """Whether ``current -> target`` is legal. Re-asserting the same non-terminal status is allowed (idempotent)."""
    frm, to = InvestigationStatus(current), InvestigationStatus(target)
    if frm == to:
        return not frm.terminal
    return to in LEGAL_TRANSITIONS[frm] or (operator and (frm, to) in OPERATOR_ONLY)
