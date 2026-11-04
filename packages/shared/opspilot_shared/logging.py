"""Structured JSON logging with contextvar-bound correlation fields.

Bind identifiers once (``bind_context(investigation_id=...)``) and every log line in that
async context carries them: correlation_id, incident_id, investigation_id, tool_call_id, node.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

_CONFIGURED = False


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler(sys.stderr)  # stderr: stdout is reserved for MCP stdio
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared, processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer]
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "mcp", "uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)  # type: ignore[no-any-return]


def bind_context(**values: Any) -> None:
    structlog.contextvars.bind_contextvars(**{k: v for k, v in values.items() if v is not None})


@contextmanager
def log_context(**values: Any) -> Iterator[None]:
    with structlog.contextvars.bound_contextvars(**{k: v for k, v in values.items() if v is not None}):
        yield
