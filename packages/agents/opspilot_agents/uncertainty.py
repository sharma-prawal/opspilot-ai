"""Explicit uncertainty policy for remediation proposals (audit finding F).

A validated plan is *withheld* — never sent for approval — when the diagnosis behind it is uncertain:

- the top hypothesis is below the confidence threshold;
- the RCA explicitly requests escalation to a human owner;
- the top two hypotheses compete: their confidences are within ``ambiguity_margin`` and they share no
  supporting evidence, so the evidence does not discriminate between two different explanations;
- an investigation budget (tool or model calls) was exhausted, so the evidence is known to be incomplete.

There is deliberately no operator override in this phase: an uncertain investigation escalates with its
evidence, and the operator acts outside the automated path. Human approval is still required for any
plan that does pass this gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

BUDGET_ERROR = "budget_exceeded"


def uncertainty_reasons(state: Mapping[str, Any], *, confidence_threshold: float, ambiguity_margin: float) -> list[str]:
    rca = state.get("rca") or {}
    hyps = rca.get("hypotheses") or []
    reasons: list[str] = []
    if not hyps:
        return ["no root-cause hypothesis was produced"]
    top = hyps[0]
    if float(top.get("confidence", 0.0)) < confidence_threshold:
        reasons.append(
            f"top hypothesis confidence {top.get('confidence')} is below the threshold {confidence_threshold}"
        )
    esc = rca.get("escalation") or {}
    if esc.get("required"):
        reasons.append("the RCA requested escalation" + (f": {esc['reason']}" if esc.get("reason") else ""))
    if len(hyps) > 1:
        second = hyps[1]
        gap = round(float(top.get("confidence", 0.0)) - float(second.get("confidence", 0.0)), 6)
        a, b = set(top.get("supporting_evidence_ids") or []), set(second.get("supporting_evidence_ids") or [])
        if gap < ambiguity_margin and a and b and not (a & b):
            reasons.append(
                f"competing hypotheses: the top two are within {ambiguity_margin} confidence and share no "
                "supporting evidence"
            )
    exhausted = sorted({e.get("node", "?") for e in state.get("errors") or [] if e.get("error_class") == BUDGET_ERROR})
    if exhausted:
        reasons.append(f"investigation budget exhausted in {exhausted}; evidence is incomplete")
    return reasons
