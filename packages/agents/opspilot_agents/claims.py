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

from opspilot_agents.prompts import is_connected, is_read_only

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


# ---------------------------------------------------------------------------------------------------------------------
# v0.10 claim calibration for read-only (uploaded or connected) RCAs. Nothing in a stored-evidence analysis verifies a
# cause independently: it is a ranked set of evidence-supported hypotheses. These checks never edit or re-rank the
# model's text; they add deterministic notes so the report and UI keep four things apart: observed telemetry facts,
# evidence-supported hypotheses, verified conclusions (none here) and unknown/unavailable evidence. Simulator
# investigations are not annotated (their prompts, outputs and evaluation are unchanged).

# "The root cause is …", "… was caused by …", "confirmed", "definitively" (real qwen3.5 output: "The root cause is a
# configuration change …"). Not "appears to be", "likely", "may", "suggests".
_CERTAIN = [
    re.compile(
        r"(?i)\b(?:the\s+)?(?:root\s+)?cause\s+(?:of\s+[\w\s'-]{1,40}?\s+)?(?:is|was)\b(?!\s+(?:likely|probably|"
        r"possibly|unclear|unknown|not|uncertain|undetermined|still|most\s+likely|plausibly))"
    ),
    re.compile(r"(?i)\b(?:is|was|were|are)\s+(?:directly\s+|definitely\s+|clearly\s+)?caused\s+by\b"),
    re.compile(r"(?i)\b(?:confirmed|proven|definitively|conclusively|undoubtedly|certainly)\b"),
]
_UNCERTAIN = re.compile(
    r"(?i)\b(?:likely|probabl[ey]|possibl[ey]|may|might|could|appears?|seems?|suggests?|hypothes\w*|potential(?:ly)?|"
    r"plausibl[ey]|if|whether|not|unverified|cannot|can't|unable|consistent\s+with|candidate)\b[\w\s,'-]{0,30}$"
)
# Deployment or configuration-change wording (the model's word for an observed start-up or configuration line).
_CHANGE_WORDING = re.compile(
    r"(?i)\b(?:(?:the|a|new|recent)\s+)?(?:deployment|deployed|rollout|rolled\s+out|release[ds]?|"
    r"(?:configuration|config)\s+change)\b"
)
_HEDGED_CHANGE = re.compile(r"(?i)\b(?:possible|potential|observed|logged|log|indicat\w*|apparent)\s+$")
# Words that describe the state of the incident as if it were current.
_CURRENT_STATE = re.compile(
    r"(?i)\b(?:ongoing|still\s+(?:failing|occurring|happening|degraded|down)|is\s+continuing|"
    r"continues|has\s+not\s+recovered|no\s+recovery)\b"
)
# Suggested actions that do not change persisted configuration, and the hypotheses they would leave in place.
_NO_CONFIG_CHANGE_ACTIONS = ("restart_service",)


def certainty_claims(text: str) -> list[str]:
    """Phrases stating a cause as an established fact (not hedged as likely, possible, apparent …)."""
    found: list[str] = []
    for pattern in _CERTAIN:
        for m in pattern.finditer(text or ""):
            if _UNCERTAIN.search((text or "")[max(0, m.start() - 40) : m.start()]):
                continue
            phrase = " ".join(m.group(0).split())
            if phrase.lower() not in (f.lower() for f in found):
                found.append(phrase)
    return found


def _observation_ids(evidence: Mapping[str, Mapping[str, Any]], ids: list[str] | None = None) -> list[str]:
    pool = ids if ids is not None else list(evidence)
    return [i for i in pool if ((evidence.get(i) or {}).get("data") or {}).get("change_observation")]


def change_wording(text: str) -> list[str]:
    """Deployment or configuration-change wording that is not itself hedged as an observation or possibility."""
    found: list[str] = []
    for m in _CHANGE_WORDING.finditer(text or ""):
        if _HEDGED_CHANGE.search((text or "")[max(0, m.start() - 20) : m.start()]):
            continue
        phrase = " ".join(m.group(0).split())
        if phrase.lower() not in (f.lower() for f in found):
            found.append(phrase)
    return found


def _change_note(phrase: str, obs: list[str], evidence: Mapping[str, Mapping[str, Any]]) -> str:
    lines = "; ".join(
        f"{i}: '{str(((evidence.get(i) or {}).get('data') or {}).get('sample') or '')[:80]}'" for i in obs[:2]
    )
    return (
        f"Change indicator, not change history ('{phrase}'): the cited change evidence is a log line observed in the "
        f"collected telemetry ({lines}). It is not a verified deployment or configuration-change record (that history "
        "was not collected) and it is not proof of cause."
    )


def snapshot_end(state: Mapping[str, Any]) -> str | None:
    """End of the collected evidence: the latest query window end of a connector snapshot, else the analysis window."""
    inc = state.get("incident") or {}
    ends = [str(q.get("end")) for q in inc.get("telemetry_queries") or [] if isinstance(q, dict) and q.get("end")]
    if ends:
        return max(ends)
    end = (state.get("window") or {}).get("end")
    return str(end) if end else None


def _hhmm(ts: str | None) -> str:
    return f"{ts[:10]} {ts[11:16]}Z" if ts and len(ts) >= 16 else "the end of the collected window"


def calibrate_hypotheses(hypotheses: list[dict[str, Any]], state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read-only RCAs: note hypotheses stated as established cause, and change wording resting only on log
    observations while change history was not collected. Appends to ``evidence_warnings``; never edits the text."""
    if not is_read_only(state.get("incident")):
        return hypotheses
    evidence = state.get("evidence") or {}
    unread = change_history_unread(state)
    for h in hypotheses:
        text = f"{h.get('title', '')}. {h.get('description', '')}"
        notes: list[str] = []
        certain = certainty_claims(text)
        if certain:
            notes.append(
                f"Stated as established ('{certain[0]}'): no cause was independently verified in this read-only "
                f"analysis. This is an evidence-supported hypothesis (model-estimated confidence "
                f"{float(h.get('confidence') or 0):.0%}, uncalibrated)."
            )
        obs = _observation_ids(evidence, list(h.get("supporting_evidence_ids") or []))
        wording = change_wording(text) if unread and obs else []
        if wording:
            notes.append(_change_note(wording[0], obs, evidence))
        if notes:
            h["evidence_warnings"] = [*(h.get("evidence_warnings") or []), *notes]
    return hypotheses


def calibration_summary_warnings(summary: str, state: Mapping[str, Any]) -> list[str]:
    """Read-only RCAs: notes for a summary that states a cause as fact, presents a log line as change history, or
    describes the incident as currently ongoing."""
    inc = state.get("incident")
    if not is_read_only(inc):
        return []
    evidence = state.get("evidence") or {}
    out: list[str] = []
    certain = certainty_claims(summary)
    if certain:
        out.append(
            f"The summary states a cause as established ('{certain[0]}'). No causal conclusion was independently "
            "verified in this read-only analysis: the ranked hypotheses below are evidence-supported explanations with "
            "uncalibrated model-estimated confidence."
        )
    obs = _observation_ids(evidence)
    named = [i for i in obs if i in (summary or "")]  # the observations the summary itself names, when it names any
    obs = named or obs
    wording = change_wording(summary) if change_history_unread(state) and obs else []
    if wording:
        out.append(_change_note(wording[0], obs, evidence))
    if _CURRENT_STATE.search(summary or ""):
        where = "collected snapshot window" if is_connected(inc) else "uploaded evidence"
        out.append(
            f"'Ongoing' describes the end of the {where} ({_hhmm(snapshot_end(state))}), not the current live state, "
            "which this analysis did not observe."
        )
    return out


def suggestion_limitations(step: Mapping[str, Any], state: Mapping[str, Any]) -> list[str]:
    """Read-only suggestions: what a suggested action would not address under the leading hypothesis."""
    if step.get("action_type") not in _NO_CONFIG_CHANGE_ACTIONS:
        return []
    hyps = (state.get("rca") or {}).get("hypotheses") or []
    top = hyps[0] if hyps else {}
    evidence = state.get("evidence") or {}
    obs = _observation_ids(evidence, list(top.get("supporting_evidence_ids") or []))
    config_obs = [i for i in obs if re.search(r"(?i)\bconfig", str(evidence[i]["data"].get("sample") or ""))]
    if top.get("category") != "configuration_error" and not config_obs:
        return []
    cited = f" (observed in {', '.join(config_obs[:2])})" if config_obs else ""
    return [
        f"A restart reloads the configuration that is currently persisted. If the configuration named by hypothesis 1"
        f"{cited} is still in place, restarting alone does not correct it: the configuration must be corrected or "
        "reverted by its owner first. A restart is containment at most, not a fix."
    ]
