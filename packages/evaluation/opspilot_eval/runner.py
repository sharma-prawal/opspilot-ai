"""``opspilot-eval [retrieval|agent|all|render] [--trials N] [--scenarios ...]``.

Results go to datasets/evaluation/results/*.json, full per-run diagnostic traces to
datasets/evaluation/results/traces_latest/, and a rendered docs/evaluation/BASELINE.md.
Nothing in BASELINE.md is typed by hand: it is generated from the result files.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opspilot_eval import agent_eval, agent_path_bench, resource_bench, retrieval_bench
from opspilot_shared.config import REPO_ROOT, get_settings
from opspilot_shared.logging import configure_logging

RESULTS = REPO_ROOT / "datasets/evaluation/results"
TRACES = RESULTS / "traces_latest"
BASELINE = REPO_ROOT / "docs/evaluation/BASELINE.md"


def _meta() -> dict[str, Any]:
    s = get_settings()
    try:
        commit = (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 - git from PATH is intended
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
                check=False,
            ).stdout.strip()
            or "uncommitted"
        )
    except OSError:
        commit = "unknown"

    def _git(*args: str) -> str:
        try:
            out = subprocess.run(["git", *args], capture_output=True, text=True, cwd=REPO_ROOT, check=False)  # noqa: S603,S607
            return out.stdout.strip()
        except OSError:
            return ""

    digest = None
    try:  # model identity beyond its tag (audit: provenance of evaluation runs)
        import httpx

        tags = httpx.get(f"{s.ollama_base_url}/api/tags", timeout=5).json().get("models", [])
        digest = next((m.get("digest") for m in tags if m.get("name") == s.llm_model), None)
    except Exception:  # provenance is best effort; the run itself does not depend on it
        digest = None
    from opspilot_agents.nodes import AgentPolicy

    policy = AgentPolicy()
    return {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": commit,
        "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "llm_model_digest": digest,
        "agent_policy": {
            "max_prompt_evidence": policy.max_prompt_evidence,
            "knowledge_section_expansion": policy.knowledge_section_expansion,
            "max_verification_checks": policy.max_verification_checks,
        },
        "llm_model": s.llm_model,
        "embedding_model": s.embedding_model,
        "machine": f"{platform.system()} {platform.machine()}",
        "python": platform.python_version(),
        "temperature": s.llm_temperature,
        "num_ctx": s.llm_num_ctx,
    }


async def run_retrieval() -> dict[str, Any]:
    from opspilot_api.container import Infrastructure  # composition root; eval may import anything
    from opspilot_mcp.gateway import connect_gateway

    settings = get_settings()
    infra = Infrastructure.create(settings)
    try:
        retriever = infra.retriever()
        out = {
            "meta": _meta(),
            "development": await retrieval_bench.run(retriever, path=retrieval_bench.QUESTIONS),
            "heldout": await retrieval_bench.run(retriever, path=retrieval_bench.HELDOUT, warmup=False),
        }
    finally:
        await infra.aclose()
    # Agent path (audit finding 8): the agent's own knowledge node over the production MCP read server.
    async with connect_gateway(settings, "read") as gw:
        out["agent_path"] = {
            "development": await agent_path_bench.run(gw, path=retrieval_bench.QUESTIONS),
            "heldout": await agent_path_bench.run(gw, path=retrieval_bench.HELDOUT),
        }
    return out


def _reset_traces(traces: Path) -> None:
    traces.mkdir(parents=True, exist_ok=True)
    for old in traces.glob("*.json"):  # traces of the previous evaluation run (written by this tool)
        old.unlink()


async def run_agent(trials: int, scenarios: list[str], traces: Path = TRACES) -> dict[str, Any]:
    from opspilot_api.demo import investigate
    from opspilot_api.runtime import AppRuntime

    rows: list[dict[str, Any]] = []
    async with AppRuntime.open(get_settings()) as rt:
        # C0-G4: only once this run owns execution (no API or other runtime on the database) are old traces reset.
        _reset_traces(traces)
        plan = [(s, i, "approve") for s in scenarios for i in range(trials)]
        if "INC-001" in scenarios:
            plan.append(("INC-001", trials, "reject"))  # rejection path: nothing may execute
        for scenario, trial, decision in plan:
            gt = agent_eval.load_truth(scenario)
            run = await investigate(rt, scenario, decision)
            row = {**agent_eval.score_run(run, gt), "trial": trial + 1, "decision": decision}
            if decision == "reject":
                row["executed_after_reject"] = run["executions_total"]
                row["outcome_correct"] = row["outcome"] == "remediation_rejected"
                row["plan_acceptable"] = run["executions_total"] == 0
            rows.append(row)
            (traces / f"{scenario}-{trial + 1}-{decision}.json").write_text(
                json.dumps({"score": row, "run": run}, indent=1, default=str)
            )
            print(
                json.dumps(
                    {
                        k: row[k]
                        for k in (
                            "scenario",
                            "trial",
                            "decision",
                            "outcome",
                            "outcome_correct",
                            "root_cause_correct",
                            "plan_acceptable",
                            "seconds_total",
                        )
                    }
                )
            )
    return {"meta": _meta(), "trials_per_scenario": trials, "summary": agent_eval.summarize(rows), "runs": rows}


async def run_resources() -> dict[str, Any]:
    return {"meta": _meta(), **(await resource_bench.run(get_settings()))}


def _fmt(v: Any) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def _retrieval_section(name: str, ret: dict[str, Any]) -> list[str]:
    out = [
        f"### {name} ({ret['questions']} questions)",
        "",
        "| Mode | Recall@5 | Recall@10 | MRR@10 | nDCG@10 | p50 | p95 | misses@5 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for mode, r in ret["modes"].items():
        o = r["overall"]
        out.append(
            f"| {mode} | {o['recall@5']:.3f} | {o['recall@10']:.3f} | {o['mrr@10']:.3f} | {o['ndcg@10']:.3f} | "
            f"{r['latency']['p50_ms']:.1f} ms | {r['latency']['p95_ms']:.1f} ms | {len(r.get('misses_at_5', []))} |"
        )
    out += ["", "nDCG@10 by query style:", "", "| Mode | exact-token | paraphrase |", "|---|---|---|"]
    for mode, r in ret["modes"].items():
        out.append(
            f"| {mode} | {r['by_style']['exact']['ndcg@10']:.3f} | {r['by_style']['paraphrase']['ndcg@10']:.3f} |"
        )
    misses = ret["modes"]["hybrid"].get("misses_at_5", [])
    if misses:
        out += ["", "Hybrid misses@5 (no relevant document in the top 5):", ""]
        out += [f"- `{m['id']}` ({m['style']}) top-3: {', '.join(m['top3'])}" for m in misses]
    return [*out, ""]


def render_baseline() -> None:
    def load(name: str) -> dict[str, Any] | None:
        p = RESULTS / f"{name}.json"
        return json.loads(p.read_text()) if p.exists() else None

    ret, agent, res = load("retrieval_latest"), load("agent_latest"), load("resources_latest")
    if agent and "by_scenario" not in agent.get("summary", {}):
        agent = None  # legacy single-scenario format from Phase A; regenerated by `opspilot-eval agent`
    out = [
        "# Evaluation Baseline",
        "",
        "> Generated by `make evaluate` from `datasets/evaluation/results/*_latest.json`. Do not edit by hand — "
        "numbers here are measured, not targets. Full per-run traces: `datasets/evaluation/results/traces_latest/`.",
        "",
    ]
    if ret and "heldout" in ret:
        m = ret["meta"]
        out += [
            "## Retrieval (measured)",
            "",
            f"Run {m['run_at']} · git `{m['git']}` · embeddings `{m['embedding_model']}` · {m['machine']} · "
            "document-level relevance, 30 chunks per query collapsed to a document ranking.",
            "",
        ]
        out += _retrieval_section("Held-out set", ret["heldout"])
        out += _retrieval_section("Development set (used while building; optimistic)", ret["development"])
    if ret and "agent_path" in ret:
        out += [
            "## Retrieval on the agent's path (measured)",
            "",
            "The agent's own knowledge node over the MCP read server: `search_runbooks` (top 5, non-incident "
            "types) + `get_historical_incidents` (top 3), lifecycle demotion, scored in RCA-prompt order. "
            "Relevance labels are document-level (a passage counts if it comes from a relevant document). "
            "Not comparable one-to-one with the document benchmark above (different unit and depth).",
            "",
            "| Set | questions | hit | doc recall | runbook-path recall | MRR | precision | passages | "
            "non-current passages | p50 | p95 |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for label, key in (("Held-out", "heldout"), ("Development", "development")):
            a = ret["agent_path"][key]
            o = a["overall"]
            out.append(
                f"| {label} | {a['questions']} | {_fmt(o['hit'])} | {_fmt(o['doc_recall'])} | "
                f"{_fmt(o['runbook_path_recall'])} | {_fmt(o['mrr'])} | {_fmt(o['precision'])} | "
                f"{_fmt(o['passages'])} | {a['non_current_passages']} | {a['latency']['p50_ms']} | "
                f"{a['latency']['p95_ms']} |"
            )
        misses = ret["agent_path"]["heldout"]["misses"]
        out += ["", "Held-out questions with no relevant passage supplied to the RCA prompt:", ""]
        out += [f"- `{x['id']}` ({x['style']}) top-3: {', '.join(x['top3'])}" for x in misses] or ["- none"]
        out.append("")
    if res:
        mm, lim = res["machine"], res["limits"]
        b, w, c = res["embedding_burst_bounded"], res["embedding_burst_wide"], res["chat_call"]
        out += [
            "## Resources on this machine (measured)",
            "",
            f"Run {res['meta']['run_at']} · git `{res['meta']['git']}` · {mm['chip']} · {mm['memory_gb']} GB · "
            f"limits: embeddings {lim['embedding_max_concurrency']} in flight, chat {lim['llm_max_concurrency']}, "
            f"investigations {lim['max_concurrent_investigations']} running / {lim['max_pending_investigations']} "
            "admitted. Ollama memory = RSS of all `ollama` processes, sampled every 100 ms.",
            "",
            "| Workload | wall ms | p50 ms | p95 ms | peak in flight | Ollama peak RSS MB |",
            "|---|---|---|---|---|---|",
            f"| {b['requests']} concurrent embeddings, bound {b['bound']} | {b['wall_ms']} | "
            f"{b['per_request']['p50_ms']} | {b['per_request']['p95_ms']} | {b['peak_in_flight']} | "
            f"{b['ollama_peak_rss_mb']} |",
            f"| {w['requests']} concurrent embeddings, bound {w['bound']} | {w['wall_ms']} | "
            f"{w['per_request']['p50_ms']} | {w['per_request']['p95_ms']} | {w['peak_in_flight']} | "
            f"{w['ollama_peak_rss_mb']} |",
            f"| one structured `{c['model']}` call ({c['prompt_tokens']}+{c['completion_tokens']} tokens) | "
            f"{c['wall_ms']} | — | — | 1 | {c['ollama_peak_rss_mb']} |",
            "",
            f"Ollama idle RSS (embedding model loaded): {res['ollama_idle_rss_mb']} MB. Models loaded afterwards: "
            + ", ".join(f"`{m['name']}` {m['size_mb']} MB" for m in res["loaded_models_after"])
            + ".",
            "",
        ]
    if agent:
        m, s = agent["meta"], agent["summary"]
        out += [
            "## Agent workflow (measured)",
            "",
            f"Run {m['run_at']} · git `{m['git']}` · LLM `{m['llm_model']}` (temperature {m['temperature']}, "
            f"num_ctx {m['num_ctx']}) · {agent['trials_per_scenario']} approve-everything trial(s) per scenario "
            "+ 1 INC-001 rejection trial.",
            "",
            "| Metric | Value |",
            "|---|---|",
        ]
        out += [f"| {k.replace('_', ' ')} | {_fmt(v)} |" for k, v in s.items() if k != "by_scenario"]
        out += [
            "",
            "### By scenario",
            "",
            "| Scenario | runs | outcome accuracy | root-cause accuracy | plan acceptable | outcomes | mean s |",
            "|---|---|---|---|---|---|---|",
        ]
        for sc, r in s["by_scenario"].items():
            out.append(
                f"| {sc} | {r['runs']} | {_fmt(r['outcome_accuracy'])} | {_fmt(r['root_cause_accuracy'])} | "
                f"{_fmt(r['plan_acceptable'])} | {', '.join(r['outcomes'])} | {r['mean_seconds']} |"
            )
        out += [
            "",
            "### Runs",
            "",
            "| Scenario | # | decision | outcome | executed | blocked by policy | cited (violations) |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in agent["runs"]:
            executed = ", ".join(x["action_type"] for x in r["executed"]) or "—"
            blocked = ", ".join(f"{a}:{c}" for a, c in r["blocked_by_policy"]) or "—"
            out.append(
                f"| {r['scenario']} | {r['trial']} | {r['decision']} | {r['outcome']} | {executed} | {blocked} | "
                f"{r['citations_total']} ({r['citation_violations']}) |"
            )
        out.append("")
    out += [
        "## Targets (not measurements)",
        "",
        "| Metric | Target |",
        "|---|---|",
        "| Outcome accuracy, all scenarios | 100% |",
        "| False-positive remediation rate (negative scenarios) | 0 |",
        "| Unsafe actions executed / approval bypass attempts | 0 / 0 |",
        "| Citation validity | 1.0 |",
        "| Hybrid nDCG@10 on the held-out set | ≥ best single retriever |",
        "",
        "## Caveats",
        "",
        "- One author wrote the corpus, scenarios, ground truth and both question sets. The held-out set was written "
        "afterwards in operator phrasing and checked for 5-gram overlap with the corpus, prompts, tests and the "
        "development set (none found), but it is not independently annotated.",
        "- Temperature 0 and a fixed seed make repeated trials near-deterministic: trials measure stability, not "
        "variance across model samples. Six scenarios is a small sample; rates are indicative.",
        "- Several safety rules were added after observing failures on these same scenarios (see docs/DECISIONS.md "
        "D25-D28), so agent results on them are not an unbiased estimate of behaviour on unseen incidents.",
    ]
    BASELINE.write_text("\n".join(out) + "\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="opspilot-eval")
    parser.add_argument("suite", nargs="?", default="all", choices=["all", "retrieval", "agent", "resources", "render"])
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--scenarios", nargs="*", default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="supplementary agent run: write results and traces to this new directory; the official latest "
        "results and BASELINE.md are left untouched",
    )
    args = parser.parse_args(argv)
    if args.out is not None:
        if args.suite != "agent":
            parser.error("--out is only supported for the agent suite")
        if args.out.exists() and any(args.out.iterdir()):
            parser.error(f"{args.out} exists and is not empty; supplementary runs never overwrite")
        configure_logging("WARNING", "console")
        scenarios = args.scenarios or agent_eval.scenarios_with_truth()
        data = asyncio.run(run_agent(args.trials, scenarios, traces=args.out / "traces"))
        (args.out / "agent.json").write_text(json.dumps(data, indent=2, default=str))
        print(f"agent (supplementary): wrote {args.out / 'agent.json'}")
        return
    configure_logging("WARNING", "console")
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    scenarios = args.scenarios or agent_eval.scenarios_with_truth()
    suites: list[tuple[str, Any]] = [
        ("retrieval", run_retrieval),
        ("resources", lambda: run_resources()),
        ("agent", lambda: run_agent(args.trials, scenarios)),
    ]
    for name, fn in suites:
        if args.suite in (name, "all"):
            data = asyncio.run(fn())
            for path in (RESULTS / f"{name}_{stamp}.json", RESULTS / f"{name}_latest.json"):
                path.write_text(json.dumps(data, indent=2, default=str))
            print(f"{name}: wrote {RESULTS / f'{name}_{stamp}.json'}")
    render_baseline()
    print(f"rendered {BASELINE}")


if __name__ == "__main__":
    main()
