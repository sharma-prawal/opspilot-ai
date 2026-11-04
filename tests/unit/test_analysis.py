from datetime import UTC, datetime, timedelta

from opspilot_agents.analysis import change_correlation, cluster_logs, detect_onset, signature

T0 = datetime(2026, 1, 1, 12, tzinfo=UTC)


def series(values: list[float]) -> list[tuple[datetime, float]]:
    return [(T0 + timedelta(minutes=i), v) for i, v in enumerate(values)]


def test_detects_sustained_onset() -> None:
    pts = series([0.003] * 60 + [0.01, 0.4, 0.38, 0.41, 0.39])
    an = detect_onset(pts, min_abs_increase=0.02)
    assert an is not None and an.onset == T0 + timedelta(minutes=61)
    assert an.peak == 0.41 and an.baseline == 0.003


def test_ignores_single_spike() -> None:
    assert detect_onset(series([0.003] * 60 + [0.5, 0.003, 0.003, 0.003]), min_abs_increase=0.02) is None


def test_signature_normalises_ids_and_numbers() -> None:
    a = signature("payment 3f1e2b0c-1111-4222-8333-944445555666 failed in 120ms")
    b = signature("payment 00000000-1111-4222-8333-944445555666 failed in 98ms")
    assert a == b == "payment <uuid> failed in <n>"


def test_cluster_ranks_errors_first() -> None:
    entries = [{"ts": T0.isoformat(), "level": "WARN", "message": "slow 1", "attributes": {}} for _ in range(10)]
    entries += [
        {
            "ts": (T0 + timedelta(seconds=i)).isoformat(),
            "level": "ERROR",
            "message": f"upstream ledger-service returned 500 #{i}",
            "attributes": {"code": "X"},
        }
        for i in range(3)
    ]
    groups = cluster_logs(entries)
    assert groups[0].level == "ERROR" and groups[0].count == 3
    assert groups[0].upstream == "ledger-service" and groups[0].attributes == {"code": "X"}


def test_change_correlation_prefers_recent_related_schema_change() -> None:
    onset = T0
    near = change_correlation(
        onset - timedelta(minutes=1),
        onset,
        change_service="ledger",
        affected_services={"ledger"},
        related_services=set(),
        schema_change=True,
        schema_signals=True,
    )
    old = change_correlation(
        onset - timedelta(hours=2),
        onset,
        change_service="api",
        affected_services={"ledger"},
        related_services={"api"},
        schema_change=False,
        schema_signals=True,
    )
    after = change_correlation(
        onset + timedelta(minutes=10),
        onset,
        change_service="ledger",
        affected_services={"ledger"},
        related_services=set(),
        schema_change=False,
        schema_signals=False,
    )
    assert near > 0.9 and old < 0.05 and after == 0.0
