"""Error taxonomy. ``error_class`` is logged and stored so failures can be aggregated."""

from __future__ import annotations


class OpsPilotError(Exception):
    error_class = "internal"
    transient = False


class ConfigurationError(OpsPilotError):
    error_class = "configuration"


class NotFoundError(OpsPilotError):
    error_class = "not_found"


class ConflictError(OpsPilotError):
    error_class = "conflict"


class AuthorizationError(OpsPilotError):
    error_class = "authorization"


class ValidationFailure(OpsPilotError):
    error_class = "validation"


class LLMError(OpsPilotError):
    error_class = "llm"


class LLMUnavailableError(LLMError):
    error_class = "llm_unavailable"
    transient = True


class LLMOutputError(LLMError):
    """Model returned output that failed schema validation after retries."""

    error_class = "llm_invalid_output"


class EmbeddingError(OpsPilotError):
    error_class = "embedding"
    transient = True


class ToolError(OpsPilotError):
    error_class = "tool"


class ToolTransientError(ToolError):
    error_class = "tool_transient"
    transient = True


class CapacityError(OpsPilotError):
    """Admission refused: the bounded work queue is full (retry later)."""

    error_class = "capacity"
    transient = True


class OwnershipError(OpsPilotError):
    """Another process owns execution for this database, or this process lost ownership (C0-G4, fail closed)."""

    error_class = "execution_owner_unavailable"


class BudgetExceededError(OpsPilotError):
    error_class = "budget_exceeded"


class ApprovalError(OpsPilotError):
    error_class = "approval"
