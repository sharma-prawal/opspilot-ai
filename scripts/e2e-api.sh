#!/usr/bin/env bash
# API for the isolated E2E stack (audit finding 10). Started by Playwright's webServer, never by hand.
# Pinned to the dedicated test database; refuses to start against anything else.
source "$(dirname "$0")/lib.sh"
cd "$ROOT_DIR"; load_env
export DB_NAME="${TEST_DB_NAME:-opspilot_test}" OPSPILOT_INSTANCE=e2e
# Uploaded files of the E2E stack never mix with the dev stack's; E2E_LLM_MODEL tries a model for this process only.
export UPLOAD_DIR="${E2E_UPLOAD_DIR:-$ROOT_DIR/var/e2e-uploads}"
if [[ -n "${E2E_LLM_MODEL:-}" ]]; then export LLM_MODEL="$E2E_LLM_MODEL"; fi
# v0.6: E2E_TELEMETRY=1 connects this process (only) to the local synthetic Loki/Prometheus of `make telemetry-up`.
if [[ -n "${E2E_TELEMETRY:-}" ]]; then
  export LOKI_URL="http://127.0.0.1:${LOKI_PORT:-3310}" LOKI_TENANT_ID="${TELEMETRY_DEMO_TENANT:-opspilot-demo}"
  export PROMETHEUS_URL="http://127.0.0.1:${PROMETHEUS_PORT:-9390}"
  export TELEMETRY_TEMPLATES_FILE="infra/telemetry/query-templates.json"
fi
# v0.9: E2E_DATADOG=1 connects this process (only) to the synthetic Datadog fixture that Playwright starts on loopback
# (scripts/datadog_fixture.py), with the fixture's synthetic keys. The E2E stack never uses a real Datadog site or key.
if [[ -n "${E2E_DATADOG:-}" ]]; then
  export DATADOG_ENABLED=true DATADOG_SITE=datadoghq.com
  export DATADOG_LOCAL_API_URL="http://127.0.0.1:${E2E_DATADOG_PORT:-8127}"
  export DATADOG_API_KEY=fixture-api-key DATADOG_APP_KEY=fixture-app-key DATADOG_ENV= DATADOG_LOG_INDEXES=
else
  export DATADOG_ENABLED=false  # never inherit a developer's Datadog settings from .env
fi
# v0.10: E2E_AZURE=1 connects this process (only) to the synthetic Azure Monitor fixture on loopback, with the fixture
# credential (no Microsoft Entra call). The E2E stack never uses a real tenant, workspace or secret.
if [[ -n "${E2E_AZURE:-}" ]]; then
  export AZURE_MONITOR_ENABLED=true AZURE_MONITOR_AUTH_MODE=fixture
  export AZURE_MONITOR_LOCAL_API_URL="http://127.0.0.1:${E2E_AZURE_PORT:-8129}"
  export AZURE_MONITOR_WORKSPACE_ID="${E2E_AZURE_WORKSPACE:-6f1c2a9e-4b7d-4e2a-9c3b-0a5d7e8f1001}"
  export AZURE_TENANT_ID= AZURE_CLIENT_ID= AZURE_CLIENT_SECRET=
else
  export AZURE_MONITOR_ENABLED=false  # never inherit a developer's Azure settings from .env
fi
E2E_API_PORT="${E2E_API_PORT:-8100}"
[[ "$DB_NAME" == *_test ]] || { fail "E2E API refuses database '$DB_NAME' (must end in _test)"; exit 1; }
[[ "$E2E_API_PORT" != "${API_PORT:-8000}" ]] || { fail "E2E API port must differ from the dev API port"; exit 1; }
uv run opspilot migrate --database "$DB_NAME" >/dev/null
uv run opspilot ingest >/dev/null   # incremental; re-embeds test-DB documents with the real embedding model
exec env -u WEB_CONCURRENCY uv run uvicorn opspilot_api.main:app --host 127.0.0.1 --port "$E2E_API_PORT" --workers 1
