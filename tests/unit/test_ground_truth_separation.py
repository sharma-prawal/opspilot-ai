"""C0-F5: answer keys stay out of everything the agent can reach (knowledge base, MCP, prompts, runtime).

Complements the import-linter contract ("nothing imports the evaluation harness"): a module could still open the
files by path, so the path itself is checked too.
"""

from pathlib import Path

from opspilot_eval.agent_eval import GROUND_TRUTH
from opspilot_shared.config import REPO_ROOT, get_settings

RUNTIME_SOURCES = ("apps/api", "packages/agents", "packages/mcp", "packages/rag", "packages/shared", "services")
# The only runtime-side mention: a docstring telling readers where answer keys live (not a file access).
ALLOWED_MENTIONS = {"services/simulator/opspilot_simulator/scenarios/base.py"}


def test_answer_keys_are_outside_the_knowledge_corpus() -> None:
    kb = get_settings().knowledge_dir.resolve()
    gt = GROUND_TRUTH.resolve()
    assert kb not in gt.parents and gt not in kb.parents and kb != gt


def test_no_runtime_module_references_the_answer_keys() -> None:
    hits = {
        str(p.relative_to(REPO_ROOT))
        for root in RUNTIME_SOURCES
        for p in (REPO_ROOT / root).rglob("*.py")
        if "ground_truth" in p.read_text(encoding="utf-8")
    }
    assert hits <= ALLOWED_MENTIONS, sorted(hits - ALLOWED_MENTIONS)
    for path in ALLOWED_MENTIONS:
        code = [
            line
            for line in Path(REPO_ROOT / path).read_text(encoding="utf-8").splitlines()
            if "ground_truth" in line
            and not line.lstrip().startswith(("#", '"', "'"))
            and "Answer keys live" not in line
        ]
        assert code == [], path
