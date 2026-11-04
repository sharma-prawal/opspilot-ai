#!/usr/bin/env bash
# Start API and web in the background (skips anything already listening). Logs in .run/.
source "$(dirname "$0")/lib.sh"
cd "$ROOT_DIR"; load_env; mkdir -p "$RUN_DIR"

docker_ready && [[ "$(docker inspect -f '{{.State.Health.Status}}' opspilot-postgres 2>/dev/null)" == healthy ]] \
  || "$ROOT_DIR/scripts/infra-up.sh"

if port_in_use "$API_PORT"; then ok "API already listening on :$API_PORT — not starting another"; else
  nohup uv run uvicorn opspilot_api.main:app --host "$API_HOST" --port "$API_PORT" \
    >"$RUN_DIR/api.log" 2>&1 </dev/null &
  echo $! >"$RUN_DIR/api.pid"
  wait_for_http "http://$API_HOST:$API_PORT/health/live" 60 && ok "API started (pid $(cat "$RUN_DIR/api.pid"))" \
    || { fail "API failed to start — see .run/api.log"; tail -30 "$RUN_DIR/api.log"; exit 1; }
fi
if port_in_use 3000; then ok "web already listening on :3000 — not starting another"; else
  # Only the server command is backgrounded (not a `cd && …` list), with stdio detached from the caller.
  (cd apps/web || exit 1
   OPSPILOT_API_URL="$OPSPILOT_API_URL" OPERATOR_TOKEN="$OPERATOR_TOKEN" \
   OPSPILOT_WEB_SESSION_SECRET="${OPSPILOT_WEB_SESSION_SECRET:-}" \
   OPSPILOT_WEB_OPERATOR_PASSPHRASE="${OPSPILOT_WEB_OPERATOR_PASSPHRASE:-}" \
   OPSPILOT_WEB_VIEWER_PASSPHRASE="${OPSPILOT_WEB_VIEWER_PASSPHRASE:-}" OPSPILOT_WEB_ORIGIN="${OPSPILOT_WEB_ORIGIN:-}" \
     nohup pnpm dev --hostname 127.0.0.1 --port 3000 >"$RUN_DIR/web.log" 2>&1 </dev/null &
   echo $! >"$RUN_DIR/web.pid")
  wait_for_http "http://127.0.0.1:3000" 90 && ok "web started" || warn "web not responding yet — see .run/web.log"
fi
echo
echo "  Web UI     http://127.0.0.1:3000"
echo "  API docs   http://$API_HOST:$API_PORT/docs"
echo "  Ollama     $OLLAMA_BASE_URL"
echo "  Postgres   127.0.0.1:$DB_PORT/$DB_NAME"
