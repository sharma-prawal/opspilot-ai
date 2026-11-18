"""Generate the synthetic example files for "Analyze your own incident data" (v0.5).

Deterministic (fixed seed). Writes to apps/web/public/examples/uploads/ so the web UI can offer them for download.
The story: payment-service 2.14.0 is deployed at 09:12Z; from 09:14Z checkout-api payments time out against it.
An unrelated search-api deployment two hours earlier is included so the agent has to discriminate.

Usage: uv run python scripts/generate_upload_examples.py
"""

from __future__ import annotations

import csv
import io
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "apps/web/public/examples/uploads"
T0 = datetime(2026, 11, 12, 8, 30, tzinfo=UTC)
DEPLOY = datetime(2026, 11, 12, 9, 12, 20, tzinfo=UTC)
ONSET = datetime(2026, 11, 12, 9, 14, tzinfo=UTC)
END = datetime(2026, 11, 12, 9, 45, tzinfo=UTC)
rng = random.Random(20261112)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def hexid(n: int) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


def logs() -> str:
    lines: list[str] = []
    t = T0
    while t < END:
        t += timedelta(seconds=rng.randint(20, 50))
        after = t >= ONSET
        trace = hexid(32)
        if after and rng.random() < 0.7:
            ms = rng.randint(2000, 2100)
            lines.append(
                f"{iso(t)} ERROR [http-nio-8080-exec-{rng.randint(1, 9)}] PaymentClient - payment authorization "
                f"failed: upstream=payment-service status=504 timeout after {ms} ms "
                f"order_id=ord-{rng.randint(10000, 99999)} "
                f"trace_id={trace}"
            )
            if rng.random() < 0.3:
                lines.append("java.net.SocketTimeoutException: Read timed out")
                lines.append("\tat com.example.checkout.payment.PaymentClient.authorize(PaymentClient.java:118)")
                lines.append("\tat com.example.checkout.CheckoutService.placeOrder(CheckoutService.java:74)")
        elif after and rng.random() < 0.5:
            lines.append(
                f"{iso(t)} WARN  [http-nio-8080-exec-{rng.randint(1, 9)}] PaymentClient - retrying payment "
                f"authorization (attempt 2/2) upstream=payment-service trace_id={trace}"
            )
        else:
            lines.append(
                f"{iso(t)} INFO  [http-nio-8080-exec-{rng.randint(1, 9)}] CheckoutController - POST /api/checkout "
                f"-> 200 in {rng.randint(80, 190)} ms trace_id={trace}"
            )
        if t > datetime(2026, 11, 12, 8, 41, tzinfo=UTC) and len(lines) == 20:
            # a credential that must never reach storage or the model (redacted on upload)
            lines.append(
                f"{iso(t)} DEBUG [main] VaultConfig - refreshed client credentials token=sk_test_EXAMPLE0000000"
            )
    return "\n".join(lines) + "\n"


def metrics() -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["timestamp", "service", "http_5xx_ratio", "p95_latency_ms", "http_requests_per_min"])
    t = T0
    while t <= END:
        after = t >= ONSET
        ramp = min(1.0, max(0.0, (t - ONSET).total_seconds() / 240)) if after else 0.0
        w.writerow(
            [
                iso(t),
                "checkout-api",
                f"{0.002 + rng.random() * 0.002 + ramp * (0.16 + rng.random() * 0.03):.4f}",
                f"{180 + rng.randint(-15, 15) + ramp * (1900 + rng.randint(-60, 60)):.0f}",
                f"{420 + rng.randint(-25, 25)}",
            ]
        )
        w.writerow(
            [
                iso(t),
                "payment-service",
                f"{0.001 + rng.random() * 0.001 + ramp * (0.11 + rng.random() * 0.03):.4f}",
                f"{95 + rng.randint(-10, 10) + ramp * (2300 + rng.randint(-80, 80)):.0f}",
                f"{400 + rng.randint(-25, 25)}",
            ]
        )
        t += timedelta(minutes=1)
    return buf.getvalue()


def events() -> str:
    items = [
        {
            "timestamp": "2026-11-12T07:05:41Z",
            "type": "deployment",
            "service": "search-api",
            "id": "deploy-7702",
            "version": "5.3.1",
            "previous_version": "5.3.0",
            "status": "succeeded",
            "author": "ci-bot",
            "summary": "search-api 5.3.1: ranking tweak for related products",
        },
        {
            "timestamp": iso(DEPLOY),
            "type": "deployment",
            "service": "payment-service",
            "id": "deploy-7731",
            "version": "2.14.0",
            "previous_version": "2.13.4",
            "status": "succeeded",
            "author": "ci-bot",
            "summary": "payment-service 2.14.0: upgrade card-vault client; outbound HTTP pool max size 50 -> 5",
        },
        {
            "timestamp": "2026-11-12T09:16:30Z",
            "type": "alert",
            "service": "checkout-api",
            "summary": "CheckoutErrorRateHigh: 5xx ratio above 5% for 2 minutes",
            "severity": "critical",
        },
    ]
    return json.dumps({"events": items}, indent=2) + "\n"


def _span(trace: str, span: str, parent: str, name: str, kind: int, start: datetime, ms: int, error: str | None):
    s = {
        "traceId": trace,
        "spanId": span,
        "name": name,
        "kind": kind,
        "startTimeUnixNano": str(int(start.timestamp() * 1e9)),
        "endTimeUnixNano": str(int((start + timedelta(milliseconds=ms)).timestamp() * 1e9)),
        "status": {"code": 2, "message": error} if error else {"code": 1},
        "attributes": [{"key": "http.method", "value": {"stringValue": "POST"}}],
    }
    if parent:
        s["parentSpanId"] = parent
    return s


def traces() -> str:
    checkout: list[dict] = []
    payment: list[dict] = []
    for i in range(8):
        start = (T0 + timedelta(minutes=12 * i + 3)) if i < 3 else (ONSET + timedelta(minutes=3 * (i - 3) + 1))
        failing = i >= 3
        trace, root, client, server = hexid(32), hexid(16), hexid(16), hexid(16)
        ms = 2050 if failing else rng.randint(110, 170)
        checkout.append(
            _span(
                trace,
                root,
                "",
                "POST /api/checkout",
                2,
                start,
                ms + 15,
                "payment authorization failed" if failing else None,
            )
        )
        client_span = _span(
            trace,
            client,
            root,
            "POST payment-service /v1/charges",
            3,
            start + timedelta(milliseconds=5),
            ms,
            "504 Gateway Timeout" if failing else None,
        )
        client_span["attributes"].append({"key": "peer.service", "value": {"stringValue": "payment-service"}})
        checkout.append(client_span)
        payment.append(
            _span(
                trace,
                server,
                client,
                "POST /v1/charges",
                2,
                start + timedelta(milliseconds=8),
                ms - 10,
                "card-vault client: connection pool exhausted (max 5)" if failing else None,
            )
        )

    def resource(service: str, spans: list[dict]) -> dict:
        return {
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
            "scopeSpans": [{"scope": {"name": "example"}, "spans": spans}],
        }

    return (
        json.dumps(
            {"resourceSpans": [resource("checkout-api", checkout), resource("payment-service", payment)]}, indent=1
        )
        + "\n"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in (
        ("checkout-api.log", logs()),
        ("service-metrics.csv", metrics()),
        ("change-events.json", events()),
        ("checkout-traces.json", traces()),
    ):
        (OUT / name).write_text(text, encoding="utf-8")
        print(f"wrote {OUT / name} ({len(text.encode())} bytes)")


if __name__ == "__main__":
    main()
