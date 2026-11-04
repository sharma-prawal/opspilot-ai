import pytest

from opspilot_rag.chunking import chunk_markdown, embedding_text
from opspilot_rag.parsing import JsonParser, MarkdownParser, normalize_text
from opspilot_shared.domain.knowledge import DocType
from opspilot_shared.errors import ValidationFailure

MD = """---
title: Example
doc_type: runbook
services: [b-svc, a-svc]
tags: [x]
version: 2
---
# Example

Intro paragraph.

## Step one

Do the thing.

## Step two

### Detail

Deep detail.
"""


def test_markdown_front_matter_and_normalisation() -> None:
    doc = MarkdownParser().parse("runbooks/example.md", MD.replace("\n", "\r\n"))
    assert doc.title == "Example" and doc.doc_type is DocType.RUNBOOK
    assert doc.services == ["a-svc", "b-svc"]  # sorted, deterministic hash input
    assert doc.metadata == {"version": 2}
    assert "\r" not in doc.body and doc.body.endswith("\n")


def test_markdown_requires_front_matter() -> None:
    with pytest.raises(ValidationFailure):
        MarkdownParser().parse("x.md", "# no front matter")


def test_invalid_doc_type_rejected() -> None:
    with pytest.raises(ValidationFailure):
        MarkdownParser().parse("x.md", "---\ntitle: t\ndoc_type: bogus\n---\nbody")


def test_heading_paths_are_tracked() -> None:
    doc = MarkdownParser().parse("x.md", MD)
    chunks = chunk_markdown(doc.body, max_words=50, overlap_words=5)
    paths = [c.heading_path for c in chunks]
    assert paths == ["Example", "Example > Step one", "Example > Step two > Detail"]
    assert [c.ordinal for c in chunks] == [0, 1, 2]


def test_long_sections_split_with_overlap() -> None:
    body = "# T\n\n" + "\n\n".join(" ".join(f"w{p}_{i}" for i in range(30)) for p in range(5))
    chunks = chunk_markdown(body, max_words=60, overlap_words=10)
    assert len(chunks) >= 3 and all(c.word_count <= 60 for c in chunks)
    first, second = chunks[0].content.split(), chunks[1].content.split()
    assert first[-10:] == second[:10]  # overlap preserved


def test_overlap_must_be_smaller_than_window() -> None:
    with pytest.raises(ValueError):
        chunk_markdown("# a\n\nb", max_words=10, overlap_words=10)


def test_json_parser_renders_codes() -> None:
    raw = '{"title":"Codes","doc_type":"error_catalog","codes":[{"code":"E1","meaning":"bad","http_status":null}]}'
    doc = JsonParser().parse("e.json", raw)
    assert "## E1" in doc.body and "meaning: bad" in doc.body and "http status" not in doc.body


def test_embedding_text_includes_context() -> None:
    assert embedding_text("T", "A > B", "body").startswith("T\nA > B")


def test_normalize_is_idempotent() -> None:
    once = normalize_text("a  \n\n\n\nb\r\n")
    assert normalize_text(once) == once == "a\n\nb\n"
