#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
runtime_bin="$project_dir/.runtime/mamba-root/envs/sevenfilm/bin"

if [[ ! -x "$runtime_bin/python" || ! -x "$runtime_bin/ffmpeg" ]]; then
  echo "7Film runtime bulunamadı. Kurulumun tamamlandığını doğrulayın." >&2
  exit 1
fi

cd "$project_dir"

# The desktop interface is a build artefact, so a fresh checkout has none and the engine falls
# back to the plain page under apps/api/sevenfilm/static. Building it takes under a second when
# its dependencies are already installed; when they are not, the fallback still serves.
if [[ ! -f "$project_dir/apps/desktop/dist/index.html" ]]; then
  if command -v npm >/dev/null && [[ -d "$project_dir/apps/desktop/node_modules" ]]; then
    echo "7Film masaüstü arayüzü derleniyor..." >&2
    (cd "$project_dir/apps/desktop" && npm run build) >&2 || \
      echo "Arayüz derlenemedi; basit sürüm kullanılacak." >&2
  else
    echo "Masaüstü arayüzü derlenmemiş. Tam sürüm için: cd apps/desktop && npm install && npm run build" >&2
  fi
fi

export PATH="$runtime_bin:$PATH"
export NUMBA_CACHE_DIR="$project_dir/.runtime/numba-cache"
export HF_HOME="$project_dir/.runtime/huggingface"
export HF_HUB_OFFLINE=1
mkdir -p "$NUMBA_CACHE_DIR"

exec "$runtime_bin/python" -m uvicorn sevenfilm.api:app \
  --app-dir "$project_dir/apps/api" \
  --host 127.0.0.1 \
  --port "${SEVENFILM_PORT:-8000}"
