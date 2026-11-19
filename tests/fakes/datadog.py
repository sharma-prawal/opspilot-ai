"""The synthetic Datadog API fixture (``scripts/datadog_fixture.py``) served through ``httpx.MockTransport`` (v0.9).

Same handler as the loopback server used for browser journeys, so unit tests, API tests and screenshots all exercise
one contract fixture built on Datadog's documented request/response shapes. Every request is recorded.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import httpx

from opspilot_shared.config import Settings
from opspilot_shared.connectors.registry import ConnectorRegistry

_FIX = Path(__file__).resolve().parents[2] / "scripts/datadog_fixture.py"
_spec = importlib.util.spec_from_file_location("datadog_fixture", _FIX)
assert _spec and _spec.loader
dd = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("datadog_fixture", dd)  # dataclasses resolve types through sys.modules
_spec.loader.exec_module(dd)

WINDOW = {"start": "2026-11-15T12:00:00Z", "end": "2026-11-15T14:30:00Z"}
INCIDENT_TIME = dd.INCIDENT_TIME
API_KEY, APP_KEY = dd.API_KEY, dd.APP_KEY


class FakeDatadog:
    def __init__(self) -> None:
        self.fixture = dd.Fixture()

    @property
    def fail(self) -> dict[str, Any]:
        return self.fixture.fail  # type: ignore[no-any-return]

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
            except TimeoutError as exc:
                raise httpx.ReadTimeout("synthetic timeout", request=request) from exc
            finally:
                if len(self.fixture.requests) > seen:
                    self.fixture.requests[-1]["host"] = request.url.host
            return httpx.Response(status, headers=headers, content=body)

        return httpx.MockTransport(handle)

    def settings(self, **overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "datadog_enabled": True,
            "datadog_site": "datadoghq.com",
            "datadog_api_key": API_KEY,
            "datadog_app_key": APP_KEY,
            **overrides,
        }
        return Settings(_env_file=None, **values)  # type: ignore[call-arg]

    def registry(self, **overrides: Any) -> ConnectorRegistry:
        return ConnectorRegistry.from_settings(self.settings(**overrides), transports={"datadog": self.transport()})
