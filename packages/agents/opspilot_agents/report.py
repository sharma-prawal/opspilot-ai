"""Deterministic RCA report rendering from structured investigation state.

The narrative summary comes from the RCA model output; everything else (timeline, evidence,
citations, metrics) is rendered from recorded data, so the report cannot cite evidence that
was never collected.
"""

from __future__ import annotations

from typing import Any


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
    lines = [f"# RCA: {inc.get('reference', '')} — {inc.get('title', 'Incident')}", ""]
    status = state.get("status")
    lines += [
        f"- **Service:** {inc.get('service')}  ",
        f"- **Severity:** {inc.get('severity')}  ",
        f"- **Detected:** {_ts(inc.get('detected_at'))}  ",
        f"- **Anomaly onset:** {_ts(w.get('onset'))}  ",
        f"- **Investigation status:** {status}  ",
        f"- **Initial triage (alert only):** {(state.get('classification') or {}).get('category')} "
        f"({(state.get('classification') or {}).get('source')})",
        "",
    ]

    final_cat = (hyps_top := (rca.get("hypotheses") or [None])[0]) and hyps_top["category"]
    if final_cat:
        lines.insert(-1, f"- **Root-cause category (RCA):** {final_cat}")
    if rca.get("summary"):
        lines += ["## Summary", "", rca["summary"], ""]
    hyps = rca.get("hypotheses") or []
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
        lines += [f"| {_ts(t)} | {d.replace('|', '/')} |" for t, d in sorted(timeline)]
        lines.append("")

    action, approval = state.get("proposed_action"), state.get("approval")
    lines += ["## Remediation", ""]
    if action:
        lines += [
            f"- **Proposed:** `{action['action_type']}` {action['parameters']} (risk {action['risk']})",
            f"- **Action ID:** `{action['action_id']}` · params hash `{action['params_hash'][:16]}…`",
            f"- **Rationale:** {action['rationale']}",
        ]
        if approval:
            lines.append(
                f"- **Decision:** {approval['decision']} by {approval.get('decided_by')} at "
                f"{_ts(approval.get('decided_at'))}"
                + (f" — “{approval['comment']}”" if approval.get("comment") else "")
            )
        rem = state.get("remediation")
        if rem:
            lines.append(f"- **Execution:** {rem.get('status')} — {rem.get('message')}")
        ver = state.get("verification")
        if ver:
            lines.append(
                f"- **Verification:** {'recovered' if ver.get('recovered') else 'NOT recovered'} — {ver.get('notes')}"
            )
    else:
        lines.append("- No remediation proposed.")
    for r in state.get("rejected_proposals") or []:
        lines.append(f"- Rejected model proposal {r['proposal'].get('action_type')}: {r['reason']}")
    lines.append("")

    if rca.get("evidence_gaps"):
        lines += ["## Evidence gaps", ""] + [f"- {g}" for g in rca["evidence_gaps"]] + [""]

    cited = [e for e in ev.values() if e.get("citation")]
    if cited:
        lines += ["## Knowledge sources", ""]
        seen: set[str] = set()
        for e in sorted(cited, key=lambda e: -e["relevance"]):
            c = e["citation"]
            if c["chunk_id"] in seen:
                continue
            seen.add(c["chunk_id"])
            lines.append(
                f"- `{e['id']}` {c['title']} > {c['heading_path']} (`{c['source_uri']}`, chunk `{c['chunk_id'][:8]}`)"
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
