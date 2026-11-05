# Frozen evaluation artifacts

Each directory is a copy of an official `make evaluate` (or a named supplementary run) taken right after it ran.
They are never rewritten; `datasets/evaluation/results/` holds only the latest run.

- `phase-b-9ec857c/` — Phase B (v0.2.0) evaluation, preserved verbatim (see its README).
- `phase-c0-cc275d7/` — Phase C0 evaluation, INC-002 supplementary and ablation runs.
- `phase-c0f-62a9e21/` — Phase C0-F official evaluation plus INC-002 ×10 and negative ×3 supplementary runs (see its README).
- `phase-c0g-2d18d46/` — Phase C0-G official evaluation after the G1–G4 safety fixes (see its README).
