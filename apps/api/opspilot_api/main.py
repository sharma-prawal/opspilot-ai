"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from opspilot_api.routes import approvals, health, incidents, investigations, knowledge, system
from opspilot_api.runtime import AppRuntime
from opspilot_shared.config import Settings, get_settings
from opspilot_shared.errors import (
    ApprovalError,
    AuthorizationError,
    CapacityError,
    ConflictError,
    EmbeddingError,
    LLMUnavailableError,
    NotFoundError,
    OpsPilotError,
    ValidationFailure,
)
from opspilot_shared.logging import bind_context, configure_logging, get_logger
from opspilot_shared.tracing import configure_tracing, current_trace_id, get_tracer

_log = get_logger(__name__)
_tracer = get_tracer(__name__)
STATUS_BY_ERROR: dict[type[OpsPilotError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    ApprovalError: 409,
    AuthorizationError: 401,
    ValidationFailure: 422,
    EmbeddingError: 503,
    LLMUnavailableError: 503,
    CapacityError: 429,
}


def create_app(
    settings: Settings | None = None,
    *,
    chat: Any | None = None,
    gateways: Any | None = None,
    embedder: Any | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    configure_tracing(settings.otel_service_name, settings.otel_exporter, settings.otel_exporter_otlp_endpoint)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AppRuntime.open(settings, chat=chat, gateways=gateways, embedder=embedder) as rt:
            # Reconcile checkpoints, decisions and application rows left by a previous process (audit H3).
            reconciled = await rt.investigations.reconcile()
            if reconciled:
                _log.warning("startup_reconciliation", **reconciled)
            app.state.runtime = rt

            async def sweep() -> None:  # bounded background maintenance: expire stale approval requests
                while True:
                    try:
                        if n := await rt.approvals.expire_stale():
                            _log.warning("approval_requests_expired", count=n)
                        await rt.dispatcher.dispatch_due()  # retry undelivered decisions (at-least-once)
                        await rt.investigations.reconcile(expired_leases_only=True)  # owners that died mid-run
                    except Exception:
                        _log.exception("maintenance_sweep_failed")
                    await asyncio.sleep(15)

            sweeper = asyncio.create_task(sweep(), name="approval-sweeper")
            try:
                yield
            finally:
                sweeper.cancel()

    app = FastAPI(
        title="OpsPilot AI",
        version="0.1.0",
        lifespan=lifespan,
        description="Local-first agentic incident investigation API. Long-running work returns 202 + an "
        "operation (investigation) ID to poll.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    )

    @app.middleware("http")
    async def correlation(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        import structlog

        structlog.contextvars.clear_contextvars()
        bind_context(correlation_id=rid)
        t0 = time.perf_counter()
        with _tracer.start_as_current_span(f"http {request.method} {request.url.path}") as span:
            span.set_attribute("http.method", request.method)
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
        response.headers["X-Request-ID"] = rid
        if not request.url.path.startswith("/health"):
            _log.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                trace_id=current_trace_id(),
            )
        return response

    @app.exception_handler(OpsPilotError)
    async def domain_error(request: Request, exc: OpsPilotError) -> JSONResponse:
        code = next((c for t, c in STATUS_BY_ERROR.items() if isinstance(exc, t)), 500)
        if code == 500:
            _log.error("unhandled_domain_error", error_class=exc.error_class, error=str(exc))
        return JSONResponse(status_code=code, content={"error": {"class": exc.error_class, "message": str(exc)}})

    for r in (
        health.router,
        system.router,
        knowledge.router,
        incidents.router,
        investigations.router,
        approvals.router,
    ):
        app.include_router(r)
    return app


def app_factory() -> FastAPI:
    return create_app()


app = app_factory()
