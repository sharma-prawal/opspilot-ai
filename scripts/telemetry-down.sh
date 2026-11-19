#!/usr/bin/env bash
# Stop and remove the synthetic Loki/Prometheus containers (their tmpfs data goes with them; no volumes exist).
source "$(dirname "$0")/lib.sh"
load_env
compose --profile telemetry rm -sf loki prometheus
ok "telemetry test containers removed"
