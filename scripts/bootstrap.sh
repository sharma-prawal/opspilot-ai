#!/usr/bin/env bash
# Idempotent bootstrap. Detects existing installs and reuses them.
# Installing missing system tools requires consent: pass --install or set OPSPILOT_ALLOW_INSTALL=1.
source "$(dirname "$0")/lib.sh"
cd "$ROOT_DIR"
ALLOW_INSTALL=${OPSPILOT_ALLOW_INSTALL:-0}
[[ "${1:-}" == "--install" ]] && ALLOW_INSTALL=1

need_brew_pkg() { # binary formula
  if have "$1"; then ok "$1 present ($(command -v "$1"))"; return; fi
  if [[ $ALLOW_INSTALL == 1 ]] && have brew; then
    info "installing $2 via Homebrew"; brew install "$2"
  else
    fail "$1 missing — install with: brew install $2  (or rerun: make bootstrap ARGS=--install)"; exit 1
  fi
}

echo "== Prerequisites"
have brew || warn "Homebrew not found; system tools must be installed manually"
need_brew_pkg uv uv
need_brew_pkg node node
have pnpm || { info "enabling pnpm via corepack"; corepack enable pnpm; }
need_brew_pkg ollama ollama
if docker info >/dev/null 2>&1; then ok "existing Docker engine works — reusing it"; else
  need_brew_pkg colima colima; need_brew_pkg docker docker; fi
have docker-compose || docker compose version >/dev/null 2>&1 || need_brew_pkg docker-compose docker-compose

echo "== Environment file"
if [[ -f .env ]]; then ok ".env exists — leaving it untouched"; else
  rnd() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-32}"; }
  sed -e "s/^POSTGRES_SUPERUSER_PASSWORD=.*/POSTGRES_SUPERUSER_PASSWORD=$(rnd 32)/" \
      -e "s/^DB_PASSWORD=.*/DB_PASSWORD=$(rnd 32)/" \
      -e "s/^OPERATOR_TOKEN=.*/OPERATOR_TOKEN=$(rnd 40)/" -e "s/^ACTION_SIGNING_KEY=.*/ACTION_SIGNING_KEY=$(rnd 48)/" \
      -e "s/^OPSPILOT_WEB_SESSION_SECRET=.*/OPSPILOT_WEB_SESSION_SECRET=$(rnd 48)/" \
      -e "s/^MCP_READ_DB_PASSWORD=.*/MCP_READ_DB_PASSWORD=$(rnd 32)/" \
      -e "s/^MCP_ACTIONS_DB_PASSWORD=.*/MCP_ACTIONS_DB_PASSWORD=$(rnd 32)/" \
      -e "s/^OPSPILOT_WEB_OPERATOR_PASSPHRASE=[^ ]*/OPSPILOT_WEB_OPERATOR_PASSPHRASE=$(rnd 20)/" .env.example > .env
  chmod 600 .env; ok ".env created with random local secrets"
fi
# Upgrade older .env files with settings added later (never overwrites existing values).
for key in OPSPILOT_WEB_SESSION_SECRET OPSPILOT_WEB_OPERATOR_PASSPHRASE MCP_READ_DB_PASSWORD MCP_ACTIONS_DB_PASSWORD; do
  if ! grep -q "^${key}=" .env; then
    rnd() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-32}"; }
    printf '%s=%s\n' "$key" "$(rnd 40)" >> .env; ok "added $key to .env"
  fi
done
info "web sign-in passphrase: see OPSPILOT_WEB_OPERATOR_PASSPHRASE in .env"
load_env

echo "== Ollama"
if ! curl -fsS "$OLLAMA_BASE_URL/api/version" >/dev/null 2>&1; then
  if have brew && brew list ollama >/dev/null 2>&1; then brew services start ollama; else
    warn "start Ollama manually (open the Ollama app or run: ollama serve)"; fi
  wait_for_http "$OLLAMA_BASE_URL/api/version" 30 || { fail "Ollama API not reachable"; exit 1; }
fi
ok "Ollama $(curl -s "$OLLAMA_BASE_URL/api/version" | jq -r .version) at $OLLAMA_BASE_URL"
for m in "$LLM_MODEL" "$EMBEDDING_MODEL"; do
  if ollama list | awk 'NR>1{print $1}' | grep -qx "$m"; then ok "model $m present"; else
    info "pulling $m"; ollama pull "$m"; fi
done

echo "== Project dependencies"
uv sync --frozen 2>/dev/null || uv sync
ok "python environment ready (.venv)"
(cd apps/web && pnpm install --frozen-lockfile 2>/dev/null || pnpm install)
ok "web dependencies installed"

echo "== Infrastructure, migrations, data"
"$ROOT_DIR/scripts/infra-up.sh"
uv run opspilot migrate
uv run opspilot migrate --database "${TEST_DB_NAME:-opspilot_test}" >/dev/null
"$ROOT_DIR/scripts/db-roles.sh"   # least-privilege roles for the MCP server processes
uv run opspilot ingest
uv run opspilot simulate --scenario INC-001 --if-none
echo "== Doctor"
"$ROOT_DIR/scripts/doctor.sh"
