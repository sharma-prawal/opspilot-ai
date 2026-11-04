# Phase B evaluation artifacts (frozen)

Verbatim copies of the evaluation results committed at `9ec857c` (release v0.2.0), extracted with
`git show 9ec857c:<path>`. They are retained as historical artifacts: `make evaluate` overwrites
`results/*_latest.json`, `results/traces_latest/` and `docs/evaluation/BASELINE.md`, but never this folder.

- `agent_latest.json`, `retrieval_latest.json`: the Phase B summaries.
- `traces/`: the Phase B per-run traces. `tests/unit/test_plan_scoring.py` re-scores them with the C0 scorer.
- The Phase B baseline report is at `docs/evaluation/history/BASELINE_phase_b_9ec857c.md`.

Do not edit these files.
