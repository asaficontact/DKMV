#!/usr/bin/env bash
# Blocks edits to the dkmv engine (consume only). Override: ENGINE_UNLOCK=1
set -euo pipefail
INPUT="$(cat)"
FILE_PATH="$(jq -r '.tool_input.file_path // ""' <<< "$INPUT")"
# match the engine package dkmv/ but NOT the platform or docs trees
if [[ "$FILE_PATH" == */dkmv/* && "$FILE_PATH" != *platform/* && "$FILE_PATH" != *docs/* ]]; then
  if [[ "${ENGINE_UNLOCK:-0}" != "1" ]]; then
    echo "BLOCKED: dkmv engine '$FILE_PATH' is locked. Consume via dkmv.runtime; engine changes are PRD §11 asks. Set ENGINE_UNLOCK=1 to override." >&2
    exit 2
  fi
fi
exit 0
