# Phase C0-G evaluation (official `make evaluate`, TRIALS=2)

- Code: `2d18d46` (G1–G4 fixes `d6d1901`, `7305815`, `37610db`, `95e79b9`, `748c069`; audit artifacts `2d18d46`).
- `git_dirty=true`: during the run only documentation files were being edited (architecture/security/deployment docs,
  DECISIONS, release notes, the C0-G record); no source, test, prompt, ground-truth or configuration file changed.
  This is a report, not reconstructable provenance (as noted by the independent audit).
- Dev API stopped for the run (`make stop`); the evaluation wrote its incidents/investigations to the dev database
  (additive). `qwen3:8b` digest `500a1f06…`, temperature 0, num_ctx 8192.
- Copied from `datasets/evaluation/results/` and `docs/evaluation/BASELINE.md` immediately after the run. Earlier
  phases' directories were not modified.
