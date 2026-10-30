#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
PYTHON="$ROOT/runtime/python/bin/python3.12"
if [ ! -f "$PYTHON" ]; then
  echo "此包未包含本机运行环境。请下载对应芯片的 Mac 转写完整包。" >&2
  exit 1
fi
chmod u+x "$PYTHON"
for program in "$ROOT"/runtime/bin/*; do
  [ ! -f "$program" ] || chmod u+x "$program"
done
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1
exec "$PYTHON" -B "$ROOT/scripts/bundle_launcher.py" "$@"
