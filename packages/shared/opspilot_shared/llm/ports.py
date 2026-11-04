"""Provider-neutral model ports. Agents depend on these protocols, never on a vendor SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

from pydantic import BaseModel

from opspilot_shared.domain.evidence import LLMCallRecord


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class StructuredResult[T: BaseModel]:
    value: T
    record: LLMCallRecord


class ChatModel(Protocol):
    @property
    def model_name(self) -> str: ...

    async def generate_structured[T: BaseModel](
        self, *, messages: list[ChatMessage], schema: type[T], purpose: str
    ) -> StructuredResult[T]:
        """Return a schema-validated object or raise LLMOutputError / LLMUnavailableError."""
        ...


class Embedder(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...
