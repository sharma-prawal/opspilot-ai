# Phase C0-H evaluation (official `make evaluate`, TRIALS=2)

- Code: `2116ef1` (H1 `1e28076`, H2 `5729dbb`, H3 `1635170`; audit artifacts `2116ef1`).
- `git_dirty=true`: only documentation (decisions, architecture/security/deployment docs, release notes, the C0-H record)
  was being edited during the run; no source, test, prompt, ground-truth or configuration change.
- Dev API stopped for the run; the evaluation added its rows to the dev database (additive). Migrations 0007/0008 were
  applied to the dev database beforehand. `qwen3:8b`, temperature 0, num_ctx 8192.
- Copied immediately after the run; earlier history directories untouched.
