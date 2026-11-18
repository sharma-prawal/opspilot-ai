"""v0.5: uploaded files are validated and normalized without inventing timestamps, services or telemetry."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opspilot_shared.uploads.model import MAX_FILE_BYTES, MAX_FILES
from opspilot_shared.uploads.parse import UploadError, UploadFile, parse_timestamp, parse_upload, sanitize_name, scrub

EXAMPLES = Path(__file__).resolve().parents[2] / "apps/web/public/examples/uploads"


def one(name: str, content: str, service: str | None = None, tz: str = "UTC"):  # type: ignore[no-untyped-def]
    return parse_upload([UploadFile(name, content, service)], timezone=tz)


def test_example_files_normalize_with_sources() -> None:
    files = [
        UploadFile(p.name, p.read_text(), "checkout-api" if p.suffix == ".log" else None)
        for p in sorted(EXAMPLES.iterdir())
    ]
    d = parse_upload(files)
    by_name = {f.name: f for f in d.files}
    assert by_name["checkout-api.log"].format == "text log" and by_name["checkout-api.log"].records["log"] > 100
    assert by_name["service-metrics.csv"].format == "CSV metrics (wide)"
    assert by_name["change-events.json"].records == {"event": 3}
    assert by_name["checkout-traces.json"].format == "OTLP/JSON traces"
    assert all(f.rejected == 0 for f in d.files)
    err = next(r for r in d.logs if r.level == "ERROR")
    assert err.source.startswith("checkout-api.log:line ") and err.service_source == "file_default"
    assert err.attributes["upstream"] == "payment-service" and err.trace_id
    # the stack trace continues the entry above it instead of being dropped or invented as an entry
    assert any("SocketTimeoutException" in r.message for r in d.logs)
    deploy = next(e for e in d.events if e.attributes.get("id") == "deploy-7731")
    assert deploy.event_type == "deployment" and deploy.service == "payment-service" and deploy.tz == "Z"
    failing = [s for s in d.spans if s.status == "error" and s.service == "payment-service"]
    assert failing and failing[0].duration_ms and failing[0].status_message


def test_credentials_are_redacted_before_storage() -> None:
    d = one(
        "app.log",
        "2026-11-12T08:00:00Z INFO login ok password=hunter2 Authorization: Bearer abcdefghijklmnop\n"
        '{"timestamp": "2026-11-12T08:00:01Z", "message": "connect", "db_password": "s3cret", "service": "api"}\n',
        "api",
    )
    text = json.dumps(d.model_dump(mode="json"))
    assert "hunter2" not in text and "abcdefghijklmnop" not in text and "s3cret" not in text
    assert d.files[0].redactions >= 3 and any("redacted" in w for w in d.warnings)
    assert scrub("api_key=AKIAABCDEFGHIJKLMNOP x")[1] >= 1


def test_csv_metrics_long_and_wide_with_units() -> None:
    wide = one(
        "m.csv",
        "time,service,latency (ms),error_ratio,cpu\n"
        "2026-11-12T09:00:00+01:00,checkout,120,0.01,n/a\n"
        "2026-11-12T09:01:00+01:00,checkout,130,0.02,55\n",
    )
    m = {(r.metric, r.unit) for r in wide.metrics}
    assert ("latency", "ms") in m and ("error_ratio", "ratio") in m and ("cpu", "") in m
    first = wide.metrics[0]
    assert first.ts == datetime(2026, 11, 12, 8, 0, tzinfo=UTC) and first.tz == "+01:00"
    assert first.source == "m.csv:row 2" and first.metric_original == "latency (ms)"
    assert any("non-numeric" in i for i in wide.files[0].issues)  # 'n/a' is skipped, not turned into 0

    long = one(
        "long.csv",
        "timestamp;service;metric;value;unit\n2026-11-12T09:00:00Z;api;p95_latency;812;ms\n"
        "2026-11-12T09:01:00Z;api;p95_latency;oops;ms\n",
    )
    assert long.files[0].format == "CSV metrics (long)" and len(long.metrics) == 1 and long.files[0].rejected == 1
    assert long.metrics[0].unit == "ms"


def test_json_events_logs_spans_and_json_lines() -> None:
    d = one(
        "e.json",
        json.dumps(
            [
                {"ts": 1794473820, "type": "Config Change", "service": "api", "key": "pool", "old": "50", "new": "5"},
                {"@timestamp": "2026-11-12T09:00:00Z", "log": {"level": "error"}, "message": "boom", "service": "api"},
                {
                    "time": "2026-11-12T09:00:00Z",
                    "traceId": "t1",
                    "spanId": "s1",
                    "name": "GET /",
                    "duration_ms": 12,
                    "status": "ERROR",
                    "service": "api",
                },
                {"timestamp": "2026-11-12T09:00:00Z", "metric": "queue_depth", "value": 7, "service": "api"},
                {"timestamp": "2026-11-12T09:00:00Z", "service": "api"},
            ]
        ),
    )
    assert [len(d.events), len(d.logs), len(d.spans), len(d.metrics)] == [1, 1, 1, 1]
    assert d.events[0].event_type == "config_change" and d.events[0].tz == "epoch"
    assert d.logs[0].level == "ERROR" and not d.logs[0].level_inferred
    assert d.spans[0].status == "error" and d.spans[0].duration_ms == 12
    assert d.files[0].rejected == 1 and "item 5" in d.files[0].issues[0]
    jl = one("x.json", '{"timestamp": "2026-11-12T09:00:00Z", "msg": "a", "service": "web"}\n{bad}\n')
    assert jl.files[0].format == "JSON lines" and len(jl.logs) == 1 and jl.files[0].rejected == 1


def test_missing_timestamps_and_services_are_rejected_not_invented() -> None:
    d = one("a.log", "no timestamp here\n2026-11-12 boom without a time\n2026-11-12T09:00:00Z ERROR x\n", "api")
    assert len(d.logs) == 1 and d.files[0].rejected == 2  # neither the lone line nor the date-only one is kept
    assert all("never invented" in i or "timestamp" in i for i in d.files[0].issues)
    assert parse_timestamp("2026-11-12", UTC, "UTC") is None
    naive = one("n.log", "2026-11-12 10:00:00 WARN slow\n", "api", tz="Europe/Berlin")
    assert naive.logs[0].tz == "assumed Europe/Berlin" and naive.logs[0].ts.hour == 9
    nosvc = one("s.log", "2026-11-12T09:00:00Z ERROR x\n")
    assert not nosvc.logs and "no service" in nosvc.files[0].issues[0]
    inferred = one("i.log", "2026-11-12T09:00:00Z payment failed: connection refused\n", "api")
    assert inferred.logs[0].level == "ERROR" and inferred.logs[0].level_inferred


def test_malformed_empty_and_unsupported_inputs() -> None:
    d = parse_upload(
        [
            UploadFile("empty.log", "   \n"),
            UploadFile("bad.json", "{not json"),
            UploadFile("no-ts.csv", "service,value\napi,1\n"),
            UploadFile("bin.txt", "abc\x00def"),
        ]
    )
    issues = {f.name: f.issues[0] for f in d.files}
    assert issues["empty.log"] == "the file is empty"
    assert issues["bad.json"].startswith("not valid JSON")
    assert issues["no-ts.csv"].startswith("no timestamp column")
    assert "binary" in issues["bin.txt"]
    assert not any(f.usable for f in d.files)
    with pytest.raises(UploadError, match="unsupported file type"):
        one("script.sh", "echo hi")
    with pytest.raises(UploadError, match="too many files"):
        parse_upload([UploadFile(f"f{i}.log", "x") for i in range(MAX_FILES + 1)])
    with pytest.raises(UploadError, match="limit"):
        one("big.log", "x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(UploadError, match="timezone"):
        one("a.log", "x", tz="Mars/Olympus")
    with pytest.raises(UploadError, match="not a valid service"):
        one("a.log", "x", service="!!")


def test_file_names_cannot_traverse_paths() -> None:
    assert sanitize_name("../../etc/passwd.log", 0) == ("passwd.log", ".log")
    assert sanitize_name("..\\..\\win\\x y;rm.csv", 1) == ("x_y_rm.csv", ".csv")
    assert sanitize_name(".hidden.json", 2) == ("hidden.json", ".json")
    with pytest.raises(UploadError):
        sanitize_name("evil.log.exe", 0)
    d = parse_upload([UploadFile("a/x.log", "2026-11-12T09:00:00Z ERROR e", "api"), UploadFile("b/x.log", "", None)])
    assert [f.name for f in d.files] == ["x.log", "x-2.log"]  # duplicates stay distinguishable in citations
