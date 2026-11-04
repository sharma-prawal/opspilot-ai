#!/usr/bin/env bash
# Stop project containers. Volumes are preserved; Colima is left running (other projects may use it).
source "$(dirname "$0")/lib.sh"
load_env
compose --profile observability --profile tools stop
ok "containers stopped (volume opspilot_pgdata preserved). Stop the VM with: colima stop"
