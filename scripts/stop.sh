#!/usr/bin/env bash
# Stop processes started by scripts/start.sh — only the recorded PIDs and their descendants.
# Infrastructure (Postgres, Colima, Ollama) is left running.
source "$(dirname "$0")/lib.sh"

descendants() { local c; for c in $(pgrep -P "$1" 2>/dev/null); do descendants "$c"; echo "$c"; done; }

for svc in api web; do
  pidf="$RUN_DIR/$svc.pid"
  if [[ -f $pidf ]] && kill -0 "$(cat "$pidf")" 2>/dev/null; then
    pid=$(cat "$pidf")
    tree="$(descendants "$pid") $pid"
    kill -TERM $tree 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    ok "stopped $svc (pid $pid and $(($(wc -w <<<"$tree") - 1)) child process(es))"
  else info "$svc not running (no live pid file)"; fi
  rm -f "$pidf"
done
