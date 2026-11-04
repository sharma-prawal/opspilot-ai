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
