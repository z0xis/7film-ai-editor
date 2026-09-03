#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")" && pwd)"
server_pid=""

cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill "$server_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

"$project_dir/scripts/run_app.sh" &
server_pid="$!"

for attempt in $(seq 1 30); do
  if /usr/bin/curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    /usr/bin/open http://127.0.0.1:8000/
    wait "$server_pid"
    exit $?
  fi
  sleep 1
done

echo "7Film AI Editor 30 saniye içinde başlamadı." >&2
exit 1

