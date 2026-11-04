#!/usr/bin/env bash
# Report installation and runtime health with remediation hints. Read-only.
source "$(dirname "$0")/lib.sh"
cd "$ROOT_DIR"; load_env
failures=0
bad() { fail "$1"; [[ -n "${2:-}" ]] && printf '    %sfix:%s %s\n' "$c_dim" "$c_off" "$2"; failures=$((failures + 1)); }

echo "== Host"
free_gb=$(df -g / | awk 'NR==2{print $4}')
[[ $free_gb -ge 30 ]] && ok "disk free: ${free_gb} GiB" || bad "low disk: ${free_gb} GiB free" "free space before pulling more models"
mem_free=$(memory_pressure 2>/dev/null | awk -F': ' '/free percentage/{gsub("%","",$2); print $2}')
[[ -n "$mem_free" && $mem_free -ge 15 ]] && ok "memory free: ${mem_free}%" || warn "memory free: ${mem_free:-?}% — close heavy apps before running investigations"

echo "== Tools"
for t in uv node pnpm docker ollama jq; do have $t && ok "$t: $($t --version 2>&1 | head -1)" || bad "$t missing" "make bootstrap ARGS=--install"; done
[[ -f .env ]] && ok ".env present" || bad ".env missing" "make bootstrap"

echo "== Ollama"
if curl -fsS "$OLLAMA_BASE_URL/api/version" >/dev/null 2>&1; then
  ok "API reachable at $OLLAMA_BASE_URL"
  for m in "$LLM_MODEL" "$EMBEDDING_MODEL"; do
    ollama list | awk 'NR>1{print $1}' | grep -qx "$m" && ok "model $m present" || bad "model $m missing" "ollama pull $m"
  done
  dim=$(curl -s "$OLLAMA_BASE_URL/api/embed" -d "{\"model\":\"$EMBEDDING_MODEL\",\"input\":\"doctor\"}" | jq '.embeddings[0] | length')
  [[ "$dim" == "$EMBEDDING_DIMENSIONS" ]] && ok "embedding dimension $dim matches EMBEDDING_DIMENSIONS" \
    || bad "embedding dimension $dim != EMBEDDING_DIMENSIONS=$EMBEDDING_DIMENSIONS" "set EMBEDDING_DIMENSIONS and re-run migrations + reindex"
  gen=$(curl -s --max-time 120 "$OLLAMA_BASE_URL/api/generate" -d "{\"model\":\"$LLM_MODEL\",\"prompt\":\"Reply with OK\",\"stream\":false,\"think\":false,\"options\":{\"num_predict\":5}}" | jq -r '.response // empty')
  [[ -n "$gen" ]] && ok "generation responds ($LLM_MODEL)" || bad "generation failed for $LLM_MODEL" "check: ollama ps; tail /opt/homebrew/var/log/ollama.log"
else
  bad "Ollama API not reachable" "brew services start ollama"
fi

echo "== Containers"
if docker_ready; then
  ok "docker engine reachable (context $(docker context show))"
  st=$(docker inspect -f '{{.State.Health.Status}}' opspilot-postgres 2>/dev/null || echo missing)
  [[ $st == healthy ]] && ok "postgres container healthy" || bad "postgres container: $st" "make infra-up"
  if [[ $st == healthy ]]; then
    ext=$(docker exec opspilot-postgres psql -U "$DB_USER" -d "$DB_NAME" -tAc "select extversion from pg_extension where extname='vector'" 2>/dev/null || true)
    [[ -n "$ext" ]] && ok "pgvector $ext enabled in $DB_NAME" || bad "pgvector not enabled" "scripts/db-ensure.sh"
    rev=$(docker exec opspilot-postgres psql -U "$DB_USER" -d "$DB_NAME" -tAc "select version_num from public.alembic_version" 2>/dev/null || true)
    [[ -n "$rev" ]] && ok "migrations applied (head $rev)" || bad "migrations not applied" "make migrate"
    docs=$(docker exec opspilot-postgres psql -U "$DB_USER" -d "$DB_NAME" -tAc "select count(*) from kb.documents" 2>/dev/null || echo 0)
    [[ ${docs:-0} -gt 0 ]] && ok "knowledge base: $docs documents" || warn "knowledge base empty — run: make ingest"
  fi
else
  bad "docker engine not reachable" "colima start  (or make infra-up)"
fi

echo "== Ports"
for p in "$API_PORT" 3000; do port_in_use "$p" && info "port $p in use ($(lsof -nP -iTCP:$p -sTCP:LISTEN | awk 'NR==2{print $1}'))" || info "port $p free"; done
if curl -fsS "http://$API_HOST:$API_PORT/health/ready" >/dev/null 2>&1; then ok "API ready at http://$API_HOST:$API_PORT"; else info "API not running (make dev)"; fi

echo
[[ $failures -eq 0 ]] && ok "doctor: all checks passed" || { fail "doctor: $failures check(s) failed"; exit 1; }
