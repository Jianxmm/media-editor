#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
if [ "${1:-}" = setup ]; then exec /bin/bash "$ROOT/setup.command"; fi
PYTHON="$ROOT/runtime/python/bin/python3.12"
RUNTIME="$ROOT"
if [ ! -f "$PYTHON" ] && [ -f "$ROOT/.runtime-path" ]; then
  IFS= read -r RUNTIME < "$ROOT/.runtime-path" || true
  PYTHON="$RUNTIME/runtime/python/bin/python3.12"
fi
if [ ! -f "$PYTHON" ]; then
  /bin/bash "$ROOT/setup.command" >&2
  RUNTIME="$(cat "$ROOT/.runtime-path")"
  PYTHON="$RUNTIME/runtime/python/bin/python3.12"
fi
chmod u+x "$PYTHON"
for program in "$RUNTIME"/runtime/bin/*; do
  [ ! -f "$program" ] || chmod u+x "$program"
done
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1
exec "$PYTHON" -B "$ROOT/scripts/bundle_launcher.py" "$@"
