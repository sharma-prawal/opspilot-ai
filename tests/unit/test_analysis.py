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


def test_detect_shift_down_and_recovered() -> None:
    from opspilot_agents.analysis import detect_shift

    drop = series([1150.0] * 60 + [120.0, 110.0, 100.0, 95.0])
    s = detect_shift(drop, metric="events_processed_per_min", unit="events/min")
    assert s is not None and s.direction == "down" and not s.recovered
    blip = series([0.003] * 60 + [0.04, 0.05, 0.04, 0.003, 0.002, 0.003, 0.003])
    b = detect_shift(blip, metric="http_5xx_ratio", unit="ratio")
    assert b is not None and b.direction == "up" and b.recovered


def test_lexical_overlap_bonus() -> None:
    from opspilot_agents.analysis import lexical_overlap_bonus

    bonus, shared = lexical_overlap_bonus(
        "rename currency to currency_code in payment events", ["'currency' is a required property"]
    )
    assert bonus == 0.1 and shared == ["currency"]
    assert lexical_overlap_bonus("update docs", ["timeout"])[0] == 0.0


def test_zero_baseline_count_noise_is_not_an_onset() -> None:
    """Regression: retries of 0/1/2 per minute triggered a false onset when the baseline median was 0."""
    import random

    from opspilot_agents.analysis import detect_shift

    rng = random.Random(3)
    noise = series([float(rng.choice([0, 0, 1, 2])) for _ in range(120)])
    assert detect_shift(noise, metric="consumer_retries_per_min", unit="attempts/min") is None
    real = series([float(rng.choice([0, 0, 1, 2])) for _ in range(100)] + [220.0, 226.0, 224.0, 221.0])
    s = detect_shift(real, metric="consumer_retries_per_min", unit="attempts/min")
    assert s is not None and s.onset == T0 + timedelta(minutes=100)
