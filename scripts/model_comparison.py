"""Tabulate supplementary agent runs (``opspilot-eval agent --out DIR``) side by side.

Usage: uv run python scripts/model_comparison.py LABEL=DIR [LABEL=DIR ...]

This only reads what the existing scorer (``opspilot_eval.agent_eval.score_run``) already wrote, plus the raw RCA
the model returned in each trace. It adds no scoring rules: "raw" columns describe the model's own answer before
the deterministic safety gates; "system" columns describe what the gated workflow did.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

NEGATIVE = {"NEG-001", "NEG-002", "NEG-003"}


def _load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted((path / "traces").glob("*-approve.json"))]


def _raw_abstained(score: dict[str, Any], rca: dict[str, Any]) -> bool | None:
    """Negative scenarios only: the model itself proposed no step (and escalated where the cause is unclear)."""
    if score["scenario"] not in NEGATIVE:
        return None
    no_plan = not rca.get("remediation_plan")
    if score["scenario"] == "NEG-001":
        return no_plan  # recovered blip: nothing to do, nothing to escalate
    return no_plan and bool((rca.get("escalation") or {}).get("required"))


def summarise(label: str, path: Path) -> dict[str, Any]:
    runs = _load(path)
    rows = []
    for t in runs:
        s, run = t["score"], t["run"]
        rca = (run.get("result") or {}).get("rca") or {}
        calls = run.get("llm_calls") or []
        rows.append(
            {
                "scenario": s["scenario"],
                "model": rca.get("model") or (calls[0]["model"] if calls else "?"),
                "outcome": s["outcome"],
                "system_ok": s["outcome_correct"],
                "root_cause": s["root_cause_correct"],
                "category": s["rca_category"],
                "top_conf": s["top_confidence"],
                "raw_plan": [p.get("action_type") for p in rca.get("remediation_plan") or []],
                "raw_plan_ok": s["model_plan_acceptable"],
                "blocked": len(s["blocked_by_policy"]),
                "raw_abstained": _raw_abstained(s, rca),
                "escalate": (rca.get("escalation") or {}).get("required"),
                "impact_agrees": rca.get("impact_ongoing_model") == rca.get("impact_ongoing"),
                "gaps": len(rca.get("evidence_gaps") or []),
                "cit_viol": s["citation_violations"],
                "json_retries": sum(max(0, int(c.get("attempts") or 1) - 1) for c in calls),
                "llm_failed": sum(1 for c in calls if c.get("status") != "ok"),
                "rca_s": next((c["latency_ms"] / 1000 for c in calls if c["purpose"] == "rca.analyze"), None),
                "rca_out_tokens": next((c["completion_tokens"] for c in calls if c["purpose"] == "rca.analyze"), None),
                "total_s": s["seconds_total"],
                "completed": s["completed"],
            }
        )
    rc = [r["root_cause"] for r in rows if r["root_cause"] is not None]
    neg = [r["raw_abstained"] for r in rows if r["raw_abstained"] is not None]
    return {
        "label": label,
        "model": rows[0]["model"] if rows else "?",
        "rows": rows,
        "totals": {
            "runs": len(rows),
            "completed": sum(r["completed"] for r in rows),
            "system_outcome_correct": sum(r["system_ok"] for r in rows),
            "root_cause_correct": f"{sum(rc)}/{len(rc)}",
            "raw_plan_acceptable": f"{sum(r['raw_plan_ok'] for r in rows)}/{len(rows)}",
            "steps_blocked_by_gates": sum(r["blocked"] for r in rows),
            "raw_abstain_or_escalate_on_negatives": f"{sum(neg)}/{len(neg)}",
            "impact_agrees_with_evidence": f"{sum(r['impact_agrees'] for r in rows)}/{len(rows)}",
            "citation_violations": sum(r["cit_viol"] for r in rows),
            "json_retries": sum(r["json_retries"] for r in rows),
            "llm_failures": sum(r["llm_failed"] for r in rows),
            "mean_rca_s": round(mean(r["rca_s"] for r in rows if r["rca_s"] is not None), 1) if rows else None,
            "mean_total_s": round(mean(r["total_s"] for r in rows), 1) if rows else None,
        },
    }


def render(results: list[dict[str, Any]]) -> str:
    keys = list(results[0]["totals"])
    out = ["| metric | " + " | ".join(f"{r['label']} (`{r['model']}`)" for r in results) + " |"]
    out.append("|---|" + "---|" * len(results))
    out += [f"| {k} | " + " | ".join(str(r["totals"][k]) for r in results) + " |" for k in keys]
    for r in results:
        out += ["", f"**{r['label']}** (`{r['model']}`)", ""]
        out.append(
            "| scenario | system outcome | root cause | top category (conf) | raw model plan | gates blocked | "
            "raw abstain/escalate | evidence gaps | RCA s |"
        )
        out.append("|---|---|---|---|---|---|---|---|---|")
        for x in r["rows"]:
            plan = ", ".join(x["raw_plan"]) or "—"
            out.append(
                f"| {x['scenario']} | {x['outcome']} {'✅' if x['system_ok'] else '❌'} | "
                f"{'—' if x['root_cause'] is None else ('✅' if x['root_cause'] else '❌')} | "
                f"{x['category']} ({x['top_conf']}) | {plan} {'✅' if x['raw_plan_ok'] else '❌'} | {x['blocked']} | "
                f"{'—' if x['raw_abstained'] is None else ('✅' if x['raw_abstained'] else '❌')} | {x['gaps']} | "
                f"{x['rca_s']:.1f} |"
            )
    return "\n".join(out)


if __name__ == "__main__":
    pairs = [a.split("=", 1) for a in sys.argv[1:]]
    if not pairs or any(len(p) != 2 for p in pairs):
        sys.exit(__doc__)
    print(render([summarise(label, Path(d)) for label, d in pairs]))
