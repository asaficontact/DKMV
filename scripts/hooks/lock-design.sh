#!/usr/bin/env bash
# Blocks edits to the design prototype + tokens. Override: DESIGN_UNLOCK=1
set -euo pipefail
INPUT="$(cat)"
FILE_PATH="$(jq -r '.tool_input.file_path // ""' <<< "$INPUT")"
if [[ "$FILE_PATH" == *docs/design_docs/platform/* && "$FILE_PATH" != *PRD_*.md ]]; then
  if [[ "${DESIGN_UNLOCK:-0}" != "1" ]]; then
    echo "BLOCKED: design prototype '$FILE_PATH' is locked. Port tokens into platform/frontend instead. Set DESIGN_UNLOCK=1 to override." >&2
    exit 2
  fi
fi
exit 0
