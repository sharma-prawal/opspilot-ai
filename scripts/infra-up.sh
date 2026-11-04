#!/usr/bin/env bash
# Start the container runtime (if needed) and PostgreSQL. Reuses anything already running.
source "$(dirname "$0")/lib.sh"
load_env
[[ -f "$ROOT_DIR/.env" ]] || { fail ".env missing — run make bootstrap"; exit 1; }

if ! docker_ready; then
  if have colima; then
    info "starting Colima (4 CPU / 4 GiB / 30 GiB)"
    colima start --cpus 4 --memory 4 --disk 30 --vm-type vz --runtime docker
  else
    fail "no working Docker engine and Colima not installed (run make bootstrap)"; exit 1
  fi
fi
ok "docker engine reachable ($(docker version --format '{{.Server.Version}}'))"

profiles=()
for p in ${PROFILES:-}; do profiles+=(--profile "$p"); done
compose ${profiles[@]+"${profiles[@]}"} up -d
info "waiting for postgres health"
for _ in $(seq 1 60); do
  status=$(docker inspect -f '{{.State.Health.Status}}' opspilot-postgres 2>/dev/null || echo missing)
  [[ $status == healthy ]] && break; sleep 2
done
[[ $status == healthy ]] || { fail "postgres not healthy (status=$status)"; compose logs --tail 50 postgres; exit 1; }
ok "postgres healthy on 127.0.0.1:${DB_PORT}"
"$ROOT_DIR/scripts/db-ensure.sh"
