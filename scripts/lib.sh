#!/usr/bin/env bash
# Shared helpers for OpsPilot scripts. Source, do not execute.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/compose/compose.yaml"
RUN_DIR="$ROOT_DIR/.run"
export HOMEBREW_NO_INSTALL_CLEANUP=1   # never let brew prune caches/kegs as a side effect

c_green=$'\033[32m'; c_red=$'\033[31m'; c_yellow=$'\033[33m'; c_dim=$'\033[2m'; c_off=$'\033[0m'
ok()   { printf '%s✔%s %s\n' "$c_green" "$c_off" "$*"; }
warn() { printf '%s!%s %s\n' "$c_yellow" "$c_off" "$*"; }
fail() { printf '%s✘%s %s\n' "$c_red" "$c_off" "$*"; }
info() { printf '%s→%s %s\n' "$c_dim" "$c_off" "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

load_env() {
  if [[ -f "$ROOT_DIR/.env" ]]; then
    set -a; # shellcheck disable=SC1091
    source "$ROOT_DIR/.env"; set +a
  fi
}

# Prefer the standalone docker-compose v2+/v5 binary; the `docker compose` plugin on this
# machine may resolve to a stale Docker Desktop plugin. Never edits ~/.docker/config.json.
compose() {
  if have docker-compose; then
    docker-compose --env-file "$ROOT_DIR/.env" -f "$COMPOSE_FILE" "$@"
  else
    docker compose --env-file "$ROOT_DIR/.env" -f "$COMPOSE_FILE" "$@"
  fi
}

docker_ready() { docker info >/dev/null 2>&1; }

port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

wait_for_http() { # url timeout_seconds
  local url=$1 timeout=${2:-30} i=0
  until curl -fsS "$url" >/dev/null 2>&1; do
    i=$((i + 1)); [[ $i -ge $timeout ]] && return 1; sleep 1
  done
}
