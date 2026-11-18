"""Synthetic telemetry for the local Loki/Prometheus test setup (v0.6).

Deterministic (fixed seed, fixed timeline). Writes, under ``var/telemetry/`` (git-ignored):

- ``prometheus/seed.om``: OpenMetrics text that Prometheus backfills with ``promtool tsdb create-blocks-from
  openmetrics`` when its container starts (``infra/telemetry/prometheus-start.sh``);
- ``loki/push.json``: a Loki push request (``POST /loki/api/v1/push``), sent by ``--push``.

The story (same incident as the v0.5 upload example, told only through logs and metrics): payment-service 2.14.0
starts at 09:12:20Z with a smaller database pool; from 09:14Z its authorizations wait for connections and fail, and
checkout-api payments time out against it. search-api restarts with a new version at 08:31Z and stays healthy (a
change that is unrelated). Everything is synthetic; one fake credential is logged so that redaction can be seen.

Usage:
    uv run python scripts/generate_telemetry.py                 # write the files
    uv run python scripts/generate_telemetry.py --push URL --tenant ID   # write, then push the logs to Loki
"""

from __future__ import annotations

import argparse
import json
import random
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var/telemetry"
START = datetime(2026, 11, 12, 8, 0, tzinfo=UTC)
END = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
SEARCH_DEPLOY = datetime(2026, 11, 12, 8, 31, 5, tzinfo=UTC)
PAY_DEPLOY = datetime(2026, 11, 12, 9, 12, 20, tzinfo=UTC)
ONSET = datetime(2026, 11, 12, 9, 14, tzinfo=UTC)
STEP = 15  # seconds between metric samples
BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)
SERVICES = ("checkout-api", "payment-service", "search-api")
rng = random.Random(20261112)


def ns(dt: datetime) -> str:
    delta = dt - datetime(1970, 1, 1, tzinfo=UTC)  # exact integer arithmetic (no float rounding)
    return str((delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000)


def hexid(n: int) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


# --------------------------------------------------------------------------------------------------- metrics
def _profile(svc: str, t: datetime) -> tuple[float, float, float]:
    """(requests per second, 5xx fraction, slow fraction) for a service at time t."""
    after = t >= ONSET
    if svc == "checkout-api":
        return 40.0, (0.33 if after else 0.004), (0.55 if after else 0.03)
    if svc == "payment-service":
        return 38.0, (0.52 if after else 0.003), (0.65 if after else 0.02)
    restarting = SEARCH_DEPLOY <= t < SEARCH_DEPLOY + timedelta(seconds=45)
    return 22.0, (0.02 if restarting else 0.002), 0.01


def _latency_bucket_fractions(slow: float) -> list[float]:
    """Cumulative fraction of requests at or below each bucket bound."""
    fast = 1.0 - slow
    return [fast * 0.35, fast * 0.7, fast * 0.95, fast, fast + slow * 0.05, fast + slow * 0.3, 1.0, 1.0]


def prometheus_seed() -> str:
    times = []
    t = START
    while t <= END:
        times.append(t)
        t += timedelta(seconds=STEP)
    req: dict[tuple[str, str], float] = {}
    hist: dict[str, list[float]] = {svc: [0.0] * (len(BUCKETS) + 1) for svc in SERVICES}
    hsum: dict[str, float] = dict.fromkeys(SERVICES, 0.0)
    pool: dict[str, tuple[float, float]] = {}
    rows_req: list[str] = []
    rows_hist: list[str] = []
    rows_pool: list[str] = []
    for t in times:
        ts = f"{t.timestamp():.3f}"
        for svc in SERVICES:
            rps, err, slow = _profile(svc, t)
            n = rps * STEP * rng.uniform(0.93, 1.07)
            bad = n * err
            code = "504" if svc == "checkout-api" else "503"
            req[(svc, "200")] = req.get((svc, "200"), 0.0) + (n - bad)
            req[(svc, code)] = req.get((svc, code), 0.0) + bad
            fractions = _latency_bucket_fractions(slow)
            for i, f in enumerate(fractions):
                hist[svc][i] += n * f
            hsum[svc] += n * ((1 - slow) * 0.09 + slow * 2.2)
            for status in ("200", code):
                rows_req.append(
                    f'http_requests_total{{service="{svc}",status="{status}",env="demo"}} '
                    f"{req.get((svc, status), 0.0):.0f} {ts}"
                )
            for i, le in enumerate([*BUCKETS, "+Inf"]):
                rows_hist.append(
                    f'http_request_duration_seconds_bucket{{service="{svc}",env="demo",le="{le}"}} '
                    f"{hist[svc][i]:.0f} {ts}"
                )
            rows_hist.append(
                f'http_request_duration_seconds_count{{service="{svc}",env="demo"}} {hist[svc][-1]:.0f} {ts}'
            )
            rows_hist.append(f'http_request_duration_seconds_sum{{service="{svc}",env="demo"}} {hsum[svc]:.3f} {ts}')
        size = 10.0 if t >= PAY_DEPLOY else 50.0
        used = size if t >= ONSET else rng.uniform(6, 12)
        pool["payment-service"] = (used, size)
        rows_pool.append(f'db_pool_connections_in_use{{service="payment-service",env="demo"}} {used:.0f} {ts}')
        rows_pool.append(f'db_pool_connections_max{{service="payment-service",env="demo"}} {size:.0f} {ts}')
    return "\n".join(
        [
            "# HELP http_requests Requests handled, by service and HTTP status.",
            "# TYPE http_requests counter",
            *rows_req,
            "# HELP http_request_duration_seconds Request latency.",
            "# TYPE http_request_duration_seconds histogram",
            "# UNIT http_request_duration_seconds seconds",
            *rows_hist,
            "# HELP db_pool_connections_in_use Database connections checked out.",
            "# TYPE db_pool_connections_in_use gauge",
            *[r for r in rows_pool if r.startswith("db_pool_connections_in_use")],
            "# HELP db_pool_connections_max Database connection pool size.",
            "# TYPE db_pool_connections_max gauge",
            *[r for r in rows_pool if r.startswith("db_pool_connections_max")],
            "# EOF",
            "",
        ]
    )


# ------------------------------------------------------------------------------------------------------ logs
def _line(level: str, msg: str, **kv: object) -> str:
    parts = [f"level={level}", f'msg="{msg}"'] + [f"{k}={v}" for k, v in kv.items()]
    return " ".join(parts)


def loki_streams() -> list[dict[str, object]]:
    values: dict[str, list[tuple[datetime, str]]] = {svc: [] for svc in SERVICES}
    t = START
    while t < END:
        t += timedelta(seconds=rng.randint(8, 16))
        after = t >= ONSET
        trace = hexid(32)
        order = f"ord-{rng.randint(10000, 99999)}"
        if after and rng.random() < 0.65:
            values["checkout-api"].append(
                (
                    t,
                    _line(
                        "error",
                        "payment authorization failed",
                        upstream="payment-service",
                        status=504,
                        duration_ms=rng.randint(2000, 2090),
                        order_id=order,
                        trace_id=trace,
                    ),
                )
            )
            values["payment-service"].append(
                (
                    t - timedelta(milliseconds=rng.randint(5, 40)),
                    _line(
                        "error",
                        "authorize failed: timed out waiting for a database connection",
                        pool="payments-db",
                        wait_ms=2000,
                        pool_in_use=10,
                        pool_max=10,
                        trace_id=trace,
                    ),
                )
            )
        elif after and rng.random() < 0.5:
            values["checkout-api"].append(
                (
                    t,
                    _line(
                        "warn",
                        "retrying payment authorization",
                        attempt="2/2",
                        upstream="payment-service",
                        trace_id=trace,
                    ),
                )
            )
            values["payment-service"].append(
                (
                    t,
                    _line(
                        "warn",
                        "database pool exhausted, request queued",
                        pool="payments-db",
                        waiting=rng.randint(20, 60),
                    ),
                )
            )
        else:
            values["checkout-api"].append(
                (t, _line("info", "order placed", order_id=order, duration_ms=rng.randint(60, 180), trace_id=trace))
            )
            values["payment-service"].append(
                (t, _line("info", "payment authorized", duration_ms=rng.randint(30, 90), trace_id=trace))
            )
        if rng.random() < 0.6:
            values["search-api"].append(
                (t, _line("info", "search served", results=rng.randint(0, 40), duration_ms=rng.randint(15, 70)))
            )
    values["search-api"] += [
        (SEARCH_DEPLOY - timedelta(seconds=4), _line("info", "shutting down", version="4.2.0")),
        (SEARCH_DEPLOY, _line("info", "starting search-api", version="4.2.1", index="products-v7")),
        (SEARCH_DEPLOY + timedelta(seconds=20), _line("warn", "cache warm-up slow", duration_ms=1800)),
    ]
    values["payment-service"] += [
        (PAY_DEPLOY - timedelta(seconds=6), _line("info", "shutting down", version="2.13.4")),
        (
            PAY_DEPLOY,
            _line("info", "starting payment-service", version="2.14.0", db_pool_max=10, previous_db_pool_max=50),
        ),
        (
            PAY_DEPLOY + timedelta(seconds=2),
            # synthetic fake credential: OpsPilot must redact it before storing or showing the line
            _line("info", "loaded gateway client config", gateway="card-gateway", api_key="sk_test_EXAMPLE0000000"),
        ),
    ]
    return [
        {
            "stream": {"service_name": svc, "env": "demo", "namespace": "shop"},
            "values": [[ns(ts), line] for ts, line in sorted(values[svc])],
        }
        for svc in SERVICES
    ]


def push(url: str, tenant: str | None, payload: dict[str, object]) -> None:
    headers = {"Content-Type": "application/json"}
    if tenant:
        headers["X-Scope-OrgID"] = tenant
    if not url.startswith(("http://127.0.0.1", "http://localhost")):
        raise SystemExit("refusing to push synthetic logs anywhere but a local Loki")
    req = urllib.request.Request(  # noqa: S310 - local test Loki only (checked above)
        url.rstrip("/") + "/loki/api/v1/push", data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - local test Loki only
        if resp.status not in (200, 204):
            raise SystemExit(f"Loki push failed: HTTP {resp.status}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--push", metavar="LOKI_URL", help="push the generated logs to this local Loki")
    ap.add_argument("--tenant", default=None, help="X-Scope-OrgID for a multi-tenant Loki")
    args = ap.parse_args()
    (OUT / "prometheus").mkdir(parents=True, exist_ok=True)
    (OUT / "loki").mkdir(parents=True, exist_ok=True)
    (OUT / "prometheus/seed.om").write_text(prometheus_seed(), encoding="utf-8")
    payload = {"streams": loki_streams()}
    (OUT / "loki/push.json").write_text(json.dumps(payload), encoding="utf-8")
    lines = sum(len(s["values"]) for s in payload["streams"])  # type: ignore[arg-type]
    print(f"wrote {OUT / 'prometheus/seed.om'} and {OUT / 'loki/push.json'} ({lines} log lines)")
    if args.push:
        push(args.push, args.tenant, payload)
        print(f"pushed {lines} log lines to {args.push}")


if __name__ == "__main__":
    main()
