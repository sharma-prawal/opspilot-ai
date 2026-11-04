#!/usr/bin/env bash
# API for the isolated E2E stack (audit finding 10). Started by Playwright's webServer, never by hand.
# Pinned to the dedicated test database; refuses to start against anything else.
source "$(dirname "$0")/lib.sh"
cd "$ROOT_DIR"; load_env
export DB_NAME="${TEST_DB_NAME:-opspilot_test}" OPSPILOT_INSTANCE=e2e
E2E_API_PORT="${E2E_API_PORT:-8100}"
[[ "$DB_NAME" == *_test ]] || { fail "E2E API refuses database '$DB_NAME' (must end in _test)"; exit 1; }
[[ "$E2E_API_PORT" != "${API_PORT:-8000}" ]] || { fail "E2E API port must differ from the dev API port"; exit 1; }
uv run opspilot migrate --database "$DB_NAME" >/dev/null
uv run opspilot ingest >/dev/null   # incremental; re-embeds test-DB documents with the real embedding model
exec uv run uvicorn opspilot_api.main:app --host 127.0.0.1 --port "$E2E_API_PORT"
