import uuid

from opspilot_rag.retrieval import keyword_query, rrf_fuse


def test_keyword_query_or_combines_and_sanitises() -> None:
    q = keyword_query("UndefinedColumn: 'amount' & !drop | ledger_entries <-> amount")
    assert q == "undefinedcolumn | amount | drop | ledger_entries"
    for bad in "&!:'<>()":
        assert bad not in q


def test_keyword_query_empty() -> None:
    assert keyword_query("? ! .") is None


def test_rrf_rewards_agreement() -> None:
    a, b, c = (uuid.uuid4() for _ in range(3))
    scores = rrf_fuse([[a, b, c], [b, a]], k=60)
    assert scores[a] == scores[b] > scores[c]
    assert abs(scores[a] - (1 / 61 + 1 / 62)) < 1e-12
