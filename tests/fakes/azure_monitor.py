"""The synthetic Azure Monitor Logs API fixture (``scripts/azure_monitor_fixture.py``) via ``httpx.MockTransport``.

Same handler as the loopback server used for browser journeys (v0.10), so unit tests, API tests and screenshots all
exercise one contract fixture built on the documented Log Analytics Query API shapes. Every request is recorded.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import httpx

from opspilot_shared.config import Settings
from opspilot_shared.connectors.registry import ConnectorRegistry

_FIX = Path(__file__).resolve().parents[2] / "scripts/azure_monitor_fixture.py"
_spec = importlib.util.spec_from_file_location("azure_monitor_fixture", _FIX)
assert _spec and _spec.loader
az = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("azure_monitor_fixture", az)  # dataclasses resolve types through sys.modules
_spec.loader.exec_module(az)

WINDOW = {"start": "2026-11-16T09:30:00Z", "end": "2026-11-16T11:30:00Z"}
INCIDENT_TIME = az.INCIDENT_TIME
WORKSPACE = az.WORKSPACE
WS = {v: k for k, v in az.WORKSPACES.items()}  # scenario name -> workspace ID
LOCAL = "http://127.0.0.1:8128"


class FakeAzureMonitor:
    def __init__(self) -> None:
        self.fixture = az.Fixture()

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self.fixture.requests  # type: ignore[no-any-return]

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            seen = len(self.fixture.requests)
            try:
                status, headers, body = self.fixture.handle(
                    request.method, request.url.path, dict(request.headers), request.content
                )
            finally:
                if len(self.fixture.requests) > seen:
                    self.fixture.requests[-1]["host"] = request.url.host
                    self.fixture.requests[-1]["url"] = str(request.url)
            return httpx.Response(status, headers=headers, content=body)

        return httpx.MockTransport(handle)

    def settings(self, **overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "azure_monitor_enabled": True,
            "azure_monitor_auth_mode": "fixture",
            "azure_monitor_local_api_url": LOCAL,
            "azure_monitor_workspace_id": WORKSPACE,
            **overrides,
        }
        return Settings(_env_file=None, **values)  # type: ignore[call-arg]

    def registry(self, **overrides: Any) -> ConnectorRegistry:
        return ConnectorRegistry.from_settings(
            self.settings(**overrides), transports={"azure_monitor": self.transport()}
        )
