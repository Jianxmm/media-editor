#!/bin/bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")" && pwd)"
VERSION="$(tr -d '\r\n' < "$ROOT/VERSION")"
case "$(uname -m)" in arm64) TARGET=macos-arm64;; x86_64) TARGET=macos-x64;; *) echo '不支持的Mac芯片' >&2; exit 1;; esac
BASE="${MEDIA_EDITOR_COMPONENT_BASE_URL:-https://github.com/Jianxmm/media-editor/releases/download/v$VERSION}"
CACHE="${MEDIA_EDITOR_RUNTIME_CACHE:-$HOME/Library/Application Support/media-editor}"
mkdir -p "$CACHE"
WORK="$(mktemp -d "$CACHE/.bootstrap-XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
curl --fail --location --retry 2 "$BASE/components-$TARGET.json" -o "$WORK/catalog.json"
# macOS ships JXA; no separately installed Python is needed to read the catalog.
read_field() { /usr/bin/osascript -l JavaScript -e 'ObjC.import("Foundation");function run(a){var s=$.NSString.stringWithContentsOfFileEncodingError(a[0],$.NSUTF8StringEncoding,null).js;return JSON.parse(s).runtime[a[1]];}' "$WORK/catalog.json" "$1"; }
NAME="$(read_field name)"; SHA="$(read_field sha256)"
case "$NAME" in media-editor-runtime-macos-*.zip) ;; *) echo '组件文件名无效' >&2; exit 1;; esac
curl --fail --location --retry 2 "$BASE/$NAME" -o "$WORK/runtime.zip"
echo "$SHA  $WORK/runtime.zip" | shasum -a 256 -c -
/usr/bin/ditto -x -k "$WORK/runtime.zip" "$WORK/program"
PYTHON="$WORK/program/media-editor/runtime/python/bin/python3.12"
chmod u+x "$PYTHON"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1
"$PYTHON" -B "$ROOT/scripts/manage_runtime.py" --catalog "$WORK/catalog.json" --cache "$CACHE" --base-url "$BASE" --runtime-source "$WORK/program/media-editor"
