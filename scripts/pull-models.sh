#!/usr/bin/env bash
# Explicit, opt-in download of the configured models (LLM_MODEL, EMBEDDING_MODEL from .env).
# Each is several GB. Nothing else in the project downloads models unless asked (bootstrap --pull-models).
source "$(dirname "$0")/lib.sh"
cd "$ROOT_DIR"
load_env
LLM_MODEL=${LLM_MODEL:-qwen3.5:9b-q4_K_M}
EMBEDDING_MODEL=${EMBEDDING_MODEL:-qwen3-embedding:0.6b}
OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-http://127.0.0.1:11434}
curl -fsS "$OLLAMA_BASE_URL/api/version" >/dev/null 2>&1 || { fail "Ollama API not reachable at $OLLAMA_BASE_URL"; exit 1; }
for m in "$LLM_MODEL" "$EMBEDDING_MODEL"; do
  if ollama list | awk 'NR>1{print $1}' | grep -qx "$m"; then ok "model $m present"; else
    info "pulling $m"; ollama pull "$m"; fi
done
if [[ -d .venv ]]; then
  info "checking $LLM_MODEL (capabilities + one structured-output call)"
  uv run opspilot models --probe >/dev/null && ok "models compatible" || { fail "model check failed: uv run opspilot models --probe"; exit 1; }
fi
