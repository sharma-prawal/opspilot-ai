from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import Field

from opspilot_shared.domain.common import Contract, ServiceName, Severity, UtcDatetime


class IncidentStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    AWAITING_APPROVAL = "awaiting_approval"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"


class IncidentCategory(StrEnum):
    DEPLOYMENT_REGRESSION = "deployment_regression"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    DEPENDENCY_DEGRADATION = "dependency_degradation"
    BAD_PAYLOAD = "bad_payload"
    QUEUE_BACKLOG = "queue_backlog"
    CONFIGURATION_ERROR = "configuration_error"
    UNKNOWN = "unknown"


class Incident(Contract):
    id: uuid.UUID
    reference: str = Field(description="Human-readable key, e.g. INC-20261104-0001")
    title: str = Field(max_length=300)
    description: str = Field(max_length=4000)
    severity: Severity
    status: IncidentStatus
    service: ServiceName
    environment_id: uuid.UUID
    detected_at: UtcDatetime
    created_at: UtcDatetime
