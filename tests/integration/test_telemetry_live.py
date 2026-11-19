"""v0.6: the connectors against the real local Loki and Prometheus of ``make telemetry-up`` (synthetic data).

Skipped unless both answer on 127.0.0.1 (LOKI_PORT / PROMETHEUS_PORT, defaults 3310 / 9390). Verifies the request
formats and response shapes of the official APIs end to end, including the multi-tenant auth error.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx
import pytest

from opspilot_shared.config import Settings
from opspilot_shared.connectors.contract import FetchWindow
from opspilot_shared.connectors.registry import ConnectorRegistry
from opspilot_shared.connectors.snapshot import SourceSelection, collect

LOKI = f"http://127.0.0.1:{os.environ.get('LOKI_PORT', '3310')}"
PROM = f"http://127.0.0.1:{os.environ.get('PROMETHEUS_PORT', '9390')}"
W = FetchWindow(start=datetime(2026, 11, 12, 7, 30, tzinfo=UTC), end=datetime(2026, 11, 12, 9, 45, tzinfo=UTC))


def _up() -> bool:
    try:
        return httpx.get(f"{LOKI}/ready", timeout=1).status_code == 200 and (
            httpx.get(f"{PROM}/-/ready", timeout=1).status_code == 200
        )
    except httpx.HTTPError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _up(), reason="local Loki/Prometheus not running (make telemetry-up)"),
]


def registry(**over: object) -> ConnectorRegistry:
    values: dict[str, object] = {
        "loki_url": LOKI,
        "loki_tenant_id": "opspilot-demo",
        "prometheus_url": PROM,
        "telemetry_templates_file": "infra/telemetry/query-templates.json",
        **over,
    }
    s = Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]
    return ConnectorRegistry.from_settings(s)


async def test_real_backends_answer_and_report_auth_errors() -> None:
    reg = registry()
    loki, prom = await reg.get("loki").test(), await reg.get("prometheus").test()
    assert loki.status == "ok" and loki.version and prom.status == "ok" and prom.version
    no_tenant = await registry(loki_tenant_id="").get("loki").test()
    assert no_tenant.status == "auth_error" and "no org id" in no_tenant.message
    assert await reg.get("prometheus").services(W) == ["checkout-api", "payment-service", "search-api"]


async def test_real_snapshot_shows_the_synthetic_incident() -> None:
    sources = [
        SourceSelection("loki", ("errors_warnings", "lifecycle")),
        SourceSelection("prometheus", ("http_5xx_ratio", "p95_latency_ms", "db_pool_in_use", "db_pool_max")),
    ]
    snap = await collect(registry(), sources, ["checkout-api", "payment-service"], W)
    assert all(q.status in ("ok", "empty") for q in snap.queries), [q.error for q in snap.queries]
    d = snap.dataset
    ratio = sorted(
        (m for m in d.metrics if m.metric == "http_5xx_ratio" and m.service == "checkout-api"), key=lambda m: m.ts
    )
    before = [m.value for m in ratio if m.ts < datetime(2026, 11, 12, 9, 13, tzinfo=UTC)]
    after = [m.value for m in ratio if m.ts > datetime(2026, 11, 12, 9, 20, tzinfo=UTC)]
    assert before and after and max(before) < 0.02 and min(after) > 0.25
    p95 = [
        m.value for m in d.metrics if m.metric == "p95_latency_ms" and m.ts > datetime(2026, 11, 12, 9, 20, tzinfo=UTC)
    ]
    assert p95 and min(p95) > 1000 and {m.unit for m in d.metrics if m.metric == "p95_latency_ms"} == {"ms"}
    pool = {m.value for m in d.metrics if m.metric == "db_pool_max" and m.service == "payment-service"}
    assert pool == {10.0, 50.0}
    assert any("version=2.14.0" in r.message for r in d.logs)
    assert snap.redactions() == 1 and not any("sk_test_EXAMPLE" in r.message for r in d.logs)
    err = next(r for r in d.logs if r.level == "ERROR" and r.service == "payment-service")
    assert err.ts_original.isdigit() and err.source.startswith("loki/errors_warnings/payment-service:entry")
