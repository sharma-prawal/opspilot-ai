"""JSON-schema helpers for constrained decoding."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel


def inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema with ``$ref``/``$defs`` inlined.

    Grammar-constrained decoders handle flat schemas most reliably, so references are expanded.
    """
    schema = model.model_json_schema()
    defs: dict[str, Any] = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                merged = {**copy.deepcopy(defs[name]), **{k: v for k, v in node.items() if k != "$ref"}}
                return resolve(merged)
            # Drop pydantic's string "title" annotations, but keep a *property* named "title"
            # (inside "properties" the value is a schema dict, not a string).
            return {k: resolve(v) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)  # type: ignore[no-any-return]
