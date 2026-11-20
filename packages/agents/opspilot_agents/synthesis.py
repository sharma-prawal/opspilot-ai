"""Deterministic evidence digest placed in front of the RCA prompt (v0.4).

The published qwen3:8b traces showed that the facts deciding an incident were already in the evidence but were
ignored by the model: a 5xx blip that had "returned to baseline (recovered)" still got a rollback of a deployment
with correlation 0.00 (NEG-001); errors naming an unhealthy external provider were blamed on an unrelated deployment
(NEG-002); two near-equally correlated changes with the ledger logs unavailable produced a 0.95-confidence answer
and no evidence gap (NEG-003). See docs/evaluation/MODEL_COMPARISON_V0.4.md.

This module restates, in a few lines, what the investigation code has already computed from the evidence: impact
state, change correlation ranking, which dependency the errors name, and which evidence is missing. It collects no
new evidence and makes no decision; the deterministic plan gates in ``remediation.py`` still decide what can be
proposed. Thresholds are imported from there so the digest and the gates cannot disagree.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opspilot_agents.claims import change_observations
from opspilot_agents.impact import assess_impact
from opspilot_agents.remediation import AMBIGUITY_MARGIN, MIN_ROLLBACK_CORRELATION

STRONG_CORRELATION = 0.5  # same bar the ambiguity gate uses for a rival change
CHANGE_TOOLS = ("list_recent_deployments", "get_config_changes")
ATTRIBUTION_SHARE = 0.8  # share of a service's ERROR logs naming one upstream before it is "attributed"


def _corr(e: dict[str, Any]) -> float:
    return float(e["data"].get("correlation") or 0.0)


def evidence_digest(state: Mapping[str, Any]) -> dict[str, Any]:
    evidence: dict[str, dict[str, Any]] = state.get("evidence", {})
    notes: list[str] = []

    impact = assess_impact(dict(state))
    if impact.state.value == "recovered":
        notes.append("impact has already ended: the affected service is back to baseline and healthy")
    elif impact.state.value == "unknown":
        notes.append("impact cannot be determined from the evidence collected")

    changes = sorted(
        (e for e in evidence.values() if e["kind"] in ("deployment", "config_change")),
        key=lambda e: (-_corr(e), e["id"]),
    )
    change_rows = [
        {
            "evidence_id": e["id"],
            "change_id": e["data"].get("id"),
            "kind": e["kind"],
            "service": e["data"].get("service"),
            "minutes_before_onset": e["data"].get("minutes_before_onset"),
            "correlation": round(_corr(e), 2),
        }
        for e in changes[:5]
    ]
    correlated = [c for c in change_rows if c["correlation"] >= MIN_ROLLBACK_CORRELATION]
    if changes and not correlated:
        notes.append(
            f"no change in the window correlates with the anomaly onset (all below {MIN_ROLLBACK_CORRELATION}); "
            "a change is not a suspect just because it exists"
        )
    strong = [c for c in change_rows if c["correlation"] >= STRONG_CORRELATION]
    if len(strong) >= 2 and strong[0]["correlation"] - strong[1]["correlation"] < AMBIGUITY_MARGIN:
        notes.append(
            f"{strong[0]['change_id']} ({strong[0]['correlation']}) and {strong[1]['change_id']} "
            f"({strong[1]['correlation']}) are similarly correlated with the onset; the evidence does not single "
            "out one of them"
        )
    changed_services = {c["service"] for c in correlated}

    unhealthy: list[dict[str, Any]] = []
    for e in evidence.values():
        if e["kind"] != "dependency":
            continue
        health = e["data"].get("health") or {}
        if health.get("status") in ("unhealthy", "degraded"):
            external = next((n for n in health.get("notes", []) if "external" in n.lower()), None)
            unhealthy.append(
                {
                    "evidence_id": e["id"],
                    "service": health.get("service"),
                    "status": health.get("status"),
                    "external": external,
                    "changed_in_window": health.get("service") in changed_services,
                }
            )

    attribution: list[dict[str, Any]] = []
    totals: dict[str, int] = {}
    by_upstream: dict[str, dict[str, int]] = {}
    ids: dict[tuple[str, str], list[str]] = {}
    for e in evidence.values():
        if e["kind"] == "log_pattern" and e["data"].get("level") == "ERROR" and e.get("service"):
            svc, n = e["service"], int(e["data"].get("count") or 0)
            totals[svc] = totals.get(svc, 0) + n
            up = (e["data"].get("attributes") or {}).get("upstream")
            if up and up != svc:
                by_upstream.setdefault(svc, {})[up] = by_upstream.setdefault(svc, {}).get(up, 0) + n
                ids.setdefault((svc, up), []).append(e["id"])
    for svc, ups in sorted(by_upstream.items()):
        for up, n in sorted(ups.items(), key=lambda kv: -kv[1]):
            share = n / totals[svc] if totals.get(svc) else 0.0
            attribution.append(
                {
                    "service": svc,
                    "upstream": up,
                    "errors": n,
                    "of": totals[svc],
                    "share": round(share, 2),
                    "evidence_ids": ids.get((svc, up), []),
                }
            )
            dep = next((u for u in unhealthy if u["service"] == up), None)
            if share >= ATTRIBUTION_SHARE and dep and not dep["changed_in_window"]:
                notes.append(
                    f"{n}/{totals[svc]} {svc} errors name {up}, which is {dep['status']} and had no change in the "
                    "window" + (f" ({dep['external']})" if dep["external"] else "")
                )
            elif share >= ATTRIBUTION_SHARE and up in changed_services:
                # state the changed case too, so a model cannot mistake it for an unchanged dependency (v0.4)
                changed = ", ".join(f"{c['change_id']} ({c['correlation']})" for c in correlated if c["service"] == up)
                notes.append(f"{n}/{totals[svc]} {svc} errors name {up}, which changed in the window: {changed}")

    missing = [e["summary"][:200] for e in evidence.values() if e["kind"] == "tool_error"]
    if missing:
        notes.append(f"{len(missing)} evidence source(s) could not be read; conclusions that depend on them are open")
    # v0.6: an empty change list must not read as "nothing changed" when the change history itself was unavailable
    # (connected telemetry has none). Only added in that case, so digests with readable change history are unchanged.
    unread = sorted(
        {
            str(c.get("tool"))
            for c in state.get("tool_calls") or []
            if c.get("tool") in CHANGE_TOOLS and c.get("status") != "ok"
        }
    )
    change_history_unknown = bool(unread) and not changes
    observed = change_observations(evidence) if change_history_unknown else []
    if change_history_unknown:
        notes.insert(
            0,
            "change history (deployments, config changes) could not be read: whether anything changed in the window "
            "is UNKNOWN; do not state that no change occurred",
        )
        if observed:  # v0.9: logs that show a change are evidence that one occurred, even without a change history
            shown = "; ".join(
                f"{o['service']} at {str(o['first_seen'])[11:16]}Z: {o['line'][:120]} ({o['evidence_id']})"
                for o in observed[:3]
            )
            notes.insert(
                1,
                f"the logs show possible change events in the window: {shown}. Treat them as observed events and "
                "weigh them as candidate causes; never write that no deployment or configuration change occurred",
            )

    queues = [
        {
            "queue": e["data"].get("queue"),
            "consumer": (e["data"].get("consumer") or {}).get("service"),
            "consumer_state": (e["data"].get("consumer") or {}).get("state"),
            "observed_error_codes": sorted({f["error_code"] for f in e["data"].get("failures", [])}),
            "dead_lettered": e["data"].get("dead_lettered"),
        }
        for e in evidence.values()
        if e["kind"] == "queue"
    ]
    for q in queues:
        if not q["observed_error_codes"] and not q["dead_lettered"]:
            notes.append(
                f"queue {q['queue']} has no failed or dead-lettered messages (consumer {q['consumer']} "
                f"{q['consumer_state']}): queue actions do not apply to it"
            )
        else:
            notes.append(
                f"queue {q['queue']} holds {q['dead_lettered']} dead-lettered message(s) with error code(s) "
                f"{', '.join(q['observed_error_codes']) or 'unknown'}; reverting the producer does not remove them"
            )

    # Key findings first: small models weight what they read first (v0.4 traces).
    digest: dict[str, Any] = {
        "key_findings": notes,
        "impact": {"state": impact.state.value, "reasons": impact.reasons},
        "changes_by_correlation": change_rows,
        "unhealthy_dependencies": unhealthy,
        "error_attribution": attribution,
        "missing_evidence": missing,
        "queues": queues,
    }
    if change_history_unknown:
        digest["change_history"] = (
            f"unavailable ({', '.join(unread)} failed); changes_by_correlation is empty because nothing could be read"
        )
        if observed:
            digest["observed_change_events"] = observed[:5]
    return digest
