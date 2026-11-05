# Phase C0-F evaluation artifacts (frozen)

Measured on 2026-11-05 with the code at commit `62a9e21` (branch `hardening/phase-c0`). `meta.git_dirty` is
`true` because documentation files were being edited during the run; no source file differed from `62a9e21`.
Model `qwen3:8b` (digest recorded in `meta.llm_model_digest`), temperature 0, num_ctx 8192, development DB.

- `agent_latest.json`, `retrieval_latest.json`, `resources_latest.json`, `BASELINE.md`, `traces/`: the official
  `make evaluate TRIALS=2` run (6 scenarios × 2 approve trials + 1 INC-001 rejection trial = 13 runs), copied
  verbatim from `datasets/evaluation/results/` and `docs/evaluation/BASELINE.md` straight after the run.
- `supplementary-inc002-x10/`: `opspilot-eval agent --trials 10 --scenarios INC-002 --out …` (agent only).
- `supplementary-neg-x3/`: `opspilot-eval agent --trials 3 --scenarios NEG-001 NEG-002 NEG-003 --out …`.

Supplementary runs use distinct incidents and never touch the official results. Temperature 0 and a fixed seed make
repeated trials near-deterministic: they measure stability, not sampling variance. No sealed unseen scenario set
exists, so these results are on the same (development) scenarios the gates were designed against.

Do not edit these files.
