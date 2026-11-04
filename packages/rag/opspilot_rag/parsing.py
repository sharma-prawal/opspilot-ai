"""Document discovery, parsing and normalisation. One ``Parser`` per file format."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from opspilot_shared.domain.knowledge import DocType
from opspilot_shared.errors import ValidationFailure

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    source_uri: str
    title: str
    doc_type: DocType
    body: str
    services: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _meta(raw: dict[str, Any], source_uri: str) -> tuple[str, DocType, list[str], list[str], dict[str, Any]]:
    try:
        title = str(raw["title"]).strip()
        doc_type = DocType(str(raw["doc_type"]))
    except (KeyError, ValueError) as exc:
        raise ValidationFailure(f"{source_uri}: missing/invalid title or doc_type ({exc})") from exc
    services = sorted({str(s) for s in raw.get("services") or []})
    tags = sorted({str(t) for t in raw.get("tags") or []})
    extra = {k: v for k, v in raw.items() if k not in {"title", "doc_type", "services", "tags", "codes"}}
    return title, doc_type, services, tags, json.loads(json.dumps(extra, default=str))


class Parser(Protocol):
    suffixes: tuple[str, ...]

    def parse(self, source_uri: str, raw: str) -> ParsedDocument: ...


class MarkdownParser:
    suffixes: tuple[str, ...] = (".md", ".markdown")

    def parse(self, source_uri: str, raw: str) -> ParsedDocument:
        match = _FRONT_MATTER.match(raw)
        if not match:
            raise ValidationFailure(f"{source_uri}: markdown documents require YAML front matter")
        front = yaml.safe_load(match.group(1)) or {}
        title, doc_type, services, tags, extra = _meta(front, source_uri)
        return ParsedDocument(source_uri, title, doc_type, normalize_text(raw[match.end() :]), services, tags, extra)


class JsonParser:
    """Renders structured JSON (e.g. the error catalogue) into heading-structured text."""

    suffixes: tuple[str, ...] = (".json",)

    def parse(self, source_uri: str, raw: str) -> ParsedDocument:
        data = json.loads(raw)
        title, doc_type, services, tags, extra = _meta(data, source_uri)
        lines = [f"# {title}", ""]
        for item in data.get("codes", []):
            lines.append(f"## {item.get('code', 'entry')}")
            for key, value in item.items():
                if key != "code" and value is not None:
                    lines.append(f"- {key.replace('_', ' ')}: {value}")
            lines.append("")
        return ParsedDocument(source_uri, title, doc_type, normalize_text("\n".join(lines)), services, tags, extra)


PARSERS: tuple[Parser, ...] = (MarkdownParser(), JsonParser())


def parser_for(path: Path) -> Parser | None:
    return next((p for p in PARSERS if path.suffix.lower() in p.suffixes), None)


def discover(root: Path) -> list[Path]:
    """Supported files under ``root``; archive folders last so canonical copies win dedup."""
    files = [p for p in root.rglob("*") if p.is_file() and parser_for(p) is not None]
    return sorted(files, key=lambda p: ("archive" in p.relative_to(root).parts, str(p.relative_to(root))))
