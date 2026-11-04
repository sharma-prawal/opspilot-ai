# Decision Log

Architecture-level decisions have ADRs in `docs/adr/`. This log records the smaller engineering
decisions made during implementation, with the evidence behind them. Newest last.

| # | Date | Decision | Rationale / evidence |
|---|---|---|---|
| D1 | 2026-11-04 | Use Colima + Homebrew Docker CLI 29.9 / docker-compose 5.7; leave Docker Desktop 4.22 untouched | Desktop was never initialised, daemon down, CLI API 1.43 too old; Colima gives a capped VM (4 CPU/4 GiB/30 GiB). |
| D2 | 2026-11-04 | Scripts call standalone `docker-compose`, not `docker compose` | `~/.docker/cli-plugins` resolves to Desktop's stale v2.20 plugin; avoids editing the user's Docker config. |
| D3 | 2026-11-04 | One Python distribution, multiple top-level packages under the suggested monorepo dirs (hatch `packages` + `dev-mode-dirs`), one `uv.lock` | Clear boundaries without 7 pyprojects; boundaries enforced by import-linter instead. |
| D4 | 2026-11-04 | Python 3.13 (uv-managed), pinned `.python-version` | All dependencies support it; `requires-python >=3.12,<3.14`. |
| D5 | 2026-11-04 | `EMBEDDING_DIMENSIONS=1024` | Measured from live `/api/embed`, not assumed; ingestion rejects any vector of a different length. |
| D6 | 2026-11-04 | LangGraph checkpoint tables in schema `langgraph` via `search_path`; `setup()` only in `opspilot migrate` | Isolation from app schemas; no DDL on application start. |
| D7 | 2026-11-04 | Explicit `JsonPlusSerializer(allowed_msgpack_modules=None)` + JSON-only state | Strict deserialisation independent of import-time env; documented by langgraph-checkpoint security notes. |
| D8 | 2026-11-04 | Approval = DB compare-and-set **and** HMAC token (action_id + params_hash, TTL) verified by the action server, which executes the *persisted* parameters | Keeps `ops` single-writer, gives defence in depth, makes replay impossible (idempotency ledger `sim.action_executions`). |
| D9 | 2026-11-04 | Two MCP servers (read vs action) over stdio, one long-lived session each per API process | Write tools are not even visible to investigation nodes; no network port; ~1–2 s start-up once. |
| D10 | 2026-11-04 | Deterministic analysis (onset detection, log clustering, change correlation) in code; LLM for plan + RCA only | Small model is unreliable with numbers; 2 LLM calls per run keep latency ~25 s. |
| D11 | 2026-11-04 | No heuristic fallback for RCA | If the model fails, the investigation fails visibly with evidence retained, rather than masking model failure. |
| D12 | 2026-11-04 | `inline_schema` keeps a *property* named `title` | Bug found in first live run: stripping all `title` keys removed `hypotheses[].title` from the decoding grammar → 3 failed attempts. Regression test added. |
| D13 | 2026-11-04 | Category definitions in prompts; triage declared provisional | Model labelled a schema migration `configuration_error` and the alert-only triage `resource_exhaustion` (0.8). After the change: `deployment_regression` / `unknown` (0.3). |
| D14 | 2026-11-04 | `knowledge` capability is policy-mandated | Evaluation run showed `required_tools_used_rate = 0.0`: after a prompt edit the model stopped selecting knowledge, so RAG never ran. Now added by policy (noted in `plan.notes`); re-measured 1.0. |
| D15 | 2026-11-04 | Dispatch by data dependency: telemetry → dependencies → changes → knowledge | With plan order, `changes` ran before `dependencies` and scored the culprit migration 0.39; with dependency order it scores 1.00. |
| D16 | 2026-11-04 | Persist the partial result when the graph pauses | The UI showed "collecting evidence" at approval time; reviewers must see hypotheses before deciding. |
| D17 | 2026-11-04 | Log `contains` search uses escaped `ILIKE`, not full-text | PostgreSQL's parser tokenises `psycopg.errors.UndefinedColumn` as one host-like lexeme, so `UndefinedColumn` matched 0 rows (found by MCP protocol test). |
| D18 | 2026-11-04 | Keep RRF hybrid as default but **do not** claim it is better | Benchmark: hybrid nDCG@10 0.901 vs vector 0.932 (keyword 0.820); hybrid best on Recall@5 and ties on exact-token queries. Tuning RRF weights on a 30-question self-authored set would overfit; revisit with a held-out set or a reranker. |
| D19 | 2026-11-04 | Web UI talks only to a same-origin BFF route that injects the operator token server-side, with a path allowlist | Token never reaches the browser; traversal and non-allowlisted paths return 404 (verified). |
| D20 | 2026-11-04 | TanStack Query polling (2–5 s) instead of SSE for now | Simple, sufficient for one operator; SSE can be added on top of `workflow_events`. |
| D21 | 2026-11-04 | Playwright clicks that trigger client-side navigations use `noWaitAfter` + explicit `waitForURL` | Playwright's implicit post-click navigation wait never settled with Next 16 prefetching (reproduced in isolation; navigation itself committed fine). |
| D22 | 2026-11-04 | Evaluation has its own entry point (`opspilot-eval`) | import-linter flagged `opspilot_api.cli → opspilot_eval`; fixed the dependency instead of weakening the contract. |
| D23 | 2026-11-04 | Line length 120, `ruff format` as formatter | Consistent style across the codebase; formatter applied once to everything. |
