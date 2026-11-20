"""Evidence-state checks for read-only RCAs (v0.9).

A model can turn *missing* change history into a *negative* finding ("no deployment or configuration change caused
the fault"). Seen in the first synthetic Datadog run with qwen3.5:9b-q4_K_M, although the digest said change history
was unknown and the logs showed inventory-service 3.8.0 starting four minutes before the onset. This module keeps four
evidence states apart:

- **observed**: an event appears in collected evidence (e.g. a version or configuration line in the logs);
- **contradicting**: collected evidence the model cites against a hypothesis;
- **searched, none found**: a source was read and matched nothing;
- **not collected**: the source was unavailable, so nothing can be concluded from its absence.

``check_hypotheses`` flags any hypothesis that asserts that no change occurred while change history was not collected.
It does not delete or re-rank anything. It only annotates (``evidence_warnings``), so the report can state the
limitation. Deterministic and independent of the prompt.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

CHANGE_TOOLS = ("list_recent_deployments", "get_config_changes")

# Terms that make a log line a possible change observation (provider-side filter, then the regex below).
CHANGE_TERMS = ("version", "start", "deploy", "rollout", "release", "config", "restart", "shutdown", "migrat")
_CHANGE_LINE = re.compile(
    r"(?i)\b(version|v?\d+\.\d+\.\d+|deploy(?:ed|ing|ment)?|rollout|release[ds]?|config(?:uration)?|restart(?:ed|ing)?"
    r"|start(?:ing|ed)|shut(?:ting)?\s?down|migrat\w*)\b"
)

_CHANGE_NOUN = (
    r"(?:deployments?|deploys?|releases?|rollouts?|upgrades?|(?:configuration|config|code|schema|software) changes?"
    r"|changes?)"
)
_QUAL = r"(?:(?:recent|internal|related|relevant|new|known|other|prior|such|any|a|an|or|and|deployment|configuration"
_QUAL += r"|config|code)\s+)*"
_NEGATIVE_CHANGE = [
    # "no internal deployment or configuration change caused ...", "no recent changes" (not "no change history")
    re.compile(
        rf"(?i)\bno\s+{_QUAL}{_CHANGE_NOUN}\b(?![\w\s/-]{{0,30}}\b(?:history|evidence|data|records?|information"
        r"|logs?|events?\s+(?:was|were)\s+(?:collected|available)|could\s+be\s+(?:read|collected)|unknown|unavailable)\b)"
    ),
    re.compile(r"(?i)\bnothing\s+(?:was\s+|has\s+been\s+)?(?:changed|deployed)\b"),
    re.compile(rf"(?i)\bwithout\s+{_QUAL}{_CHANGE_NOUN}\b"),
    re.compile(
        rf"(?i)\bnot\s+(?:caused|triggered|introduced|related\s+to|due\s+to|attributable\s+to)\s+(?:by\s+)?"
        rf"{_QUAL}{_CHANGE_NOUN}\b"
    ),
    re.compile(rf"(?i)\brul(?:e|es|ed|ing)\s+out\s+{_QUAL}{_CHANGE_NOUN}\b"),
    re.compile(rf"(?i)\b{_CHANGE_NOUN}\s+(?:can\s+be|are|is|were|was|has\s+been|have\s+been)\s+ruled\s+out\b"),
    re.compile(r"(?i)\b(?:no|zero)\s+(?:internal\s+)?changes?\s+(?:occurred|happened|took\s+place|were\s+made)\b"),
]


def is_change_observation(message: str) -> bool:
    """True when a log line mentions a version, start/stop, deployment, rollout, release, migration or config."""
    return bool(_CHANGE_LINE.search(message or ""))


# A phrase governed by inability, purpose or a question states a gap, not a finding: "change history unavailable to
# rule out recent changes", "we cannot rule out a deployment", "whether no change occurred" (real qwen3.5 output).
_HEDGE = re.compile(
    r"(?i)\b(?:cannot|can\s*not|can't|could\s+not|couldn't|unable|unavailable|not\s+possible|impossible|needed|"
    r"need|needs|required|requires|insufficient|whether|if|to\s+confirm|to\s+determine|not\s+enough)\b[\w\s,'-]{0,25}$"
    r"|\bto\s*$"
)


def negative_change_claims(text: str) -> list[str]:
    """Phrases in ``text`` asserting that no change occurred or that changes are ruled out."""
    found: list[str] = []
    for pattern in _NEGATIVE_CHANGE:
        for m in pattern.finditer(text or ""):
            if _HEDGE.search((text or "")[max(0, m.start() - 40) : m.start()]):
                continue
            phrase = " ".join(m.group(0).split())
            if phrase not in found:
                found.append(phrase)
    return found


def change_history_unread(state: Mapping[str, Any]) -> list[str]:
    """Change tools that failed when no change evidence exists: change history was not collected (unknown)."""
    evidence = state.get("evidence") or {}
    if any(e.get("kind") in ("deployment", "config_change") for e in evidence.values()):
        return []
    return sorted(
        {
            str(c.get("tool"))
            for c in state.get("tool_calls") or []
            if c.get("tool") in CHANGE_TOOLS and c.get("status") != "ok"
        }
    )


def change_observations(evidence: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Change observations found in collected logs (version/start/config lines), oldest first."""
    rows = [
        {
            "evidence_id": e["id"],
            "service": e.get("service"),
            "first_seen": e["data"].get("first_seen"),
            "line": str(e["data"].get("sample") or "")[:200],
        }
        for e in evidence.values()
        if e.get("kind") == "log_pattern" and (e.get("data") or {}).get("change_observation")
    ]
    return sorted(rows, key=lambda r: (str(r["first_seen"]), str(r["evidence_id"])))


def _observed_text(observed: list[dict[str, Any]]) -> str:
    if not observed:
        return "no change event was found in the collected logs either, which is absence of evidence only"
    shown = "; ".join(
        f"{o['service']} at {str(o['first_seen'])[11:16]}Z: '{o['line'][:100]}' ({o['evidence_id']})"
        for o in observed[:3]
    )
    return f"the collected logs show possible change events: {shown}"


def check_hypotheses(hypotheses: list[dict[str, Any]], state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Annotate hypotheses that claim no change occurred while change history was not collected."""
    unread = change_history_unread(state)
    if not unread:
        return hypotheses
    observed = change_observations(state.get("evidence") or {})
    for h in hypotheses:
        claims = negative_change_claims(f"{h.get('title', '')}. {h.get('description', '')}")
        if claims:
            h["evidence_warnings"] = [
                f"Unsupported claim ('{claims[0]}'): deployment and configuration-change history was not collected "
                f"({', '.join(unread)} unavailable), so whether a change happened is unknown; "
                + _observed_text(observed)
                + "."
            ]
    return hypotheses


def summary_warnings(summary: str, state: Mapping[str, Any]) -> list[str]:
    unread = change_history_unread(state)
    claims = negative_change_claims(summary) if unread else []
    if not claims:
        return []
    return [
        f"The summary states '{claims[0]}', but change history was not collected; whether a change happened is unknown."
    ]
