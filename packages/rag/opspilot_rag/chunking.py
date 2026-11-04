"""Heading-aware Markdown chunking with paragraph-boundary splitting and word overlap."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class Chunk:
    ordinal: int
    heading_path: str
    content: str
    word_count: int


def _sections(body: str) -> list[tuple[str, str]]:
    stack: list[tuple[int, str]] = []
    sections: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            sections.append((" > ".join(h for _, h in stack), text))
        buf.clear()

    for line in body.split("\n"):
        m = _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
        else:
            buf.append(line)
    flush()
    return sections


def _split_long(text: str, max_words: int, overlap: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    current: list[str] = []
    for para in paragraphs:
        words = para.split()
        if current and len(current) + len(words) > max_words:
            pieces.append(" ".join(current))
            current = current[-overlap:] if overlap else []
        current.extend(words)
        while len(current) > max_words:  # a single paragraph longer than the window
            pieces.append(" ".join(current[:max_words]))
            current = current[max_words - overlap :] if overlap else current[max_words:]
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_markdown(body: str, *, max_words: int, overlap_words: int) -> list[Chunk]:
    if overlap_words >= max_words:
        raise ValueError("overlap must be smaller than max chunk size")
    chunks: list[Chunk] = []
    for heading_path, text in _sections(body):
        parts = [text] if len(text.split()) <= max_words else _split_long(text, max_words, overlap_words)
        for part in parts:
            chunks.append(Chunk(len(chunks), heading_path, part, len(part.split())))
    return chunks


def embedding_text(title: str, heading_path: str, content: str) -> str:
    """Text actually embedded: title + heading path give short sections their context."""
    return f"{title}\n{heading_path}\n\n{content}" if heading_path else f"{title}\n\n{content}"
