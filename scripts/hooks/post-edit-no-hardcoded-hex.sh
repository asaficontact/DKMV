#!/usr/bin/env bash
# Block hardcoded hex colors in frontend source (use design tokens). INV-14.
set -euo pipefail
INPUT="$(cat)"
FILE_PATH="$(jq -r '.tool_input.file_path // ""' <<< "$INPUT")"
case "$FILE_PATH" in
  *platform/frontend/src/*.ts|*platform/frontend/src/*.tsx|*platform/frontend/src/*.css)
    # allow the canonical tokens file(s)
    case "$FILE_PATH" in */styles/tokens.css) exit 0 ;; esac
    if grep -nE '#[0-9a-fA-F]{3,8}\b' "$FILE_PATH" >/dev/null 2>&1; then
      echo "BLOCKED: hardcoded hex color in '$FILE_PATH'. Use a design token (INV-14)." >&2
      grep -nE '#[0-9a-fA-F]{3,8}\b' "$FILE_PATH" | head -10 >&2
      exit 2
    fi ;;
esac
exit 0
