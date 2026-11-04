from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_ensure_utc)]
ServiceName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,62}$", description="Service slug")]


class Contract(BaseModel):
    """Base for all contracts: immutable, strict about unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class Severity(StrEnum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


def utcnow() -> datetime:
    return datetime.now(UTC)
