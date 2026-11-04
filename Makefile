# OpsPilot AI developer commands. Run `make help`.
SHELL := /bin/bash
.DEFAULT_GOAL := help
PROFILES ?=
ARGS ?=
TRIALS ?= 2
TEST_DB ?= opspilot_test

help: ## Show available commands
	@awk 'BEGIN{FS=":.*## "} /^[a-zA-Z_-]+:.*## /{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Install/verify everything, start infra, migrate, ingest, seed (ARGS=--install allows brew installs)
	./scripts/bootstrap.sh $(ARGS)

doctor: ## Check toolchain, models, ports, database and configuration
	./scripts/doctor.sh

infra-up: ## Start Colima (if needed) and PostgreSQL (PROFILES="observability tools" for extras)
	PROFILES="$(PROFILES)" ./scripts/infra-up.sh

infra-down: ## Stop project containers (volumes are preserved)
	./scripts/infra-down.sh

migrate: ## Apply Alembic migrations + LangGraph checkpointer setup (app and test DBs)
	uv run opspilot migrate
	uv run opspilot migrate --database $(TEST_DB)

ingest: ## Ingest the synthetic knowledge base (incremental; ARGS=--reindex to rebuild)
	uv run opspilot ingest $(ARGS)

simulate: ## Create a simulated INC-001 incident
	uv run opspilot simulate --scenario INC-001

investigate: ## End-to-end CLI run: simulate, investigate, approve, print RCA report
	uv run opspilot investigate --scenario INC-001 --decision approve

dev: ## Start API + web in the background (skips anything already running)
	./scripts/start.sh

stop: ## Stop API + web started by `make dev`
	./scripts/stop.sh

test: ## Deterministic tests: Python (unit/integration/security) + web unit tests
	uv run pytest
	cd apps/web && pnpm test

test-live: ## Live local-model tests (needs Ollama)
	uv run pytest -m live_llm --run-live

e2e: ## Playwright UI tests on an isolated stack (API :8100 on opspilot_test, web :3100); uses the real model
	set -a; source .env; set +a; cd apps/web && pnpm e2e

lint: ## Ruff, mypy --strict, import-linter, ESLint, TypeScript
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy apps/api packages services
	uv run lint-imports
	cd apps/web && pnpm lint && pnpm typecheck

format: ## Auto-format Python
	uv run ruff format .
	uv run ruff check --fix .

evaluate: ## Retrieval benchmark + agent evaluation (TRIALS=3); renders docs/evaluation/BASELINE.md
	uv run opspilot-eval all --trials $(TRIALS)

build-web: ## Production build of the web app
	cd apps/web && pnpm build

.PHONY: help bootstrap doctor infra-up infra-down migrate ingest simulate investigate dev stop test test-live e2e lint format evaluate build-web
