#!/usr/bin/env bash
# Start API and web in the background (skips anything already listening). Logs in .run/.
source "$(dirname "$0")/lib.sh"
export ROOT_DIR
cd "$ROOT_DIR"; load_env; mkdir -p "$RUN_DIR"

docker_ready && [[ "$(docker inspect -f '{{.State.Health.Status}}' opspilot-postgres 2>/dev/null)" == healthy ]] \
  || "$ROOT_DIR/scripts/infra-up.sh"

if port_in_use "$API_PORT"; then ok "API already listening on :$API_PORT — not starting another"; else
  # C0-G4: exactly one worker per database; the runtime also enforces it (advisory lock + WEB_CONCURRENCY check).
  nohup env -u WEB_CONCURRENCY uv run uvicorn opspilot_api.main:app --host "$API_HOST" --port "$API_PORT" --workers 1 \
    >"$RUN_DIR/api.log" 2>&1 </dev/null &
  echo $! >"$RUN_DIR/api.pid"
  wait_for_http "http://$API_HOST:$API_PORT/health/live" 60 && ok "API started (pid $(cat "$RUN_DIR/api.pid"))" \
    || { fail "API failed to start — see .run/api.log"; tail -30 "$RUN_DIR/api.log"; exit 1; }
fi
if port_in_use 3000; then ok "web already listening on :3000 — not starting another"; else
  python3 -c '
import os, sys
sys.path.insert(0, os.path.join(os.environ["ROOT_DIR"], "packages/shared"))
from opspilot_shared.web_env import spawn_web_server
spawn_web_server()
'
  wait_for_http "http://127.0.0.1:3000" 90 && ok "web started" || warn "web not responding yet — see .run/web.log"
fi
echo
echo "  Web UI     http://127.0.0.1:3000"
echo "  API docs   http://$API_HOST:$API_PORT/docs"
echo "  Ollama     $OLLAMA_BASE_URL"
echo "  Postgres   127.0.0.1:$DB_PORT/$DB_NAME"
