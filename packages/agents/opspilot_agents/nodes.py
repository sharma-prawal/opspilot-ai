"""Investigation graph nodes.

Each node is ``async (state) -> partial state update``. Nodes only talk to the outside world
through the ``ChatModel`` and ``ToolGateway`` ports. Nodes up to and including ``await_approval``
are side-effect free (re-execution on resume is safe); the only state-changing call is in
``execute``, which runs strictly after a validated, action-bound approval — once per plan step.
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
    detect_shift,
    has_schema_signals,
    lexical_overlap_bonus,
    mean,
)
from opspilot_agents.impact import MIN_POINTS, assess_impact
from opspilot_agents.ports import ToolGateway, ToolResult
from opspilot_agents.prompts import PlanOutput, RcaOutput, plan_messages, rca_messages
from opspilot_agents.remediation import enforce_plan_shape, validate_step
from opspilot_agents.report import determine_outcome, render_report
from opspilot_agents.state import CAPABILITIES, InvestigationState, Task, task_key
from opspilot_agents.uncertainty import uncertainty_reasons
from opspilot_agents.verification import (
    Condition,
    evaluate_metric,
    evaluate_postcondition,
    metric_conditions,
    overall,
    postcondition_conditions,
)
from opspilot_shared.approvals import action_params_hash
from opspilot_shared.domain.actions import REMEDIATION_CATALOG, ActionType
from opspilot_shared.domain.common import utcnow
from opspilot_shared.domain.evidence import Citation, Evidence, EvidenceKind, ToolCallStatus
from opspilot_shared.domain.incidents import ImpactState, IncidentCategory
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
METRIC_PRIORITY = (
    "http_5xx_ratio",
    "p95_latency_ms",
    "events_processed_per_min",
    "validation_failures_per_min",
    "dlq_depth",
    "queue_depth",
    "db_pool_in_use",
    "db_pool_wait_ms",
    "consumer_retries_per_min",
    "http_requests_per_min",
)
MAX_METRICS_PER_SERVICE = 6


@dataclass(frozen=True, slots=True)
class AgentPolicy:
    max_tool_calls: int = 60
    max_llm_calls: int = 6
    max_rounds: int = 2
    confidence_threshold: float = 0.6
    ambiguity_margin: float = 0.1  # top-two hypotheses closer than this with disjoint evidence => withheld
    lookback_hours: float = 3.0
    change_horizon_hours: float = 6.0
    recovery_threshold: float = 0.01
    max_verification_checks: int = 16  # explicit budget; unchecked required conditions => incomplete
    max_prompt_evidence: int = 34


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


def _fmt(unit: str, v: float) -> str:
    if unit == "ratio":
        return f"{v:.2%}"
    if unit == "ms":
        return f"{v:.0f} ms"
    return f"{v:.0f} {unit}".strip()


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


def _queued_or_done(state: State, key: str, extra: list[Task] | None = None) -> bool:
    keys = set(state.get("completed_tasks", [])) | {task_key(t) for t in state.get("task_queue", [])}
    keys |= {task_key(t) for t in (extra or [])}
    return key in keys


def _complete(state: State, task: Task | None) -> list[str]:
    done = list(state.get("completed_tasks", []))
    if task is not None:
        done.append(task_key(task))
    return done


def _enqueue(state: State, new: list[Task], task: Task) -> None:
    if not _queued_or_done(state, task_key(task), new):
        new.append(task)


def _impact(state: State) -> dict[str, Any]:
    """Tri-state, evidence-based impact on the alerting service (see impact.py)."""
    return assess_impact(dict(state)).model_dump(mode="json")


def _anomalies(state: State, services: set[str] | None = None) -> list[dict[str, Any]]:
    return [
        e
        for e in state.get("evidence", {}).values()
        if e["kind"] == "metric_anomaly"
        and e["data"].get("anomaly", True)
        and (services is None or e.get("service") in services)
    ]


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
            "executions": [],
            "plan_index": 0,
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
        catalog_res = await calls.one("list_service_metrics", {"environment_id": env, "service": svc})
        catalog = {m["metric"]: m["unit"] for m in ((catalog_res.data or {}).get("metrics", []) if catalog_res else [])}
        chosen = [m for m in METRIC_PRIORITY if m in catalog][:MAX_METRICS_PER_SERVICE]
        results = await calls.many(
            [("query_metrics", {**base, "metric": m}) for m in chosen]
            + [
                ("search_logs", {**base, "min_level": "WARN", "limit": 300}),
                ("get_service_health", {"environment_id": env, "service": svc}),
            ]
        )
        metric_results, rlogs, rhealth = results[: len(chosen)], results[-2], results[-1]
        evidence: dict[str, dict[str, Any]] = {}
        findings: list[str] = []
        new_tasks: list[Task] = []
        onset: datetime | None = None

        coverage: dict[str, Any] = {
            "metrics_requested": chosen,
            "metrics_ok": [],
            "metrics_failed": {},
            "metrics_insufficient": [],
            "health_status": None,
            "catalog_failed": not (catalog_res and catalog_res.ok),
        }
        if coverage["catalog_failed"]:
            eid, ev = _evidence(
                id=f"ev-toolerr-{short_hash(svc, 'list_service_metrics')}",
                kind=EvidenceKind.TOOL_ERROR,
                source_tool="list_service_metrics",
                collected_by="telemetry",
                service=svc,
                relevance=0.7,
                summary=f"Metric catalogue for {svc} unavailable: "
                f"{catalog_res.error if catalog_res else 'tool budget exhausted'}. Metric evidence is missing.",
                data={"tool": "list_service_metrics", "error": catalog_res.error if catalog_res else "budget"},
            )
            evidence[eid] = ev
        for metric, res in zip(chosen, metric_results, strict=True):
            if not res or not res.ok or not res.data:
                err = res.error if res else "tool budget exhausted"
                coverage["metrics_failed"][metric] = err
                eid, ev = _evidence(
                    id=f"ev-toolerr-{short_hash(svc, 'query_metrics', metric)}",
                    kind=EvidenceKind.TOOL_ERROR,
                    source_tool="query_metrics",
                    collected_by="telemetry",
                    service=svc,
                    relevance=0.7,
                    summary=f"Metric {metric} for {svc} could not be retrieved: {err}. "
                    "This is not evidence of recovery.",
                    data={"tool": "query_metrics", "metric": metric, "error": err},
                )
                evidence[eid] = ev
                continue
            unit = catalog.get(metric, "")
            pts = [(_dt(p["ts"]), float(p["value"])) for p in res.data["points"]]
            if len(pts) < MIN_POINTS:
                coverage["metrics_insufficient"].append(metric)
                continue
            coverage["metrics_ok"].append(metric)
            sh = detect_shift(pts, metric=metric, unit=unit)
            if sh:
                if not sh.recovered and (onset is None or sh.onset < onset):
                    onset = sh.onset
                verb = "rose" if sh.direction == "up" else "fell"
                status = "returned to baseline (recovered)" if sh.recovered else f"currently {_fmt(unit, sh.current)}"
                eid, ev = _evidence(
                    id=f"ev-metric-{short_hash(svc, metric, sh.onset)}",
                    kind=EvidenceKind.METRIC_ANOMALY,
                    source_tool="query_metrics",
                    collected_by="telemetry",
                    service=svc,
                    relevance=0.55 if sh.recovered else 0.9,
                    observed_at=sh.onset,
                    summary=(
                        f"{svc} {metric} {verb} from baseline {_fmt(unit, sh.baseline)} to "
                        f"{_fmt(unit, sh.extreme)} starting {_hhmm(sh.onset)}; {status}"
                    ),
                    data={
                        "metric": metric,
                        "unit": unit,
                        "direction": sh.direction,
                        "baseline": sh.baseline,
                        "extreme": sh.extreme,
                        "peak": sh.extreme,
                        "current": sh.current,
                        "onset": _iso(sh.onset),
                        "recovered": sh.recovered,
                        "points": len(pts),
                    },
                )
                evidence[eid] = ev
                findings.append(f"{metric} {verb} from {_hhmm(sh.onset)}{' (recovered)' if sh.recovered else ''}")
            elif pts and metric in ("http_5xx_ratio", "p95_latency_ms"):
                avg = mean([v for _, v in pts])
                eid, ev = _evidence(
                    id=f"ev-metric-{short_hash(svc, metric, 'steady')}",
                    kind=EvidenceKind.METRIC_ANOMALY,
                    source_tool="query_metrics",
                    collected_by="telemetry",
                    service=svc,
                    relevance=0.3,
                    summary=f"{svc} {metric} shows no sustained anomaly in the window (mean {_fmt(unit, avg)})",
                    data={"metric": metric, "unit": unit, "anomaly": False, "mean": avg},
                )
                evidence[eid] = ev

        if rlogs and not rlogs.ok:
            eid, ev = _evidence(
                id=f"ev-toolerr-{short_hash(svc, 'search_logs')}",
                kind=EvidenceKind.TOOL_ERROR,
                source_tool="search_logs",
                collected_by="telemetry",
                service=svc,
                relevance=0.7,
                summary=f"Logs for {svc} could not be retrieved: {rlogs.error}. Log evidence for {svc} is missing.",
                data={"tool": "search_logs", "error": rlogs.error},
            )
            evidence[eid] = ev
            findings.append(f"logs unavailable for {svc}")
        elif rlogs and rlogs.data:
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
            errors = [p for p in patterns if p.level == "ERROR"]
            if errors:
                findings.append(f"top error: {errors[0].sample[:160]} (x{errors[0].count})")

        if rhealth and rhealth.ok and rhealth.data:
            h = rhealth.data
            coverage["health_status"] = h["status"]
            eid, ev = _evidence(
                id=f"ev-health-{short_hash(svc, h['as_of'])}",
                kind=EvidenceKind.SERVICE_HEALTH,
                source_tool="get_service_health",
                collected_by="telemetry",
                service=svc,
                relevance=0.6 if h["status"] not in ("healthy", "unknown") else 0.3,
                summary=f"{svc} health {h['status']} at {_hhmm(h['as_of'])}, version {h['version']}; "
                f"{'; '.join(h['notes'])}",
                data=h,
            )
            evidence[eid] = ev

        # Evidence-driven routing: any anomalous service gets its dependencies examined.
        if any(e["kind"] == "metric_anomaly" and e["data"].get("anomaly", True) for e in evidence.values()):
            _enqueue(
                state,
                new_tasks,
                {
                    "capability": "dependencies",
                    "service": svc,
                    "reason": f"{svc} shows anomalies; examine its dependencies and capacity",
                },
            )

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
            "telemetry_coverage": {svc: coverage},
            "task_queue": [*state.get("task_queue", []), *new_tasks],
            "completed_tasks": _complete(state, task),
        }

    # -- dependency, capacity and queue walk ----------------------------------------
    async def dependencies(self, state: State) -> Update:
        task = state.get("active_task")
        svc = (task["service"] if task else None) or state["incident"]["service"]
        env = state["incident"]["environment_id"]
        calls = _Calls(self.d.tools, state, self.p, "dependencies")
        rdeps, rcfg = await calls.many(
            [
                ("get_service_dependencies", {"environment_id": env, "service": svc}),
                ("get_service_config", {"environment_id": env, "service": svc}),
            ]
        )
        evidence: dict[str, dict[str, Any]] = {}
        new_tasks: list[Task] = []
        findings: list[str] = []
        if rcfg and rcfg.ok and rcfg.data:
            c = rcfg.data
            shown = ", ".join(f"{k}={v}" for k, v in list(c["config"].items())[:8])
            eid, ev = _evidence(
                id=f"ev-config-{short_hash(svc, 'current')}",
                kind=EvidenceKind.SERVICE_CONFIG,
                source_tool="get_service_config",
                collected_by="dependencies",
                service=svc,
                relevance=0.5,
                summary=f"{svc} runtime config: replicas {c['replicas']}, version {c['version']}; {shown}",
                data=c,
            )
            evidence[eid] = ev
        upstream_mentions = {
            e["data"].get("attributes", {}).get("upstream")
            for e in state.get("evidence", {}).values()
            if e["kind"] == "log_pattern" and e.get("service") == svc and e["data"]["level"] == "ERROR"
        }
        if rdeps and rdeps.ok and rdeps.data:
            downstream = rdeps.data["downstream"]
            health_targets = [
                d
                for d in downstream
                if d["kind"] == "sync_http" and (d["critical"] or d["depends_on"] in upstream_mentions)
            ]
            ds_targets = [d for d in downstream if d["kind"] == "database"]
            q_targets = [d for d in downstream if d["kind"] == "async_queue"]
            results = await calls.many(
                [("get_service_health", {"environment_id": env, "service": d["depends_on"]}) for d in health_targets]
                + [("get_datastore_status", {"environment_id": env, "datastore": d["depends_on"]}) for d in ds_targets]
                + [("inspect_queue", {"environment_id": env, "queue": d["depends_on"]}) for d in q_targets]
            )
            h_res = results[: len(health_targets)]
            ds_res = results[len(health_targets) : len(health_targets) + len(ds_targets)]
            q_res = results[len(health_targets) + len(ds_targets) :]
            for dep, h in zip(health_targets, h_res, strict=True):
                status = h.data["status"] if h and h.ok and h.data else "unknown"
                notes = "; ".join(h.data["notes"]) if h and h.ok and h.data else (h.error if h else "budget")
                eid, ev = _evidence(
                    id=f"ev-dep-{short_hash(svc, dep['depends_on'], status)}",
                    kind=EvidenceKind.DEPENDENCY,
                    source_tool="get_service_health",
                    collected_by="dependencies",
                    service=dep["depends_on"],
                    relevance=0.75 if status in ("unhealthy", "degraded") else 0.3,
                    summary=(
                        f"{svc} -> {dep['depends_on']} ({'critical' if dep['critical'] else 'non-critical'} "
                        f"{dep['kind']}): {dep['depends_on']} is {status}; {notes}"
                    ),
                    data={"edge": dep, "health": h.data if h and h.ok else None},
                )
                evidence[eid] = ev
                findings.append(f"{dep['depends_on']} {status}")
                if status in ("unhealthy", "degraded"):
                    _enqueue(
                        state,
                        new_tasks,
                        {
                            "capability": "telemetry",
                            "service": dep["depends_on"],
                            "reason": f"downstream {dep['depends_on']} of {svc} is {status}",
                        },
                    )
            for dep, r in zip(ds_targets, ds_res, strict=True):
                if not r or not r.ok or not r.data:
                    continue
                d = r.data
                usable = d["max_connections"] - d.get("reserved_superuser_connections", 0)
                util = d["connections_active"] / max(usable, 1)
                lrq = d.get("long_running_queries") or []
                lrq_txt = (
                    "; ".join(
                        f"{q['sessions']} sessions of '{q['fingerprint'][:140]}' mean {q['mean_ms']} ms ({q['plan']})"
                        for q in lrq[:2]
                    )
                    or "no long-running queries"
                )
                eid, ev = _evidence(
                    id=f"ev-ds-{short_hash(dep['depends_on'], d['as_of'])}",
                    kind=EvidenceKind.DATASTORE,
                    source_tool="get_datastore_status",
                    collected_by="dependencies",
                    service=dep["depends_on"],
                    relevance=0.85 if (util > 0.8 or lrq) else 0.35,
                    summary=(
                        f"{dep['depends_on']} connections {d['connections_active']}/{d['max_connections']} "
                        f"({util:.0%} of usable {usable}); by client {d['connections_by_client']}; pool limits "
                        f"{d['client_pool_limits']}; {lrq_txt}"
                    ),
                    data=d,
                )
                evidence[eid] = ev
                findings.append(f"{dep['depends_on']} at {util:.0%} connection capacity")
            for _dep, r in zip(q_targets, q_res, strict=True):
                if not r or not r.ok or not r.data:
                    continue
                q = r.data
                fails = (
                    "; ".join(
                        f"{f['error_code']} x{f['count']} from producer {f['producer_version']} "
                        f"schema {f['schema_version']} ({f['error']})"
                        for f in q["failures"][:3]
                    )
                    or "none"
                )
                eid, ev = _evidence(
                    id=f"ev-queue-{short_hash(q['queue'], q['as_of'], q['pending'], q['dead_lettered'])}",
                    kind=EvidenceKind.QUEUE,
                    source_tool="inspect_queue",
                    collected_by="dependencies",
                    service=(q.get("consumer") or {}).get("service"),
                    relevance=0.85 if (q["failures"] or q["dead_lettered"]) else 0.3,
                    summary=(
                        f"queue {q['queue']} (expects {q['expected_schema']}): consumer "
                        f"{q['consumer'].get('service')} {q['consumer'].get('state')}; pending {q['pending']}, "
                        f"dead-lettered {q['dead_lettered']}, quarantined {q['quarantined']}; producers "
                        f"{q['producers']}; failures: {fails}"
                    ),
                    data=q,
                )
                evidence[eid] = ev
                findings.append(f"{q['queue']}: {q['dead_lettered']} dead-lettered")
        obs = {
            "agent": "dependencies",
            "service": svc,
            "finding": f"{svc} dependencies: {', '.join(findings) or 'none'}",
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
        ev_all = list(state.get("evidence", {}).values())
        affected = {e["service"] for e in _anomalies(state) if e.get("service")}
        related = {
            e["service"]
            for e in ev_all
            if e["kind"] in ("dependency", "datastore", "service_config") and e.get("service")
        } | {state["incident"]["service"]}
        for e in ev_all:
            if e["kind"] == "queue":
                related |= set(e["data"].get("producers", []))
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
        signals = [
            f"{e['data']['sample']} {e['data'].get('attributes', {})}"
            for e in ev_all
            if e["kind"] == "log_pattern" and e["data"]["level"] in ("ERROR", "WARN")
        ]
        signals += [f["error"] or "" for e in ev_all if e["kind"] == "queue" for f in e["data"].get("failures", [])]
        signals += [
            f"{f['schema_version']}" for e in ev_all if e["kind"] == "queue" for f in e["data"].get("failures", [])
        ]
        signals += [
            q["fingerprint"]
            for e in ev_all
            if e["kind"] == "datastore"
            for q in e["data"].get("long_running_queries", [])
        ]
        evidence: dict[str, dict[str, Any]] = {}
        scored: list[tuple[float, str, str]] = []
        for d in (rdep.data or {}).get("deployments", []) if rdep and rdep.ok else []:
            effective = _dt(d["finished_at"] or d["started_at"])
            base = change_correlation(
                effective,
                onset,
                change_service=d["service"],
                affected_services=affected,
                related_services=related,
                schema_change=d["kind"] == "schema_migration",
                schema_signals=schema_signals,
            )
            bonus, shared = lexical_overlap_bonus(f"{d['change_summary']} {d.get('metadata', {})}", signals)
            score = round(min(1.0, base + bonus), 4) if base > 0 else 0.0
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
                    + (f" (shares terms with failures: {', '.join(shared)})" if shared and base > 0 else "")
                ),
                data={**d, "minutes_before_onset": delta, "correlation": score, "shared_terms": shared},
            )
            evidence[eid] = ev
            scored.append((score, d["service"], eid))
        for c in (rcfg.data or {}).get("changes", []) if rcfg and rcfg.ok else []:
            changed = _dt(c["changed_at"])
            base = change_correlation(
                changed,
                onset,
                change_service=c["service"],
                affected_services=affected,
                related_services=related,
                schema_change=False,
                schema_signals=False,
            )
            bonus, shared = lexical_overlap_bonus(f"{c['key']} {c['old_value']} {c['new_value']}", signals)
            score = round(min(1.0, base + bonus), 4) if base > 0 else 0.0
            delta = round((onset - changed).total_seconds() / 60, 1)
            eid, ev = _evidence(
                id=f"ev-cfgchg-{short_hash(c['id'])}",
                kind=EvidenceKind.CONFIG_CHANGE,
                source_tool="get_config_changes",
                collected_by="changes",
                service=c["service"],
                relevance=max(score, 0.05),
                observed_at=changed,
                summary=(
                    f"{c['service']} config {c['key']} {c['old_value']} -> {c['new_value']} (id {c['id']}) at "
                    f"{_hhmm(changed)}, {delta} min before onset; correlation {score:.2f}"
                ),
                data={**c, "minutes_before_onset": delta, "correlation": score},
            )
            evidence[eid] = ev
            scored.append((score, c["service"], eid))
        scored.sort(reverse=True)
        new_tasks: list[Task] = []
        if scored and scored[0][0] >= 0.5:
            _enqueue(
                state,
                new_tasks,
                {
                    "capability": "telemetry",
                    "service": scored[0][1],
                    "reason": f"strongly correlated change on {scored[0][1]} ({scored[0][2]})",
                },
            )
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
            (e for e in ev if e["kind"] == "log_pattern" and e["data"]["level"] in ("ERROR", "WARN")),
            key=lambda e: (e["data"]["level"] != "ERROR", -e["data"]["count"]),
        )
        changes = sorted((e for e in ev if e["kind"] in ("deployment", "config_change")), key=lambda e: -e["relevance"])
        parts = [e["data"]["signature"].replace("<uuid>", "").replace("<n>", "")[:160] for e in errors[:2]]
        parts += [
            e["summary"][:160]
            for e in ev
            if e["kind"] in ("datastore", "queue", "tool_error") and e["relevance"] >= 0.7
        ][:1]
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
                ("search_runbooks", {"query": query, "top_k": 5}),
                ("get_historical_incidents", {"query": query, "top_k": 3}),
            ]
        )
        evidence: dict[str, dict[str, Any]] = {}
        retrieved_at = utcnow()
        for res, kind in ((rrun, EvidenceKind.KNOWLEDGE), (rinc, EvidenceKind.HISTORICAL_INCIDENT)):
            if not res or not res.ok or not res.data:
                continue
            for rank, hit in enumerate(res.data["results"], start=1):
                status = (hit.get("metadata") or {}).get("status")
                marker = f"[{status.upper()}] " if status and status != "current" else ""
                eid, item = _evidence(
                    id=f"ev-kb-{hit['chunk_id'].replace('-', '')[:12]}",
                    kind=kind,
                    source_tool=res.tool,
                    collected_by="knowledge",
                    relevance=round(max(0.2, 0.8 - 0.1 * rank) * (0.5 if marker else 1), 2),
                    summary=f"{marker}[{hit['title']} > {hit['heading_path']}] {hit['snippet'][:420]}",
                    citation=Citation(
                        document_id=hit["document_id"],
                        chunk_id=hit["chunk_id"],
                        source_uri=hit["source_uri"],
                        title=hit["title"],
                        heading_path=hit["heading_path"],
                        document_version=hit.get("document_version"),
                        passage=hit.get("content") or hit["snippet"],
                        passage_sha256=hit.get("content_sha256"),
                        lifecycle_status=status or "current",
                        retrieved_at=retrieved_at,
                    ),
                    data={
                        "rank": rank,
                        "score": hit["score"],
                        "query_id": res.data["query_id"],
                        "doc_type": hit["doc_type"],
                        "doc_status": status,
                        "vector_rank": hit.get("vector_rank"),
                        "keyword_rank": hit.get("keyword_rank"),
                    },
                )
                evidence[eid] = item
        warnings = [w for r in (rrun, rinc) if r and r.ok and r.data for w in r.data.get("warnings", [])]
        degraded = [
            r.data.get("effective_mode")
            for r in (rrun, rinc)
            if r and r.ok and r.data and r.data.get("effective_mode") not in (None, r.data.get("mode"))
        ]
        obs = {
            "agent": "knowledge",
            "service": None,
            "finding": f"retrieved {len(evidence)} cited passages for query: {query[:200]}"
            + (f" (retrieval degraded: {warnings[0]})" if warnings else ""),
            "evidence_ids": list(evidence),
            "retrieval": {"warnings": warnings, "degraded_to": sorted({str(d) for d in degraded})},
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
                "impact": _impact(state),
                "impact_ongoing": _impact(state)["state"] == ImpactState.ONGOING.value,
                "impact_ongoing_model": value.impact_ongoing,
                "remediation_plan": [s.model_dump(exclude_none=True) for s in value.remediation_plan],
                "escalation": value.escalation.model_dump(),
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

    # -- remediation plan (validated against catalogue + evidence) -------------------
    async def propose(self, state: State) -> Update:
        rca = state["rca"] or {}
        evidence = state.get("evidence", {})
        plan: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for step in rca.get("remediation_plan", []):
            check = validate_step(step, evidence, state["incident"]["service"])
            if not check.ok or check.params is None:
                rejected.append(
                    {
                        "proposal": step,
                        "reason": check.reason,
                        "category": check.category,
                        "details": check.details,
                        "at": _iso(utcnow()),
                    }
                )
                _log.warning("remediation_rejected", reason=check.reason, category=check.category, proposal=step)
                continue
            params_hash = action_params_hash(check.action_type, check.params)
            if params_hash in seen:
                continue
            seen.add(params_hash)
            spec = REMEDIATION_CATALOG[ActionType(check.action_type)]
            plan.append(
                {
                    "action_id": str(stable_uuid("action", state["investigation_id"], len(plan), params_hash)),
                    "action_type": check.action_type,
                    "parameters": check.params,
                    "params_hash": params_hash,
                    "rationale": str(step.get("rationale", "")),
                    "risk": spec.risk.value,
                    "role": spec.role.value,
                    "step": len(plan) + 1,
                    "hypothesis_rank": 1,
                    "proposed_at": _iso(utcnow()),
                    "validation": check.details,
                }
            )
        impact = _impact(state)
        if plan and impact["state"] != ImpactState.ONGOING.value:
            recovered = impact["state"] == ImpactState.RECOVERED.value
            rejected += [
                {
                    "proposal": {k: p[k] for k in ("action_type", "parameters")},
                    "category": "unwarranted" if recovered else "insufficient_evidence",
                    "reason": (
                        "impact has ended on the alerting service; no remediation is warranted"
                        if recovered
                        else "impact on the alerting service is unknown ("
                        + "; ".join(impact["reasons"])
                        + "); remediation requires affirmative evidence of ongoing impact"
                    ),
                    "at": _iso(utcnow()),
                }
                for p in plan
            ]
            plan = []
        uncertain = uncertainty_reasons(
            state, confidence_threshold=self.p.confidence_threshold, ambiguity_margin=self.p.ambiguity_margin
        )
        if plan and uncertain:  # explicit uncertainty policy: never ask for approval of an uncertain diagnosis
            rejected += [
                {
                    "proposal": {k: p[k] for k in ("action_type", "parameters")},
                    "category": "withheld_uncertain",
                    "reason": "proposal withheld: " + "; ".join(uncertain),
                    "uncertainty": uncertain,
                    "at": _iso(utcnow()),
                }
                for p in plan
            ]
            _log.info("remediation_withheld", reasons=uncertain, steps=len(plan))
            plan = []
        plan, dropped = enforce_plan_shape(plan)
        rejected += [{**d, "at": _iso(utcnow())} for d in dropped]
        # Completeness: a containment that halts processing must be undone by the plan itself.
        paused = [p["parameters"]["service"] for p in plan if p["action_type"] == "pause_consumer"]
        resumed = {p["parameters"]["service"] for p in plan if p["action_type"] == "resume_consumer"}
        for svc_name in paused:
            if svc_name in resumed:
                continue
            check = validate_step(
                {"action_type": "resume_consumer", "service": svc_name}, evidence, state["incident"]["service"]
            )
            if check.ok and check.params is not None:
                ph = action_params_hash(check.action_type, check.params)
                spec = REMEDIATION_CATALOG[ActionType.RESUME_CONSUMER]
                plan.append(
                    {
                        "action_id": "",
                        "action_type": check.action_type,
                        "parameters": check.params,
                        "params_hash": ph,
                        "risk": spec.risk.value,
                        "role": spec.role.value,
                        "added_by": "policy",
                        "rationale": "policy: a paused consumer must be resumed once the cause is resolved",
                        "hypothesis_rank": 1,
                        "proposed_at": _iso(utcnow()),
                        "validation": None,
                    }
                )
        for i, p in enumerate(plan):
            p["step"], p["plan_size"] = i + 1, len(plan)
            p["action_id"] = str(stable_uuid("action", state["investigation_id"], i, p["params_hash"]))
        return {
            "remediation_plan": plan,
            "plan_index": 0,
            "proposed_action": plan[0] if plan else None,
            "rejected_proposals": rejected,
        }

    # -- human-in-the-loop ----------------------------------------------------------
    async def await_approval(self, state: State) -> Update:
        action = state["proposed_action"]
        assert action is not None
        decision = interrupt(
            {
                "type": "approval_required",
                "action": action,
                "plan": [
                    {k: p[k] for k in ("step", "action_type", "parameters", "role")}
                    for p in state.get("remediation_plan", [])
                ],
            }
        )
        if not isinstance(decision, dict):
            raise ApprovalError("resume payload must be an object")
        if decision.get("action_id") != action["action_id"] or decision.get("params_hash") != action["params_hash"]:
            raise ApprovalError("resume payload does not match the pending action")
        kind = decision.get("decision")
        if kind not in ("approve", "reject", "expired"):
            raise ApprovalError("decision must be approve, reject or expired")
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

    # -- sandbox execution (one plan step) ------------------------------------------
    async def execute(self, state: State) -> Update:
        action, approval = state["proposed_action"], state["approval"]
        assert action is not None and approval is not None and approval["decision"] == "approve"
        if self.d.actions is None:
            result: dict[str, Any] = {"status": "failed", "message": "no action gateway configured"}
            return {
                "remediation": result,
                "executions": [*state.get("executions", []), {**result, "step": action["step"]}],
            }
        calls = _Calls(self.d.actions, state, self.p, "remediation")
        res = await calls.one(
            "execute_remediation", {"action_id": action["action_id"], "approval_token": approval["approval_token"]}
        )
        if res is None or not res.ok or res.data is None:
            result = {
                "action_id": action["action_id"],
                "status": "failed",
                "message": (res.error if res else "tool budget exhausted"),
            }
        else:
            result = {**res.data}
        record = {**result, "step": action["step"], "action_type": action["action_type"], "role": action.get("role")}
        # The token has been spent (or refused); drop it so later checkpoints no longer carry it (finding E).
        spent = {**approval, "approval_token": None}
        return {
            **calls.update(),
            "approval": spent,
            "remediation": result,
            "executions": [*state.get("executions", []), record],
        }

    async def advance(self, state: State) -> Update:
        idx = state.get("plan_index", 0) + 1
        return {"plan_index": idx, "proposed_action": state["remediation_plan"][idx], "approval": None}

    async def verify(self, state: State) -> Update:
        """Check every required recovery condition (see verification.py); never silently truncate."""
        executions = state.get("executions", [])
        last = executions[-1] if executions else {}
        svc = state["incident"]["service"]
        if last.get("status") != "succeeded":
            return {
                "verification": {
                    "status": "not_recovered",
                    "recovered": False,
                    "service": svc,
                    "checks": [],
                    "notes": f"remediation step did not succeed: {last.get('message')}",
                }
            }
        details = last.get("details") or {}
        start, end = details.get("executed_at_sim"), details.get("sim_now_after")
        evidence = state.get("evidence", {})
        top = ((state.get("rca") or {}).get("hypotheses") or [{}])[0]
        culprits = {
            evidence[i]["service"] for i in top.get("supporting_evidence_ids", []) if evidence.get(i, {}).get("service")
        }
        anomalies = [a for a in _anomalies(state, {svc} | culprits) if not a["data"].get("recovered")]
        metric_conds, informational = metric_conditions(anomalies)
        post_conds = postcondition_conditions(executions, state.get("remediation_plan") or [], evidence)
        required = [*metric_conds, *post_conds]
        calls = _Calls(self.d.tools, state, self.p, "verify")
        budget = min(self.p.max_verification_checks, max(calls.remaining, 0))
        env = state["incident"]["environment_id"]

        def plan_call(c: Condition) -> tuple[str, dict[str, Any]]:
            if c.kind == "metric":
                return "query_metrics", {
                    "environment_id": env,
                    "service": c.service,
                    "metric": c.name,
                    "start": start,
                    "end": end,
                }
            kind = c.name.split(":", 1)[0]
            if kind == "rolled_back":
                begin = c.spec.get("started_at") or start
                return "list_recent_deployments", {"environment_id": env, "start": begin, "end": end}
            if kind == "pool_size":
                return "get_service_config", {"environment_id": env, "service": c.service}
            return "inspect_queue", {"environment_id": env, "queue": c.spec["queue"]}

        # Deduplicate identical tool calls (e.g. two postconditions on the same queue) so the budget counts reads.
        planned: dict[str, tuple[str, dict[str, Any]]] = {}
        for c in required:
            tool, args = plan_call(c)
            planned.setdefault(f"{tool}:{sorted(args.items())}", (tool, args))
        keys = list(planned)
        checked_keys, omitted_keys = keys[:budget], keys[budget:]
        results = await calls.many([planned[k] for k in checked_keys])
        by_key = dict(zip(checked_keys, results, strict=True))
        checks: list[dict[str, Any]] = []
        for c in required:
            tool, args = plan_call(c)
            key = f"{tool}:{sorted(args.items())}"
            if key in omitted_keys:
                checks.append(
                    {
                        "kind": c.kind,
                        "service": c.service,
                        "name": c.name,
                        "evidence_id": c.evidence_id,
                        "status": "not_checked",
                        "detail": "verification budget exhausted",
                    }
                )
                continue
            r = by_key[key]
            data = r.data if r and r.ok else None
            if c.kind == "metric":
                pts = [float(p["value"]) for p in data["points"]] if data else None
                check = evaluate_metric(c, pts)
            else:
                check = evaluate_postcondition(c, data)
            if r is not None:
                check["tool_call_id"] = r.record.id
                if not r.ok:
                    check["detail"] = f"{check.get('detail', '')}; tool error: {r.error}".strip("; ")
            checks.append(check)
        status = overall(checks)
        failed = [c for c in checks if c["status"] == "failed"]
        unknown = [c for c in checks if c["status"] in ("unknown", "not_checked")]
        notes = (
            f"{len(checks)} required condition(s): {len(checks) - len(failed) - len(unknown)} passed, "
            f"{len(failed)} failed, {len(unknown)} unknown/not checked"
        )
        if failed:
            notes += "; failed: " + ", ".join(f"{c.get('service') or ''} {c['name']}".strip() for c in failed)
        if unknown:
            notes += "; unverified: " + ", ".join(f"{c.get('service') or ''} {c['name']}".strip() for c in unknown)
        return {
            **calls.update(),
            "verification": {
                "status": status,
                "recovered": status == "recovered",
                "service": svc,
                "checks": checks,
                "informational": informational,
                "required": len(required),
                "budget": budget,
                "omitted": len([c for c in checks if c["status"] == "not_checked"]),
                "window_start": start,
                "window_end": end,
                "notes": notes,
                "criterion": "every required metric back inside its healthy band and every action postcondition met",
            },
        }

    # -- report / terminal ----------------------------------------------------------
    async def report(self, state: State) -> Update:
        final = {**state, "status": "completed"}
        outcome = determine_outcome(final, self.p.confidence_threshold)
        final["outcome"] = outcome
        return {
            "report": {"markdown": render_report(final), "generated_at": _iso(utcnow())},
            "status": "completed",
            "outcome": outcome,
        }

    async def failed(self, state: State) -> Update:
        final = {**state, "status": "failed"}
        outcome = determine_outcome(final, self.p.confidence_threshold)
        final["outcome"] = outcome
        return {
            "status": "failed",
            "outcome": outcome,
            "report": {"markdown": render_report(final), "generated_at": _iso(utcnow())},
        }


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
    return "propose" if (state.get("rca") or {}).get("remediation_plan") else "report"


def route_after_followup(state: State) -> str:
    return "dispatch" if state.get("task_queue") else _decide(state)


def route_after_propose(state: State) -> str:
    return "await_approval" if state.get("proposed_action") else "report"


def route_after_approval(state: State) -> str:
    return "execute" if (state.get("approval") or {}).get("decision") == "approve" else "report"


def route_after_execute(state: State) -> str:
    succeeded = (state.get("remediation") or {}).get("status") == "succeeded"
    more = state.get("plan_index", 0) + 1 < len(state.get("remediation_plan") or [])
    return "advance" if succeeded and more else "verify"
