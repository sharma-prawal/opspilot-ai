#!/usr/bin/env bash
# Start the local Loki + Prometheus test setup with synthetic telemetry (v0.6). Nothing here reaches a real system:
# both containers listen on 127.0.0.1 only and keep their data in tmpfs (no volumes).
source "$(dirname "$0")/lib.sh"
load_env
docker_ready || { fail "no working Docker engine (run make infra-up first)"; exit 1; }
LOKI="http://127.0.0.1:${LOKI_PORT:-3310}"
PROM="http://127.0.0.1:${PROMETHEUS_PORT:-9390}"
TENANT="${TELEMETRY_DEMO_TENANT:-opspilot-demo}"

uv run python scripts/generate_telemetry.py
# Recreate so Prometheus backfills the freshly generated history into its empty tmpfs.
compose --profile telemetry up -d --force-recreate loki prometheus
info "waiting for Loki and Prometheus"
for _ in $(seq 1 60); do
  curl -fsS "$LOKI/ready" >/dev/null 2>&1 && curl -fsS "$PROM/-/ready" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS "$LOKI/ready" >/dev/null || { fail "Loki not ready"; compose logs --tail 30 loki; exit 1; }
curl -fsS "$PROM/-/ready" >/dev/null || { fail "Prometheus not ready"; compose logs --tail 30 prometheus; exit 1; }
uv run python scripts/generate_telemetry.py --push "$LOKI" --tenant "$TENANT"
ok "Loki $LOKI (tenant $TENANT) and Prometheus $PROM are seeded with the synthetic incident of 2026-11-12 08:00-10:00Z"
cat <<MSG
To use them, add to .env (or the API process environment) and restart the API:
  LOKI_URL=$LOKI
  LOKI_TENANT_ID=$TENANT
  PROMETHEUS_URL=$PROM
  TELEMETRY_TEMPLATES_FILE=infra/telemetry/query-templates.json
MSG
