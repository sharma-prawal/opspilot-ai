"""Investigation graph nodes.

Each node is ``async (state) -> partial state update``. Nodes only talk to the outside world
through the ``ChatModel`` and ``ToolGateway`` ports. Nodes up to and including ``await_approval``
are side-effect free (re-execution on resume is safe); the only state-changing call is in
``execute``, which runs strictly after a validated approval.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from langgraph.config import get_stream_writer
from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from opspilot_agents.analysis import (
    LogPattern,
    change_correlation,
    cluster_logs,
    detect_onset,
    has_schema_signals,
    mean,
)
from opspilot_agents.ports import ToolGateway, ToolResult
from opspilot_agents.prompts import PlanOutput, RcaOutput, plan_messages, rca_messages
from opspilot_agents.report import render_report
from opspilot_agents.state import CAPABILITIES, InvestigationState, Task, task_key
from opspilot_shared.approvals import action_params_hash
from opspilot_shared.domain.actions import REMEDIATION_CATALOG, ActionType
from opspilot_shared.domain.common import utcnow
from opspilot_shared.domain.evidence import Citation, Evidence, EvidenceKind, ToolCallStatus
from opspilot_shared.domain.incidents import IncidentCategory
from opspilot_shared.errors import ApprovalError, LLMError
from opspilot_shared.ids import short_hash, stable_uuid
from opspilot_shared.llm.ports import ChatModel
from opspilot_shared.logging import get_logger, log_context
from opspilot_shared.tracing import get_tracer

_log = get_logger(__name__)
_tracer = get_tracer(__name__)
State = InvestigationState
PRECEDENCE = {"telemetry": 0, "dependencies": 1, "changes": 2, "knowledge": 3}
Update = dict[str, Any]


@dataclass(frozen=True, slots=True)
class AgentPolicy:
    max_tool_calls: int = 40
    max_llm_calls: int = 6
    max_rounds: int = 2
    confidence_threshold: float = 0.6
    lookback_hours: float = 3.0
    change_horizon_hours: float = 6.0
    recovery_threshold: float = 0.01
    max_prompt_evidence: int = 30


@dataclass(slots=True)
class AgentDeps:
    chat: ChatModel
    tools: ToolGateway
    actions: ToolGateway | None
    policy: AgentPolicy = field(default_factory=AgentPolicy)


# ----------------------------------------------------------------------------- helpers
def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _hhmm(value: str | datetime) -> str:
    dt = _dt(value) if isinstance(value, str) else value
    return dt.strftime("%H:%M:%SZ")


def _fmt_ratio(v: float) -> str:
    return f"{v:.2%}"


def _fmt_ms(v: float) -> str:
    return f"{v:.0f} ms"


def _evidence(**kw: Any) -> tuple[str, dict[str, Any]]:
    ev = Evidence(**kw)
    return ev.id, ev.model_dump(mode="json")


def _error(node: str, message: str, error_class: str = "agent") -> dict[str, Any]:
    return {"node": node, "error_class": error_class, "message": message[:1000], "at": _iso(utcnow())}


class _Calls:
    """Budget-aware tool invoker for one node execution. Records every call (incl. rejections)."""

    def __init__(self, gateway: ToolGateway, state: State, policy: AgentPolicy, agent: str) -> None:
        self._gw = gateway
        self._agent = agent
        self.remaining = policy.max_tool_calls - len(state.get("tool_calls", []))
        self.records: list[dict[str, Any]] = []
        self.budget_exhausted = False

    async def one(self, tool: str, args: dict[str, Any]) -> ToolResult | None:
        if self.remaining <= 0:
            self.budget_exhausted = True
            return None
        self.remaining -= 1
        res = await self._gw.call(tool, args, agent=self._agent)
        if res.record.status is ToolCallStatus.TIMEOUT and self.remaining > 0:  # one bounded retry
            self.records.append(res.record.model_dump(mode="json"))
            self.remaining -= 1
            res = await self._gw.call(tool, args, agent=self._agent)
        self.records.append(res.record.model_dump(mode="json"))
        return res

    async def many(self, calls: list[tuple[str, dict[str, Any]]]) -> list[ToolResult | None]:
        return list(await asyncio.gather(*(self.one(t, a) for t, a in calls)))

    def update(self) -> Update:
        out: Update = {"tool_calls": self.records}
        if self.budget_exhausted:
            out["errors"] = [_error(self._agent, "tool-call budget exhausted", "budget_exceeded")]
        return out


def instrumented(name: str) -> Callable[[Callable[[State], Awaitable[Update]]], Callable[[State], Awaitable[Update]]]:
    """Span + log context + live 'node_started' stream event for every node."""

    def deco(fn: Callable[[State], Awaitable[Update]]) -> Callable[[State], Awaitable[Update]]:
        @functools.wraps(fn)
        async def wrapper(state: State) -> Update:
            with contextlib.suppress(Exception):  # not streaming (e.g. direct unit-test calls)
                get_stream_writer()({"event": "node_started", "node": name, "at": _iso(utcnow())})
            t0 = time.perf_counter()
            with (
                log_context(node=name, investigation_id=state.get("investigation_id")),
                _tracer.start_as_current_span(f"agent.node/{name}", record_exception=False) as span,
            ):
                try:
                    update = await fn(state)
                except GraphInterrupt:
                    span.set_attribute("agent.interrupted", True)
                    raise
            update.setdefault("current_step", name)
            _log.info("node_completed", latency_ms=round((time.perf_counter() - t0) * 1000, 1))
            return update

        return wrapper

    return deco


def _services_seen(state: State) -> set[str]:
    return {e["service"] for e in state.get("evidence", {}).values() if e.get("service")}


def _queued_or_done(state: State, key: str, extra: list[Task] | None = None) -> bool:
    keys = set(state.get("completed_tasks", [])) | {task_key(t) for t in state.get("task_queue", [])}
    keys |= {task_key(t) for t in (extra or [])}
    return key in keys


def _complete(state: State, task: Task | None) -> list[str]:
    done = list(state.get("completed_tasks", []))
    if task is not None:
        done.append(task_key(task))
    return done


# ----------------------------------------------------------------------------- nodes
class InvestigationNodes:
    def __init__(self, deps: AgentDeps) -> None:
        self.d = deps
        self.p = deps.policy

    # -- intake ---------------------------------------------------------------------
    async def intake(self, state: State) -> Update:
        calls = _Calls(self.d.tools, state, self.p, "intake")
        res = await calls.one("get_incident", {"incident_id": state["incident_id"]})
        if res is None or not res.ok or res.data is None:
            return {
                **calls.update(),
                "status": "failed",
                "errors": [_error("intake", f"cannot load incident: {res.error if res else 'budget'}")],
            }
        incident = res.data
        detected = _dt(incident["detected_at"])
        window = {
            "start": _iso(detected - timedelta(hours=self.p.lookback_hours)),
            "end": _iso(detected + timedelta(minutes=30)),
            "detected_at": incident["detected_at"],
        }
        return {
            **calls.update(),
            "incident": incident,
            "window": window,
            "status": "running",
            "task_queue": [],
            "completed_tasks": [],
            "rounds": 0,
        }

    # -- supervisor: classify + plan -------------------------------------------------
    async def plan(self, state: State) -> Update:
        incident = state["incident"]
        service = incident["service"]
        update: Update = {}
        if len(state.get("llm_calls", [])) >= self.p.max_llm_calls:
            caps, cls = (
                list(CAPABILITIES),
                {
                    "category": IncidentCategory.UNKNOWN.value,
                    "confidence": 0.0,
                    "rationale": "LLM budget exhausted",
                    "source": "fallback",
                },
            )
        else:
            try:
                out = await self.d.chat.generate_structured(
                    messages=plan_messages(incident), schema=PlanOutput, purpose="supervisor.plan"
                )
                caps = list(dict.fromkeys(out.value.capabilities))
                cls = {
                    "category": out.value.category.value,
                    "confidence": out.value.category_confidence,
                    "rationale": out.value.rationale,
                    "source": "llm",
                }
                update["llm_calls"] = [out.record.model_dump(mode="json")]
            except LLMError as exc:
                caps = list(CAPABILITIES)
                cls = {
                    "category": IncidentCategory.UNKNOWN.value,
                    "confidence": 0.0,
                    "rationale": f"fallback plan: {exc}",
                    "source": "fallback",
                }
                update["errors"] = [_error("plan", str(exc), exc.error_class)]
        notes = []
        if "telemetry" not in caps:  # policy: the alerting service is always inspected
            caps.insert(0, "telemetry")
            notes.append("telemetry added by policy (alerting service is always inspected)")
        if "knowledge" not in caps:  # policy: hypotheses must be grounded in runbooks / past incidents
            caps.append("knowledge")
            notes.append("knowledge added by policy (RCA must be grounded in retrieved runbooks/incidents)")
        queue: list[Task] = [
            {
                "capability": c,
                "service": service if c in ("telemetry", "dependencies") else None,
                "reason": "supervisor plan",
            }
            for c in caps
        ]
        return {
            **update,
            "classification": cls,
            "task_queue": queue,
            "plan": {"capabilities": caps, "notes": notes, "planned_at": _iso(utcnow())},
        }

    # -- router ---------------------------------------------------------------------
    async def dispatch(self, state: State) -> Update:
        queue = [t for t in state.get("task_queue", []) if task_key(t) not in set(state.get("completed_tasks", []))]
        if len(state.get("tool_calls", [])) >= self.p.max_tool_calls:
            return {
                "task_queue": [],
                "active_task": None,
                "errors": [_error("dispatch", "tool budget exhausted; proceeding to RCA", "budget_exceeded")],
            }
        if not queue:
            return {"task_queue": [], "active_task": None}
        # Scheduling follows data dependencies: each capability consumes what the previous ones found
        # (onset → related services → change correlation → informed retrieval). The plan decides *which*
        # capabilities run; evidence-driven tasks are appended by the nodes themselves.
        idx = min(range(len(queue)), key=lambda i: (PRECEDENCE.get(queue[i]["capability"], 9), i))
        task = queue.pop(idx)
        return {"task_queue": queue, "active_task": task}

    # -- telemetry agent ------------------------------------------------------------
    async def telemetry(self, state: State) -> Update:
        task = state.get("active_task") or {
            "capability": "telemetry",
            "service": state["incident"]["service"],
            "reason": "",
        }
        svc = task["service"] or state["incident"]["service"]
        env = state["incident"]["environment_id"]
        w = state["window"]
        calls = _Calls(self.d.tools, state, self.p, "telemetry")
        base = {"environment_id": env, "service": svc, "start": w["start"], "end": w["end"]}
        r5xx, rlat, rlogs, rhealth = await calls.many(
            [
                ("query_metrics", {**base, "metric": "http_5xx_ratio"}),
                ("query_metrics", {**base, "metric": "p95_latency_ms"}),
                ("search_logs", {**base, "min_level": "WARN", "limit": 300}),
                ("get_service_health", {"environment_id": env, "service": svc}),
            ]
        )
        evidence: dict[str, dict[str, Any]] = {}
        findings: list[str] = []
        onset: datetime | None = None

        for res, metric, min_inc, factor in ((r5xx, "http_5xx_ratio", 0.02, 5.0), (rlat, "p95_latency_ms", 100.0, 2.0)):
            if not res or not res.ok or not res.data:
                continue
            pts = [(_dt(p["ts"]), float(p["value"])) for p in res.data["points"]]
            an = detect_onset(pts, min_abs_increase=min_inc, factor=factor)
            fmt = _fmt_ratio if metric.endswith("ratio") else _fmt_ms
            if an:
                onset = an.onset if metric == "http_5xx_ratio" or onset is None else onset
                eid, ev = _evidence(
                    id=f"ev-metric-{short_hash(svc, metric, an.onset)}",
                    kind=EvidenceKind.METRIC_ANOMALY,
                    source_tool="query_metrics",
                    collected_by="telemetry",
                    service=svc,
                    relevance=0.9,
                    observed_at=an.onset,
                    summary=(
                        f"{svc} {metric} rose from baseline {fmt(an.baseline)} to peak {fmt(an.peak)} "
                        f"(current {fmt(an.current)}); sustained anomaly onset at {_hhmm(an.onset)}"
                    ),
                    data={
                        "metric": metric,
                        "baseline": an.baseline,
                        "peak": an.peak,
                        "current": an.current,
                        "onset": _iso(an.onset),
                        "threshold": an.threshold,
                        "points": len(pts),
                    },
                )
                evidence[eid] = ev
                findings.append(f"{metric} anomaly from {_hhmm(an.onset)}")
            elif pts:
                eid, ev = _evidence(
                    id=f"ev-metric-{short_hash(svc, metric, 'steady')}",
                    kind=EvidenceKind.METRIC_ANOMALY,
                    source_tool="query_metrics",
                    collected_by="telemetry",
                    service=svc,
                    relevance=0.35,
                    summary=f"{svc} {metric} shows no sustained anomaly in the window "
                    f"(mean {fmt(mean([v for _, v in pts]))})",
                    data={"metric": metric, "anomaly": False, "mean": mean([v for _, v in pts])},
                )
                evidence[eid] = ev

        new_tasks: list[Task] = []
        if rlogs and rlogs.ok and rlogs.data:
            patterns = cluster_logs(rlogs.data["entries"])
            for p in patterns:
                eid, ev = _evidence(
                    id=f"ev-log-{short_hash(svc, p.level, p.signature)}",
                    kind=EvidenceKind.LOG_PATTERN,
                    source_tool="search_logs",
                    collected_by="telemetry",
                    service=svc,
                    relevance=0.85 if p.level == "ERROR" else 0.3,
                    observed_at=p.first_seen,
                    summary=(
                        f"{svc} {p.level} x{p.count} (first {_hhmm(p.first_seen)}, last {_hhmm(p.last_seen)}): "
                        f"{p.sample[:400]}"
                    ),
                    data={
                        "level": p.level,
                        "count": p.count,
                        "signature": p.signature,
                        "sample": p.sample,
                        "first_seen": _iso(p.first_seen),
                        "last_seen": _iso(p.last_seen),
                        "attributes": p.attributes,
                        "total_matched": rlogs.data["total_matched"],
                    },
                )
                evidence[eid] = ev
                up = p.upstream
                if p.level == "ERROR" and up and up != svc:
                    t: Task = {
                        "capability": "dependencies",
                        "service": svc,
                        "reason": f"error logs on {svc} attribute failures to upstream {up}",
                    }
                    if not _queued_or_done(state, task_key(t), new_tasks):
                        new_tasks.append(t)
            errors = [p for p in patterns if p.level == "ERROR"]
            if errors:
                findings.append(f"top error: {errors[0].sample[:160]} (x{errors[0].count})")

        if rhealth and rhealth.ok and rhealth.data:
            h = rhealth.data
            eid, ev = _evidence(
                id=f"ev-health-{short_hash(svc, h['as_of'])}",
                kind=EvidenceKind.SERVICE_HEALTH,
                source_tool="get_service_health",
                collected_by="telemetry",
                service=svc,
                relevance=0.6 if h["status"] != "healthy" else 0.3,
                summary=f"{svc} health {h['status']} at {_hhmm(h['as_of'])}, version {h['version']}; "
                f"{'; '.join(h['notes'])}",
                data=h,
            )
            evidence[eid] = ev

        window = dict(state["window"])
        if onset and ("onset" not in window or onset < _dt(window["onset"])):
            window["onset"] = _iso(onset)
        obs = {
            "agent": "telemetry",
            "service": svc,
            "finding": "; ".join(findings) or f"no anomalies found on {svc}",
            "evidence_ids": list(evidence),
        }
        return {
            **calls.update(),
            "evidence": evidence,
            "observations": [obs],
            "window": window,
            "task_queue": [*state.get("task_queue", []), *new_tasks],
            "completed_tasks": _complete(state, task),
        }

    # -- dependency walk ------------------------------------------------------------
    async def dependencies(self, state: State) -> Update:
        task = state.get("active_task")
        svc = (task["service"] if task else None) or state["incident"]["service"]
        env = state["incident"]["environment_id"]
        calls = _Calls(self.d.tools, state, self.p, "dependencies")
        res = await calls.one("get_service_dependencies", {"environment_id": env, "service": svc})
        evidence: dict[str, dict[str, Any]] = {}
        new_tasks: list[Task] = []
        findings: list[str] = []
        if res and res.ok and res.data:
            critical = [d for d in res.data["downstream"] if d["critical"] and d["kind"] == "sync_http"]
            healths = await calls.many(
                [("get_service_health", {"environment_id": env, "service": d["depends_on"]}) for d in critical]
            )
            for dep, h in zip(critical, healths, strict=True):
                status = h.data["status"] if h and h.ok and h.data else "unknown"
                notes = "; ".join(h.data["notes"]) if h and h.ok and h.data else (h.error if h else "budget")
                eid, ev = _evidence(
                    id=f"ev-dep-{short_hash(svc, dep['depends_on'], status)}",
                    kind=EvidenceKind.DEPENDENCY,
                    source_tool="get_service_dependencies",
                    collected_by="dependencies",
                    service=dep["depends_on"],
                    relevance=0.75 if status in ("unhealthy", "degraded") else 0.3,
                    summary=f"{svc} → {dep['depends_on']} (critical {dep['kind']}): "
                    f"{dep['depends_on']} is {status}; {notes}",
                    data={"edge": dep, "health": h.data if h and h.ok else None},
                )
                evidence[eid] = ev
                findings.append(f"{dep['depends_on']} {status}")
                t: Task = {
                    "capability": "telemetry",
                    "service": dep["depends_on"],
                    "reason": f"critical downstream {dep['depends_on']} of {svc} is {status}",
                }
                if status in ("unhealthy", "degraded") and not _queued_or_done(state, task_key(t), new_tasks):
                    new_tasks.append(t)
        obs = {
            "agent": "dependencies",
            "service": svc,
            "finding": f"critical downstreams of {svc}: {', '.join(findings) or 'none'}",
            "evidence_ids": list(evidence),
        }
        return {
            **calls.update(),
            "evidence": evidence,
            "observations": [obs],
            "task_queue": [*state.get("task_queue", []), *new_tasks],
            "completed_tasks": _complete(state, task),
        }

    # -- change analysis agent ------------------------------------------------------
    async def changes(self, state: State) -> Update:
        task = state.get("active_task")
        env = state["incident"]["environment_id"]
        w = state["window"]
        onset = _dt(w.get("onset") or w["detected_at"])
        start = _iso(onset - timedelta(hours=self.p.change_horizon_hours))
        calls = _Calls(self.d.tools, state, self.p, "changes")
        rdep, rcfg = await calls.many(
            [
                ("list_recent_deployments", {"environment_id": env, "start": start, "end": w["end"]}),
                ("get_config_changes", {"environment_id": env, "start": start, "end": w["end"]}),
            ]
        )
        ev_all = state.get("evidence", {}).values()
        affected = {
            e["service"]
            for e in ev_all
            if e["kind"] == "metric_anomaly" and e["data"].get("anomaly", True) and e.get("service")
        }
        related = {e["service"] for e in ev_all if e["kind"] == "dependency"} | {state["incident"]["service"]}
        patterns = [
            LogPattern(
                e["data"]["signature"],
                e["data"]["level"],
                e["data"]["count"],
                _dt(e["data"]["first_seen"]),
                _dt(e["data"]["last_seen"]),
                e["data"]["sample"],
            )
            for e in ev_all
            if e["kind"] == "log_pattern"
        ]
        schema_signals = has_schema_signals(patterns)
        evidence: dict[str, dict[str, Any]] = {}
        scored: list[tuple[float, str, str]] = []
        for d in (rdep.data or {}).get("deployments", []) if rdep and rdep.ok else []:
            effective = _dt(d["finished_at"] or d["started_at"])
            score = change_correlation(
                effective,
                onset,
                change_service=d["service"],
                affected_services=affected,
                related_services=related,
                schema_change=d["kind"] == "schema_migration",
                schema_signals=schema_signals,
            )
            delta = round((onset - effective).total_seconds() / 60, 1)
            rel = "before" if delta >= 0 else "after"
            eid, ev = _evidence(
                id=f"ev-deploy-{short_hash(d['id'])}",
                kind=EvidenceKind.DEPLOYMENT,
                source_tool="list_recent_deployments",
                collected_by="changes",
                service=d["service"],
                relevance=max(score, 0.05),
                observed_at=effective,
                summary=(
                    f"{d['service']} {d['kind']} {d['version']} (id {d['id']}, previous {d['previous_version']}) "
                    f"finished {_hhmm(effective)}, {abs(delta)} min {rel} anomaly onset; status {d['status']}; "
                    f'"{d["change_summary"]}"; correlation {score:.2f}'
                ),
                data={**d, "minutes_before_onset": delta, "correlation": score},
            )
            evidence[eid] = ev
            scored.append((score, d["service"], eid))
        for c in (rcfg.data or {}).get("changes", []) if rcfg and rcfg.ok else []:
            changed = _dt(c["changed_at"])
            score = change_correlation(
                changed,
                onset,
                change_service=c["service"],
                affected_services=affected,
                related_services=related,
                schema_change=False,
                schema_signals=False,
            )
            delta = round((onset - changed).total_seconds() / 60, 1)
            eid, ev = _evidence(
                id=f"ev-config-{short_hash(c['id'])}",
                kind=EvidenceKind.CONFIG_CHANGE,
                source_tool="get_config_changes",
                collected_by="changes",
                service=c["service"],
                relevance=max(score, 0.05),
                observed_at=changed,
                summary=(
                    f"{c['service']} config {c['key']} {c['old_value']} → {c['new_value']} (id {c['id']}) at "
                    f"{_hhmm(changed)}, {delta} min before onset; correlation {score:.2f}"
                ),
                data={**c, "minutes_before_onset": delta, "correlation": score},
            )
            evidence[eid] = ev
            scored.append((score, c["service"], eid))
        scored.sort(reverse=True)
        new_tasks: list[Task] = []
        if scored and scored[0][0] >= 0.5:
            t: Task = {
                "capability": "telemetry",
                "service": scored[0][1],
                "reason": f"strongly correlated change on {scored[0][1]} ({scored[0][2]})",
            }
            if not _queued_or_done(state, task_key(t)):
                new_tasks.append(t)
        top = evidence[scored[0][2]]["summary"] if scored else "no changes in window"
        obs = {
            "agent": "changes",
            "service": None,
            "finding": f"{len(scored)} change(s) in window; top: {top[:240]}",
            "evidence_ids": [s[2] for s in scored[:5]],
        }
        return {
            **calls.update(),
            "evidence": evidence,
            "observations": [obs],
            "task_queue": [*state.get("task_queue", []), *new_tasks],
            "completed_tasks": _complete(state, task),
        }

    # -- knowledge agent ------------------------------------------------------------
    async def knowledge(self, state: State) -> Update:
        task = state.get("active_task")
        ev = list(state.get("evidence", {}).values())
        errors = sorted(
            (e for e in ev if e["kind"] == "log_pattern" and e["data"]["level"] == "ERROR"),
            key=lambda e: -e["data"]["count"],
        )
        changes = sorted((e for e in ev if e["kind"] in ("deployment", "config_change")), key=lambda e: -e["relevance"])
        parts = [e["data"]["signature"].replace("<uuid>", "").replace("<n>", "")[:160] for e in errors[:2]]
        if changes and changes[0]["relevance"] >= 0.3:
            c = changes[0]["data"]
            parts.append(f"{c.get('kind', 'config change')} {c.get('change_summary') or c.get('key', '')}")
        rca = state.get("rca") or {}
        if rca.get("hypotheses"):
            parts.insert(0, rca["hypotheses"][0]["title"])
        if not parts:
            parts = [state["incident"]["title"]]
        query = " ".join(parts)[:480]
        calls = _Calls(self.d.tools, state, self.p, "knowledge")
        rrun, rinc = await calls.many(
            [
                ("search_runbooks", {"query": query, "top_k": 4}),
                ("get_historical_incidents", {"query": query, "top_k": 3}),
            ]
        )
        evidence: dict[str, dict[str, Any]] = {}
        for res, kind in ((rrun, EvidenceKind.KNOWLEDGE), (rinc, EvidenceKind.HISTORICAL_INCIDENT)):
            if not res or not res.ok or not res.data:
                continue
            for rank, hit in enumerate(res.data["results"], start=1):
                eid, item = _evidence(
                    id=f"ev-kb-{hit['chunk_id'].replace('-', '')[:12]}",
                    kind=kind,
                    source_tool=res.tool,
                    collected_by="knowledge",
                    relevance=round(max(0.2, 0.8 - 0.1 * rank), 2),
                    summary=f"[{hit['title']} > {hit['heading_path']}] {hit['snippet'][:420]}",
                    citation=Citation(
                        document_id=hit["document_id"],
                        chunk_id=hit["chunk_id"],
                        source_uri=hit["source_uri"],
                        title=hit["title"],
                        heading_path=hit["heading_path"],
                    ),
                    data={
                        "rank": rank,
                        "score": hit["score"],
                        "query_id": res.data["query_id"],
                        "doc_type": hit["doc_type"],
                        "vector_rank": hit.get("vector_rank"),
                        "keyword_rank": hit.get("keyword_rank"),
                    },
                )
                evidence[eid] = item
        obs = {
            "agent": "knowledge",
            "service": None,
            "finding": f"retrieved {len(evidence)} cited passages for query: {query[:200]}",
            "evidence_ids": list(evidence),
        }
        return {
            **calls.update(),
            "evidence": evidence,
            "observations": [obs],
            "completed_tasks": _complete(state, task),
        }

    # -- RCA agent ------------------------------------------------------------------
    async def rca(self, state: State) -> Update:
        if len(state.get("llm_calls", [])) >= self.p.max_llm_calls:
            return {
                "status": "failed",
                "errors": [_error("rca", "LLM call budget exhausted before RCA", "budget_exceeded")],
            }
        evidence = state.get("evidence", {})
        ranked = sorted(evidence.values(), key=lambda e: (-e["relevance"], e["id"]))[: self.p.max_prompt_evidence]
        prompt_ev = [
            {
                "id": e["id"],
                "kind": e["kind"],
                "service": e.get("service"),
                "relevance": round(e["relevance"], 2),
                "summary": e["summary"],
            }
            for e in ranked
        ]
        round_no = state.get("rounds", 0) + 1
        try:
            out = await self.d.chat.generate_structured(
                messages=rca_messages(
                    state["incident"], state["window"], prompt_ev, state.get("observations", []), round_no
                ),
                schema=RcaOutput,
                purpose="rca.analyze",
            )
        except LLMError as exc:
            return {"status": "failed", "errors": [_error("rca", str(exc), exc.error_class)]}
        value: RcaOutput = out.value
        violations: list[str] = []
        hyps: list[dict[str, Any]] = []
        for h in value.hypotheses:
            support = [i for i in h.supporting_evidence_ids if i in evidence]
            contra = [i for i in h.contradicting_evidence_ids if i in evidence]
            violations += [i for i in [*h.supporting_evidence_ids, *h.contradicting_evidence_ids] if i not in evidence]
            if not support:
                continue  # an uncited hypothesis is not evidence-based; drop it
            hyps.append(
                {
                    "title": h.title,
                    "category": h.category.value,
                    "description": h.description,
                    "confidence": round(h.confidence, 3),
                    "supporting_evidence_ids": list(dict.fromkeys(support)),
                    "contradicting_evidence_ids": list(dict.fromkeys(contra)),
                }
            )
        hyps.sort(key=lambda item: -item["confidence"])
        for i, item in enumerate(hyps, start=1):
            item["rank"] = i
        update: Update = {"llm_calls": [out.record.model_dump(mode="json")]}
        if not hyps:
            return {
                **update,
                "status": "failed",
                "rca": {"summary": value.summary, "citation_violations": violations},
                "errors": [_error("rca", "model produced no hypothesis citing valid evidence", "llm_invalid_output")],
            }
        return {
            **update,
            "rca": {
                "summary": value.summary,
                "hypotheses": hyps,
                "evidence_gaps": value.evidence_gaps,
                "followups": list(dict.fromkeys(value.followups)),
                "remediation": value.remediation.model_dump(),
                "citation_violations": sorted(set(violations)),
                "round": round_no,
                "model": self.d.chat.model_name,
            },
        }

    # -- bounded follow-up ----------------------------------------------------------
    async def followup(self, state: State) -> Update:
        rca = state.get("rca") or {}
        completed = list(state.get("completed_tasks", []))
        top = (rca.get("hypotheses") or [{}])[0]
        services = {
            state["evidence"][i]["service"]
            for i in top.get("supporting_evidence_ids", [])
            if state["evidence"].get(i, {}).get("service")
        } or {state["incident"]["service"]}
        tasks: list[Task] = []
        for cap in rca.get("followups", []):
            if cap == "knowledge":
                completed = [k for k in completed if not k.startswith("knowledge:")]
                tasks.append({"capability": "knowledge", "service": None, "reason": "RCA follow-up: refine retrieval"})
            elif cap == "changes":
                continue  # change history over the same window would be identical
            else:
                for s in sorted(services):
                    t: Task = {"capability": cap, "service": s, "reason": "RCA follow-up on low-confidence hypothesis"}
                    if task_key(t) not in completed:
                        tasks.append(t)
        return {"rounds": state.get("rounds", 0) + 1, "task_queue": tasks, "completed_tasks": completed}

    # -- remediation proposal (validated against catalogue + evidence) ---------------
    async def propose(self, state: State) -> Update:
        rca = state["rca"] or {}
        rem = rca.get("remediation") or {}
        evidence = state.get("evidence", {})
        deployments = {e["data"]["id"]: e for e in evidence.values() if e["kind"] == "deployment"}
        known_services = _services_seen(state) | {state["incident"]["service"]}

        def reject(reason: str) -> Update:
            _log.warning("remediation_rejected", reason=reason, proposal=rem)
            return {
                "proposed_action": None,
                "rejected_proposals": [{"proposal": rem, "reason": reason, "at": _iso(utcnow())}],
            }

        try:
            action_type = ActionType(str(rem.get("action_type")))
        except ValueError:
            return reject(f"action type {rem.get('action_type')!r} is not in the remediation catalogue")
        spec = REMEDIATION_CATALOG[action_type]
        if not spec.implemented:
            return reject(f"{action_type.value} is not available in the sandbox")
        params: dict[str, Any]
        if action_type is ActionType.ROLLBACK_DEPLOYMENT:
            dep = deployments.get(rem.get("deployment_id") or "")
            if dep is None:
                return reject(f"deployment {rem.get('deployment_id')!r} does not appear in collected evidence")
            if dep["data"]["kind"] == "rollback" or dep["data"]["status"] == "rolled_back":
                return reject("deployment is already a rollback / rolled back")
            params = {"service": dep["data"]["service"], "deployment_id": dep["data"]["id"]}
        elif action_type is ActionType.RESTART_SERVICE:
            if rem.get("service") not in known_services:
                return reject(f"service {rem.get('service')!r} not observed in this investigation")
            params = {"service": rem["service"]}
        else:  # pragma: no cover - unimplemented types rejected above
            return reject("unsupported")
        params_hash = action_params_hash(action_type.value, params)
        action_id = stable_uuid("action", state["investigation_id"], params_hash)
        proposed = {
            "action_id": str(action_id),
            "action_type": action_type.value,
            "parameters": params,
            "params_hash": params_hash,
            "rationale": rem.get("rationale", ""),
            "risk": spec.risk.value,
            "hypothesis_rank": 1,
            "proposed_at": _iso(utcnow()),
        }
        return {"proposed_action": proposed}

    # -- human-in-the-loop ----------------------------------------------------------
    async def await_approval(self, state: State) -> Update:
        action = state["proposed_action"]
        assert action is not None
        decision = interrupt({"type": "approval_required", "action": action})
        if not isinstance(decision, dict):
            raise ApprovalError("resume payload must be an object")
        if decision.get("action_id") != action["action_id"] or decision.get("params_hash") != action["params_hash"]:
            raise ApprovalError("resume payload does not match the pending action")
        kind = decision.get("decision")
        if kind not in ("approve", "reject"):
            raise ApprovalError("decision must be approve or reject")
        if kind == "approve" and not decision.get("approval_token"):
            raise ApprovalError("approval requires a signed approval token")
        return {
            "approval": {
                k: decision.get(k)
                for k in (
                    "action_id",
                    "params_hash",
                    "decision",
                    "decided_by",
                    "comment",
                    "decided_at",
                    "approval_token",
                )
            }
        }

    # -- sandbox execution ----------------------------------------------------------
    async def execute(self, state: State) -> Update:
        action, approval = state["proposed_action"], state["approval"]
        assert action is not None and approval is not None and approval["decision"] == "approve"
        if self.d.actions is None:
            return {"remediation": {"status": "failed", "message": "no action gateway configured"}}
        calls = _Calls(self.d.actions, state, self.p, "remediation")
        res = await calls.one(
            "execute_remediation", {"action_id": action["action_id"], "approval_token": approval["approval_token"]}
        )
        if res is None or not res.ok or res.data is None:
            remediation = {"status": "failed", "message": (res.error if res else "tool budget exhausted")}
        else:
            remediation = {**res.data}
        return {**calls.update(), "remediation": remediation}

    async def verify(self, state: State) -> Update:
        rem = state.get("remediation") or {}
        svc = state["incident"]["service"]
        if rem.get("status") != "succeeded":
            return {
                "verification": {
                    "recovered": False,
                    "service": svc,
                    "notes": f"remediation did not succeed: {rem.get('message')}",
                }
            }
        details = rem.get("details") or {}
        start, end = details.get("executed_at_sim"), details.get("sim_now_after")
        calls = _Calls(self.d.tools, state, self.p, "verify")
        res = await calls.one(
            "query_metrics",
            {
                "environment_id": state["incident"]["environment_id"],
                "service": svc,
                "metric": "http_5xx_ratio",
                "start": start,
                "end": end,
            },
        )
        before = max(
            (
                e["data"].get("current", 0.0)
                for e in state["evidence"].values()
                if e["kind"] == "metric_anomaly"
                and e.get("service") == svc
                and e["data"].get("metric") == "http_5xx_ratio"
            ),
            default=0.0,
        )
        if not res or not res.ok or not res.data or len(res.data["points"]) < 3:
            return {
                **calls.update(),
                "verification": {"recovered": False, "service": svc, "notes": "insufficient post-remediation data"},
            }
        tail = [float(p["value"]) for p in res.data["points"]][-5:]
        after = mean(tail)
        recovered = after < self.p.recovery_threshold
        return {
            **calls.update(),
            "verification": {
                "recovered": recovered,
                "service": svc,
                "metric": "http_5xx_ratio",
                "threshold": self.p.recovery_threshold,
                "observed_before": round(before, 5),
                "observed_after": round(after, 5),
                "window_start": start,
                "window_end": end,
                "notes": (
                    f"5xx ratio {after:.2%} over the last {len(tail)} min after remediation "
                    f"(before {before:.2%}); threshold {self.p.recovery_threshold:.0%}"
                ),
            },
        }

    # -- report / terminal ----------------------------------------------------------
    async def report(self, state: State) -> Update:
        final = {**state, "status": "completed"}
        return {"report": {"markdown": render_report(final), "generated_at": _iso(utcnow())}, "status": "completed"}

    async def failed(self, state: State) -> Update:
        final = {**state, "status": "failed"}
        return {"status": "failed", "report": {"markdown": render_report(final), "generated_at": _iso(utcnow())}}


# ----------------------------------------------------------------------------- routing
def route_after_intake(state: State) -> str:
    return "failed" if state.get("status") == "failed" else "plan"


def route_dispatch(state: State) -> str:
    task = state.get("active_task")
    return task["capability"] if task else "rca"


def make_route_after_rca(policy: AgentPolicy) -> Callable[[State], str]:
    def route(state: State) -> str:
        if state.get("status") == "failed" or not state.get("rca"):
            return "failed"
        rca: dict[str, Any] = state["rca"] or {}
        top = rca["hypotheses"][0]["confidence"]
        if (
            top < policy.confidence_threshold
            and rca.get("followups")
            and state.get("rounds", 0) + 1 < policy.max_rounds
            and len(state.get("llm_calls", [])) < policy.max_llm_calls
        ):
            return "followup"
        return _decide(state)

    return route


def _decide(state: State) -> str:
    rem = (state.get("rca") or {}).get("remediation") or {}
    return "propose" if rem.get("action_type") not in (None, "none") else "report"


def route_after_followup(state: State) -> str:
    return "dispatch" if state.get("task_queue") else _decide(state)


def route_after_propose(state: State) -> str:
    return "await_approval" if state.get("proposed_action") else "report"


def route_after_approval(state: State) -> str:
    return "execute" if (state.get("approval") or {}).get("decision") == "approve" else "report"
