"""Deterministic outcome classification and RCA report rendering from structured state.

The narrative summary comes from the RCA model output; everything else (outcome, timeline, evidence,
citations, actions, verification) is derived from recorded data, so the report cannot cite evidence
that was never collected or claim an action that did not happen.
"""

from __future__ import annotations

from typing import Any

OUTCOMES = {
    "mitigated": "Remediation executed and recovery verified.",
    "not_recovered": "Remediation executed but recovery was NOT verified.",
    "remediation_failed": "A remediation step failed to execute.",
    "remediation_rejected": "The operator rejected the proposed remediation.",
    "approval_expired": "The approval request expired before a decision.",
    "proposal_blocked": "Every proposed action was blocked by safety validation.",
    "escalated": "No automated action; escalated to a human owner.",
    "inconclusive": "Evidence was insufficient to determine the cause; escalated.",
    "no_action_required": "Impact has ended and no action is required.",
    "no_action_proposed": "Impact is ongoing but no catalogue action applies; escalated.",
    "impact_unknown": "Impact could not be established from the available evidence; escalated.",
    "verification_incomplete": "Remediation executed but not every recovery condition could be checked; escalated.",
    "failed": "The investigation did not complete.",
}
ESCALATE = {
    "not_recovered",
    "remediation_failed",
    "remediation_rejected",
    "approval_expired",
    "proposal_blocked",
    "escalated",
    "inconclusive",
    "no_action_proposed",
    "impact_unknown",
    "verification_incomplete",
    "failed",
}


def impact_state(rca: dict[str, Any]) -> str:
    """Impact state recorded by the RCA node. Legacy records without it are treated conservatively."""
    impact = rca.get("impact")
    if isinstance(impact, dict) and impact.get("state"):
        return str(impact["state"])
    return "ongoing" if rca.get("impact_ongoing") else "unknown"


def determine_outcome(state: dict[str, Any], confidence_threshold: float = 0.6) -> dict[str, Any]:
    rca = state.get("rca") or {}
    approval = state.get("approval") or {}
    executions = state.get("executions") or []
    plan = state.get("remediation_plan") or []
    esc = rca.get("escalation") or {}
    hyps = rca.get("hypotheses") or []
    top = hyps[0]["confidence"] if hyps else 0.0
    impact = impact_state(rca)
    verification = state.get("verification") or {}
    withheld = [r for r in state.get("rejected_proposals") or [] if r.get("category") == "withheld_uncertain"]
    if state.get("status") == "failed":
        code = "failed"
    elif approval.get("decision") == "expired":
        code = "approval_expired"
    elif approval.get("decision") == "reject":
        code = "remediation_rejected"
    elif executions:
        if executions[-1].get("status") != "succeeded":
            code = "remediation_failed"
        elif verification.get("status") == "recovered" or (
            "status" not in verification and verification.get("recovered")
        ):
            code = "mitigated"
        elif verification.get("status") == "incomplete":
            code = "verification_incomplete"
        else:
            code = "not_recovered"
    elif esc.get("required"):  # an explicit escalation request is never overridden
        code = "escalated"
    elif impact == "recovered":  # requires affirmative, sufficient recovery evidence
        code = "no_action_required"
    elif impact == "unknown":
        code = "impact_unknown"
    elif withheld:  # a valid plan existed but the diagnosis was too uncertain to propose it
        code = "inconclusive"
    elif rca.get("remediation_plan") and not plan:
        code = "proposal_blocked"
    elif top < confidence_threshold:
        code = "inconclusive"
    else:
        code = "no_action_proposed"
    reason = esc.get("reason") or OUTCOMES[code]
    if code == "inconclusive" and withheld:
        reason = withheld[0]["reason"]
    if code == "impact_unknown":
        reason = "; ".join((rca.get("impact") or {}).get("reasons") or [OUTCOMES[code]])
    return {
        "code": code,
        "summary": OUTCOMES[code],
        "escalate": code in ESCALATE,
        "escalate_to": esc.get("to") or None,
        "reason": reason,
        "actions_executed": len(executions),
        "steps_planned": len(plan),
        "impact": impact,
    }


def _one_line(text: str, limit: int = 220) -> str:
    flat = " ".join(text.replace("|", "/").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _ts(value: str | None) -> str:
    return value.replace("T", " ").replace("+00:00", "Z")[:20] if value else "—"


def render_report(state: dict[str, Any]) -> str:
    inc = state.get("incident") or {}
    rca = state.get("rca") or {}
    ev = state.get("evidence") or {}
    w = state.get("window") or {}
    outcome = state.get("outcome") or determine_outcome(state)
    hyps = rca.get("hypotheses") or []
    lines = [f"# RCA: {inc.get('reference', '')} — {inc.get('title', 'Incident')}", ""]
    lines += [
        f"- **Outcome:** `{outcome['code']}` — {outcome['summary']}  ",
        f"- **Service:** {inc.get('service')}  ",
        f"- **Severity:** {inc.get('severity')}  ",
        f"- **Detected:** {_ts(inc.get('detected_at'))}  ",
        f"- **Anomaly onset:** {_ts(w.get('onset'))}  ",
        f"- **Investigation status:** {state.get('status')}  ",
    ]
    if hyps:
        lines.append(f"- **Root-cause category (RCA):** {hyps[0]['category']}  ")
    cls = state.get("classification") or {}
    lines += [f"- **Initial triage (alert only):** {cls.get('category')} ({cls.get('source')})", ""]

    if outcome.get("escalate"):
        lines += [
            "## Escalation",
            "",
            "**Human follow-up required**"
            + (f" — owner: {outcome['escalate_to']}" if outcome.get("escalate_to") else "")
            + ".",
            "",
            outcome["reason"],
            "",
        ]
    if rca.get("summary"):
        lines += ["## Summary", "", rca["summary"], ""]
        if rca.get("impact"):
            imp = rca["impact"]
            lines += [f"Impact at analysis time: **{imp['state']}** — {'; '.join(imp.get('reasons') or [])}.", ""]
    if hyps:
        lines += ["## Ranked hypotheses", ""]
        for h in hyps:
            lines.append(f"### {h['rank']}. {h['title']} — confidence {h['confidence']:.0%}")
            lines += ["", f"*Category:* `{h['category']}`", "", h["description"], "", "Supporting evidence:"]
            lines += [f"- `{i}` — {_one_line(ev[i]['summary'])}" for i in h["supporting_evidence_ids"] if i in ev]
            if h.get("contradicting_evidence_ids"):
                lines.append("Contradicting evidence:")
                lines += [
                    f"- `{i}` — {_one_line(ev[i]['summary'])}" for i in h["contradicting_evidence_ids"] if i in ev
                ]
            lines.append("")
    if rca.get("citation_violations"):
        lines += [
            f"> Note: the model cited {len(rca['citation_violations'])} evidence ID(s) that do not exist; "
            "they were discarded: " + ", ".join(f"`{v}`" for v in rca["citation_violations"]),
            "",
        ]

    timeline: list[tuple[str, str]] = []
    for e in ev.values():
        if e["kind"] in ("deployment", "config_change") and e["relevance"] >= 0.2:
            timeline.append((e.get("observed_at") or "", e["summary"][:160]))
        if e["kind"] == "metric_anomaly" and e["data"].get("onset"):
            timeline.append((e["data"]["onset"], e["summary"][:160]))
        if e["kind"] == "log_pattern" and e["data"]["level"] == "ERROR":
            timeline.append((e["data"]["first_seen"], f"first error on {e['service']}: {e['data']['sample'][:120]}"))
    if inc.get("detected_at"):
        timeline.append((inc["detected_at"], "alert fired / incident detected"))
    if timeline:
        lines += ["## Timeline", "", "| Time (UTC) | Event |", "|---|---|"]
        lines += [f"| {_ts(t)} | {_one_line(d, 200)} |" for t, d in sorted(timeline)]
        lines.append("")

    lines += ["## Remediation", ""]
    plan = state.get("remediation_plan") or []
    executions = {x.get("step"): x for x in state.get("executions") or []}
    approval = state.get("approval") or {}
    if plan:
        lines += ["| Step | Action | Role | Parameters | Result |", "|---|---|---|---|---|"]
        for p in plan:
            x = executions.get(p["step"])
            result = (
                f"{x.get('status')}: {_one_line(str(x.get('message', '')), 90)}"
                if x
                else (
                    f"not executed ({approval.get('decision')})"
                    if approval.get("decision") in ("reject", "expired")
                    and p["step"] >= (state.get("plan_index", 0) + 1)
                    else "not executed"
                )
            )
            lines.append(
                f"| {p['step']} | `{p['action_type']}` | {p.get('role', '')} | "
                f"{_one_line(str(p['parameters']), 80)} | {result} |"
            )
        lines.append("")
        if approval:
            lines.append(
                f"- **Last decision:** {approval.get('decision')} by {approval.get('decided_by')} at "
                f"{_ts(approval.get('decided_at'))}"
                + (f" — “{approval['comment']}”" if approval.get("comment") else "")
            )
        ver = state.get("verification")
        if ver:
            lines.append(
                f"- **Verification:** {'recovered' if ver.get('recovered') else 'NOT recovered'} — {ver.get('notes')}"
            )
    else:
        lines.append("- No remediation executed or proposed for approval.")
    for r in state.get("rejected_proposals") or []:
        lines.append(
            f"- Blocked model proposal `{r['proposal'].get('action_type')}` "
            f"({r.get('category') or 'invalid'}): {r['reason']}"
        )
    lines.append("")

    if rca.get("evidence_gaps"):
        lines += ["## Evidence gaps", ""] + [f"- {g}" for g in rca["evidence_gaps"]] + [""]
    tool_errors = [e for e in ev.values() if e["kind"] == "tool_error"]
    if tool_errors:
        lines += ["## Tool failures during the investigation", ""] + [f"- {e['summary']}" for e in tool_errors] + [""]

    cited = [e for e in ev.values() if e.get("citation")]
    if cited:
        lines += ["## Knowledge sources", ""]
        seen: set[str] = set()
        for e in sorted(cited, key=lambda e: -e["relevance"]):
            c = e["citation"]
            if c["chunk_id"] in seen:
                continue
            seen.add(c["chunk_id"])
            status = e["data"].get("doc_status")
            snapshot = (
                f", v{c['document_version']}, sha256 `{c['passage_sha256'][:12]}`" if c.get("passage_sha256") else ""
            )
            lines.append(
                f"- `{e['id']}` {c['title']} > {c['heading_path']} (`{c['source_uri']}`, chunk "
                f"`{c['chunk_id'][:8]}`{snapshot})" + (f" — **{status}**" if status and status != "current" else "")
            )
        lines.append("")

    tc, lc = state.get("tool_calls") or [], state.get("llm_calls") or []
    lines += [
        "## Investigation trace",
        "",
        f"- Tool calls: {len(tc)} ({sum(1 for t in tc if t['status'] != 'ok')} non-ok), "
        f"total tool latency {sum(t['latency_ms'] for t in tc) / 1000:.1f}s",
        f"- LLM calls: {len(lc)}, total {sum(c['latency_ms'] for c in lc) / 1000:.1f}s, "
        f"tokens in/out {sum(c.get('prompt_tokens') or 0 for c in lc)}/"
        f"{sum(c.get('completion_tokens') or 0 for c in lc)}",
        f"- Evidence items: {len(ev)}; rounds: {state.get('rounds', 0) + (1 if rca else 0)}",
    ]
    for err in state.get("errors") or []:
        lines.append(f"- Error [{err['error_class']}] in {err['node']}: {err['message'][:200]}")
    return "\n".join(lines) + "\n"
