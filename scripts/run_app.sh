#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
runtime_bin="$project_dir/.runtime/mamba-root/envs/sevenfilm/bin"

if [[ ! -x "$runtime_bin/python" || ! -x "$runtime_bin/ffmpeg" ]]; then
  echo "7Film runtime bulunamadı. Kurulumun tamamlandığını doğrulayın." >&2
  exit 1
fi

cd "$project_dir"
export PATH="$runtime_bin:$PATH"
export NUMBA_CACHE_DIR="$project_dir/.runtime/numba-cache"
export HF_HOME="$project_dir/.runtime/huggingface"
export HF_HUB_OFFLINE=1
mkdir -p "$NUMBA_CACHE_DIR"

exec "$runtime_bin/python" -m uvicorn sevenfilm.api:app \
  --app-dir "$project_dir/apps/api" \
  --host 127.0.0.1 \
  --port "${SEVENFILM_PORT:-8000}"
