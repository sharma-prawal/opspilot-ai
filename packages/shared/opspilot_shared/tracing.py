"""OpenTelemetry tracing setup. Exporter is optional: none | console | otlp.

Code everywhere uses ``get_tracer(__name__)`` from the OTel API; with exporter ``none`` spans are
still created (so trace/span IDs appear in logs) but are not exported anywhere.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from opspilot_shared.logging import get_logger

_log = get_logger(__name__)
_CONFIGURED = False


def configure_tracing(service_name: str, exporter: str = "none", otlp_endpoint: str = "") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if exporter == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif exporter == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:  # optional extra not installed
            _log.warning("otlp_exporter_unavailable", hint="uv sync --extra otlp")
        else:
            endpoint = otlp_endpoint.replace(":4317", ":4318").rstrip("/") + "/v1/traces"
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    _CONFIGURED = True


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None
