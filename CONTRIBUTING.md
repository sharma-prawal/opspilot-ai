# Contributing

1. `make bootstrap` (once) and `make doctor`.
2. Create a branch; keep changes focused.
3. Before pushing: `make lint && make test`. If you changed agent behaviour, prompts, retrieval or the
   simulator, also run `make evaluate` and include the BASELINE diff in your PR.
4. Architecture-level changes need an ADR in `docs/adr/` (problem, alternatives, decision, rationale,
   tradeoffs, consequences) and an entry in `docs/DECISIONS.md`.
5. Do not commit `.env`, model files, or anything outside the synthetic datasets. Only synthetic data is accepted.

Code style: ruff (format + lint, 120 cols), mypy `--strict`, typed pydantic contracts at every boundary, no
business logic in route handlers. Commit messages: imperative mood, explain *why*.
