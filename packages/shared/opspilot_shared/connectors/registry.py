"""Configured connectors, built from settings (v0.6). A connector exists only when its URL is configured."""

from __future__ import annotations

from typing import Any

import httpx

from opspilot_shared.config import Settings
from opspilot_shared.connectors.azure_monitor import AzureMonitorConnector
from opspilot_shared.connectors.base import Limits
from opspilot_shared.connectors.contract import ConnectorError, TelemetryConnector
from opspilot_shared.connectors.datadog import DatadogConnector
from opspilot_shared.connectors.loki import LokiConnector
from opspilot_shared.connectors.prometheus import PrometheusConnector
from opspilot_shared.connectors.templates import load_templates

KNOWN = {
    "loki": {"name": "Grafana Loki", "signal": "log", "signals": ["log"], "env": "LOKI_URL"},
    "prometheus": {"name": "Prometheus", "signal": "metric", "signals": ["metric"], "env": "PROMETHEUS_URL"},
    "datadog": {
        "name": "Datadog",
        "signal": "log",
        "signals": ["log", "metric", "span"],
        "env": "DATADOG_ENABLED=true, DATADOG_SITE, DATADOG_API_KEY and DATADOG_APP_KEY",
    },
    "azure_monitor": {
        "name": "Azure Monitor",
        "signal": "log",
        "signals": ["log", "metric", "span"],
        "env": "AZURE_MONITOR_ENABLED=true, AZURE_MONITOR_WORKSPACE_ID and an AZURE_MONITOR_AUTH_MODE with its "
        "credentials",
    },
}
# Shown in the UI and docs so planned work is never mistaken for an implemented connector.
PLANNED = ("Amazon CloudWatch", "custom adapters")


class ConnectorRegistry:
    def __init__(
        self,
        connectors: dict[str, TelemetryConnector],
        problems: dict[str, str] | None = None,
        template_problems: list[str] | None = None,
    ) -> None:
        self._connectors = connectors
        self._problems = problems or {}
        self.template_problems = template_problems or []

    @classmethod
    def from_settings(
        cls, settings: Settings, *, transports: dict[str, httpx.AsyncBaseTransport] | None = None
    ) -> ConnectorRegistry:
        templates, template_problems = load_templates(settings.telemetry_templates_file)
        limits = Limits(
            timeout=settings.telemetry_timeout_seconds,
            max_window_hours=settings.telemetry_max_window_hours,
            max_log_lines=settings.telemetry_max_log_lines,
            max_series=settings.telemetry_max_series,
            max_response_bytes=settings.telemetry_max_response_bytes,
        )
        transports = transports or {}
        connectors: dict[str, TelemetryConnector] = {}
        problems: dict[str, str] = {}
        if settings.loki_url.strip():
            try:
                connectors["loki"] = LokiConnector(
                    url=settings.loki_url,
                    tenant_id=settings.loki_tenant_id.strip(),
                    service_label=settings.loki_service_label,
                    templates=templates,
                    limits=limits,
                    bearer_token=settings.loki_bearer_token.get_secret_value(),
                    username=settings.loki_username,
                    password=settings.loki_password.get_secret_value(),
                    transport=transports.get("loki"),
                )
            except ConnectorError as exc:
                problems["loki"] = exc.message
        if settings.prometheus_url.strip():
            try:
                connectors["prometheus"] = PrometheusConnector(
                    url=settings.prometheus_url,
                    service_label=settings.prometheus_service_label,
                    templates=templates,
                    limits=limits,
                    bearer_token=settings.prometheus_bearer_token.get_secret_value(),
                    username=settings.prometheus_username,
                    password=settings.prometheus_password.get_secret_value(),
                    transport=transports.get("prometheus"),
                )
            except ConnectorError as exc:
                problems["prometheus"] = exc.message
        if settings.datadog_enabled:
            try:
                connectors["datadog"] = DatadogConnector(
                    site=settings.datadog_site,
                    api_key=settings.datadog_api_key.get_secret_value(),
                    app_key=settings.datadog_app_key.get_secret_value(),
                    env=settings.datadog_env,
                    log_indexes=settings.datadog_log_indexes.split(","),
                    max_spans=settings.datadog_max_spans,
                    local_api_url=settings.datadog_local_api_url,
                    templates=templates,
                    limits=limits,
                    transport=transports.get("datadog"),
                )
            except ConnectorError as exc:
                problems["datadog"] = exc.message
        if settings.azure_monitor_enabled:
            try:
                connectors["azure_monitor"] = AzureMonitorConnector(
                    workspace_id=settings.azure_monitor_workspace_id,
                    auth_mode=settings.azure_monitor_auth_mode,
                    tenant_id=settings.azure_tenant_id,
                    client_id=settings.azure_client_id,
                    client_secret=settings.azure_client_secret.get_secret_value(),
                    max_records=settings.azure_monitor_max_records,
                    local_api_url=settings.azure_monitor_local_api_url,
                    templates=templates,
                    limits=limits,
                    transport=transports.get("azure_monitor"),
                )
            except ConnectorError as exc:
                problems["azure_monitor"] = exc.message
        return cls(connectors, problems, template_problems)

    def get(self, connector_id: str) -> TelemetryConnector:
        c = self._connectors.get(connector_id)
        if c is None:
            if connector_id in KNOWN:
                why = self._problems.get(connector_id) or f"set {KNOWN[connector_id]['env']} to enable it"
                raise ConnectorError("not_configured", f"{KNOWN[connector_id]['name']} is not configured: {why}")
            raise ConnectorError("invalid_request", f"unknown connector {connector_id!r}")
        return c

    @property
    def configured(self) -> list[str]:
        return list(self._connectors)

    def describe(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for cid, meta in KNOWN.items():
            if cid in self._connectors:
                items.append(self._connectors[cid].info())
            else:
                items.append(
                    {
                        "id": cid,
                        "kind": cid,
                        "name": meta["name"],
                        "signal": meta["signal"],
                        "signals": meta["signals"],
                        "configured": False,
                        "problem": self._problems.get(cid),
                        "hint": f"set {meta['env']} (see .env.example)",
                    }
                )
        return {"connectors": items, "template_problems": self.template_problems, "planned": list(PLANNED)}
