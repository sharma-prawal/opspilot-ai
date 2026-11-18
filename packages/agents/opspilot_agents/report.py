"""Deterministic outcome classification and RCA report rendering from structured state.

The narrative summary comes from the RCA model output; everything else (outcome, timeline, evidence,
citations, actions, verification) is derived from recorded data, so the report cannot cite evidence
that was never collected or claim an action that did not happen.
"""

from __future__ import annotations

import re
from typing import Any

from opspilot_agents.prompts import is_uploaded
from opspilot_agents.verification import CONTRACT as VERIFICATION_CONTRACT
from opspilot_agents.verification import condition_key, required_conditions

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
    # v0.5 read-only analysis of uploaded files: findings and suggestions only, never execution or verified recovery
    "analysis_complete": "Read-only analysis of uploaded evidence: nothing was executed and recovery was not verified.",
    "analysis_inconclusive": "Read-only analysis of uploaded evidence was inconclusive; more evidence is needed.",
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
    "analysis_inconclusive",
}


def impact_state(rca: dict[str, Any]) -> str:
    """Impact state recorded by the RCA node. Legacy records without it are treated conservatively."""
    impact = rca.get("impact")
    if isinstance(impact, dict) and impact.get("state"):
        return str(impact["state"])
    return "ongoing" if rca.get("impact_ongoing") else "unknown"


def verified_recovered(verification: dict[str, Any], state: dict[str, Any] | None = None) -> bool:
    """C0-F1/C0-G1 invariant, enforced again at outcome time: "recovered" needs every required condition to have
    passed. A record claiming recovery with a failed, unknown or unchecked condition is not trusted.

    For records written under the C0-G contract the required conditions are *re-derived* from the recorded state
    (``verification.required_conditions``), so recovery also fails closed if condition generation was ever
    incomplete: every re-derived condition must have a passed check. Without the state to re-derive from, a C0-G
    record is not trusted."""
    if "status" not in verification:  # legacy (pre-C0) record: only the boolean exists
        return bool(verification.get("recovered"))
    if verification.get("status") != "recovered":
        return False
    checks = verification.get("checks") or []
    if not checks or any(c.get("status") != "passed" for c in checks):
        return False
    required = verification.get("required")
    if isinstance(required, int) and len(checks) < required:
        return False
    if verification.get("contract") != VERIFICATION_CONTRACT:
        return True  # C0-F record: count/status invariant above (documented legacy path)
    if not state or not state.get("incident"):
        return False
    passed = {condition_key(c.get("kind"), c.get("service"), c.get("name"), c.get("evidence_id")) for c in checks}
    req = required_conditions(state)
    return all(condition_key(c.kind, c.service, c.name, c.evidence_id) in passed for c in req.conditions)


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
    uploaded = is_uploaded(state.get("incident"))
    if state.get("status") == "failed":
        code = "failed"
    elif uploaded:  # no environment: never an executed, verified, resolved or "no action required" outcome
        confident = hyps and top >= confidence_threshold and not withheld
        code = "analysis_complete" if confident else "analysis_inconclusive"
    elif approval.get("decision") == "expired":
        code = "approval_expired"
    elif approval.get("decision") == "reject":
        code = "remediation_rejected"
    elif executions:
        if executions[-1].get("status") != "succeeded":
            code = "remediation_failed"
        elif verified_recovered(verification, state):
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
    if code == "analysis_inconclusive" and not withheld and not esc.get("reason"):
        reason = (
            f"top hypothesis confidence {top:.0%} is below {confidence_threshold:.0%}"
            if hyps
            else "no hypothesis could be supported by the uploaded evidence"
        )
    if code == "analysis_complete" and not esc.get("reason"):
        reason = (
            f"Most likely cause (model-estimated {top:.0%}, uncalibrated): {hyps[0]['title']}. Verify it in your "
            "environment; any remediation is for a human to carry out outside OpsPilot."
        )
    extra: dict[str, Any] = {}
    if uploaded:
        extra = {"read_only": True, "suggested_steps": len(state.get("suggested_remediation") or [])}
    return {
        **extra,
        "code": code,
        "summary": OUTCOMES[code],
        "escalate": code in ESCALATE or (uploaded and bool(esc.get("required"))),
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
    if not value:
        return "—"
    return re.sub(r"\.\d+", "", value).replace("T", " ").replace("+00:00", "Z")[:20]


def render_report(state: dict[str, Any]) -> str:
    inc = state.get("incident") or {}
    rca = state.get("rca") or {}
    ev = state.get("evidence") or {}
    w = state.get("window") or {}
    outcome = state.get("outcome") or determine_outcome(state)
    hyps = rca.get("hypotheses") or []
    lines = [f"# RCA: {inc.get('reference', '')} — {inc.get('title', 'Incident')}", ""]
    uploaded = is_uploaded(inc)
    if uploaded:
        lines += [
            "> **Uploaded evidence — read-only analysis.** Findings come only from the files the user uploaded. "
            "No action was executed and recovery was not verified; live state was not observed.",
            "",
        ]
    lines += [
        f"- **Outcome:** `{outcome['code']}` — {outcome['summary']}  ",
        f"- **Service:** {inc.get('service')}  ",
        f"- **Severity:** {inc.get('severity')}  ",
        f"- **Detected:** {_ts(inc.get('detected_at'))}  ",
        f"- **Anomaly onset:** {_ts(w.get('onset'))}  ",
        f"- **Investigation status:** {state.get('status')}  ",
    ]
    if uploaded and inc.get("affected_services"):
        lines.append(f"- **Affected services (declared):** {', '.join(inc['affected_services'])}  ")
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
        lines += [
            "## Ranked hypotheses",
            "",
            "_Confidence values are the model's own estimates, not calibrated probabilities: even 100% means the model "
            "found no competing explanation in the evidence, not that the cause is statistically established._",
            "",
        ]
        for h in hyps:
            lines.append(f"### {h['rank']}. {h['title']} — model-estimated confidence {h['confidence']:.0%}")
            lines += ["", f"*Category:* `{h['category']}`", "", h["description"], "", "Supporting evidence:"]
            lines += [
                f"- `{i}` — {_one_line(ev[i]['summary'])}{_cite(ev[i])}"
                for i in h["supporting_evidence_ids"]
                if i in ev
            ]
            if h.get("contradicting_evidence_ids"):
                lines.append("Contradicting evidence:")
                lines += [
                    f"- `{i}` — {_one_line(ev[i]['summary'])}{_cite(ev[i])}"
                    for i in h["contradicting_evidence_ids"]
                    if i in ev
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

    if uploaded:
        lines += _uploaded_sections(state, rca, ev)
        return "\n".join(lines + _trailer(state, rca, ev)) + "\n"

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
                f"- **Verification:** {'recovered' if ver.get('recovered') else 'NOT recovered'}"
                f"{' (' + ver['verdict'] + ')' if ver.get('verdict') else ''} — {ver.get('notes')}"
            )
            for svc, x in (ver.get("services") or {}).items():
                lines.append(
                    f"  - {svc} ({', '.join(x['reasons'])}): initial {x['initial']}"
                    f"{' (conflicting observations)' if x.get('initial_conflict') else ''}, now {x['current']}"
                )
            for x in ver.get("excluded") or []:
                lines.append(f"  - Not a recovery condition: {x['service']} {x['metric']} ({x['reason']})")
    else:
        lines.append("- No remediation executed or proposed for approval.")
    for r in state.get("rejected_proposals") or []:
        lines.append(
            f"- Blocked model proposal `{r['proposal'].get('action_type')}` "
            f"({r.get('category') or 'invalid'}): {r['reason']}"
        )
    lines.append("")

    return "\n".join(lines + _trailer(state, rca, ev)) + "\n"


def _source(e: dict[str, Any]) -> str | None:
    """Where uploaded evidence came from (file and line/row), when known."""
    d = e.get("data") or {}
    return (
        (d.get("attributes") or {}).get("source_ref")
        or d.get("sources")
        or (d.get("metadata") or {}).get("source_ref")
        or None
    )


def _cite(e: dict[str, Any]) -> str:
    src = _source(e)
    return f" _(source: {_one_line(str(src), 120)})_" if src else ""


def next_steps(state: dict[str, Any]) -> list[str]:
    """Deterministic follow-up investigation steps for an uploaded-evidence analysis: what is missing and why."""
    inc = state.get("incident") or {}
    svc = inc.get("service") or "the affected service"
    ev = list((state.get("evidence") or {}).values())
    kinds = {e["kind"] for e in ev}
    services_with_metrics = {e.get("service") for e in ev if e["kind"] == "metric_anomaly"}
    steps: list[str] = []
    coverage = (state.get("telemetry_coverage") or {}).get(svc) or {}
    if svc not in services_with_metrics and not coverage.get("metrics_ok"):
        steps.append(
            f"Export error-rate and latency metrics for {svc} covering at least an hour before and after the incident "
            "(CSV with timestamp, service and one column per metric); without them impact cannot be established."
        )
    if "log_pattern" not in kinds:
        steps.append(f"Upload WARN/ERROR application logs for {svc} from the incident window.")
    if not kinds & {"deployment", "config_change"}:
        steps.append(
            "Upload the deployment and configuration-change history for the window (JSON or CSV events with timestamp, "
            "service and type); change correlation was not possible without it."
        )
    calls = state.get("tool_calls") or []
    if any(c.get("tool") == "get_service_dependencies" and c.get("status") != "ok" for c in calls) or not any(
        c.get("tool") == "get_service_dependencies" for c in calls
    ):
        steps.append("Upload traces (OTLP/JSON) to show which downstream calls fail; dependencies were not observed.")
    rca = state.get("rca") or {}
    hyps = rca.get("hypotheses") or []
    if hyps:
        cited = [e for e in ev if e["id"] in set(hyps[0].get("supporting_evidence_ids") or [])]
        changes = [e for e in cited if e["kind"] in ("deployment", "config_change")]
        for c in changes[:1]:
            steps.append(
                f"Confirm or rule out the change behind the top hypothesis ({_one_line(c['summary'], 140)}): compare "
                "error rates before and after it, or check whether a rollback is possible in your environment."
            )
    steps.append(
        f"Check the current health of {svc} in your own monitoring: this analysis saw only the uploaded files, "
        "not live state."
    )
    return steps


def _uploaded_sections(state: dict[str, Any], rca: dict[str, Any], ev: dict[str, Any]) -> list[str]:
    lines = ["## Suggested remediation (not executed)", ""]
    suggested = state.get("suggested_remediation") or []
    if suggested:
        lines += [
            "These steps passed the same evidence checks used for sandbox plans. They are suggestions for a human "
            "to review and carry out in the real environment; OpsPilot did not and cannot execute them.",
            "",
            "| Step | Action | Parameters | Rationale |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {p.get('step')} | `{p['action_type']}` | {_one_line(str(p['parameters']), 80)} | "
            f"{_one_line(str(p.get('rationale') or ''), 140)} |"
            for p in suggested
        ]
        lines.append("")
    else:
        lines.append("- No remediation step was supported well enough by the uploaded evidence to suggest.")
    for r in state.get("rejected_proposals") or []:
        lines.append(
            f"- Not suggested: model proposal `{r['proposal'].get('action_type')}` "
            f"({r.get('category') or 'invalid'}): {r['reason']}"
        )
    lines += ["", "## Recommended next investigation steps", ""]
    lines += [f"- {g}" for g in rca.get("evidence_gaps") or []]
    lines += [f"- {s}" for s in next_steps(state)]
    lines.append("")
    return lines


def _trailer(state: dict[str, Any], rca: dict[str, Any], ev: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if rca.get("evidence_gaps") and not is_uploaded(state.get("incident")):
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
    return lines
