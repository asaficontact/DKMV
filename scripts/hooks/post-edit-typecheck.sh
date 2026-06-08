#!/usr/bin/env bash
# After an edit, typecheck/lint the file's language. Backend: ruff+mypy. Frontend: tsc.
# Gracefully no-ops if the project dir or toolchain isn't present yet (early scaffolding).
set -euo pipefail
INPUT="$(cat)"
FILE_PATH="$(jq -r '.tool_input.file_path // ""' <<< "$INPUT")"
[[ -z "$FILE_PATH" ]] && exit 0
case "$FILE_PATH" in
  *platform/backend/*.py)
    DIR="${FILE_PATH%%platform/backend/*}platform/backend"
    [[ -d "$DIR" ]] || exit 0
    command -v ruff >/dev/null 2>&1 || exit 0
    ( cd "$DIR" && ruff check . && { command -v mypy >/dev/null 2>&1 && mypy app || true; } ) 2>&1 | tail -25 \
      || { echo "BACKEND LINT/TYPECHECK FAILED (ruff/mypy) — see above." >&2; exit 2; } ;;
  *platform/frontend/*.ts|*platform/frontend/*.tsx)
    DIR="${FILE_PATH%%platform/frontend/*}platform/frontend"
    [[ -d "$DIR/node_modules" ]] || exit 0
    ( cd "$DIR" && npx --no-install tsc --noEmit ) 2>&1 | tail -25 \
      || { echo "FRONTEND TYPECHECK FAILED (tsc) — see above." >&2; exit 2; } ;;
  *) exit 0 ;;
esac
exit 0
