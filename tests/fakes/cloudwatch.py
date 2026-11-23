"""The synthetic AWS CloudWatch fixture (``scripts/cloudwatch_fixture.py``) on a loopback port, for tests.

Unlike the httpx-based fakes, CloudWatch goes through the official SDK (boto3/botocore), so tests run the same
fixture server that browser journeys use and let the real SDK sign, send and parse every request. Contract testing
only: no AWS account, credential or endpoint is contacted.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from opspilot_shared.config import Settings
from opspilot_shared.connectors.base import Limits
from opspilot_shared.connectors.cloudwatch import CloudWatchConnector
from opspilot_shared.connectors.cloudwatch_resources import load_resources
from opspilot_shared.connectors.contract import FetchWindow
from opspilot_shared.connectors.registry import ConnectorRegistry

ROOT = Path(__file__).resolve().parents[2]
_FIX = ROOT / "scripts/cloudwatch_fixture.py"
_spec = importlib.util.spec_from_file_location("cloudwatch_fixture", _FIX)
assert _spec and _spec.loader
cw = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("cloudwatch_fixture", cw)  # dataclasses resolve types through sys.modules
_spec.loader.exec_module(cw)

STORY = ROOT / "infra/cloudwatch/resources.fixture.yaml"
SCENARIOS = ROOT / "infra/cloudwatch/resources.scenarios.yaml"
WINDOW = {"start": "2026-11-18T13:30:00Z", "end": "2026-11-18T15:30:00Z"}
W = FetchWindow(start=datetime.fromisoformat(WINDOW["start"]), end=datetime.fromisoformat(WINDOW["end"]))
INCIDENT_TIME = cw.INCIDENT_TIME


class FixtureServer:
    def __init__(self) -> None:
        self.httpd = cw.serve(0)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def state(self) -> dict[str, Any]:
        with urllib.request.urlopen(f"{self.url}/_fixture/state", timeout=5) as r:
            return json.loads(r.read())  # type: ignore[no-any-return]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@contextmanager
def fixture_server() -> Iterator[FixtureServer]:
    srv = FixtureServer()
    try:
        yield srv
    finally:
        srv.close()


async def no_sleep(_: float) -> None:
    return None


def connector(url: str, resources: Path = STORY, **kw: Any) -> CloudWatchConnector:
    kw.setdefault("sleep", no_sleep)
    return CloudWatchConnector(
        region="us-east-1",
        resources=load_resources(resources),
        limits=kw.pop("limits", Limits()),
        auth_mode="fixture",
        local_endpoint_url=url,
        **kw,
    )


def settings(url: str, resources: Path = STORY, **over: Any) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        cloudwatch_enabled=True,
        cloudwatch_region="us-east-1",
        cloudwatch_auth_mode="fixture",
        cloudwatch_local_endpoint_url=url,
        cloudwatch_resources_file=resources,
        **over,
    )


def registry(url: str, resources: Path = STORY, **over: Any) -> ConnectorRegistry:
    return ConnectorRegistry.from_settings(settings(url, resources, **over))
