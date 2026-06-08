#!/usr/bin/env bash
# Blocks edits to the locked PRD, phase briefs, and ADRs. Override: PRD_UNLOCK=1
set -euo pipefail
INPUT="$(cat)"
FILE_PATH="$(jq -r '.tool_input.file_path // ""' <<< "$INPUT")"
case "$FILE_PATH" in
  *docs/design_docs/platform/PRD_*.md|*docs/implementation/platform/phase_*.md|*docs/implementation/platform/adrs/*)
    if [[ "${PRD_UNLOCK:-0}" != "1" ]]; then
      echo "BLOCKED: '$FILE_PATH' is locked (PRD / phase brief / ADR). Set PRD_UNLOCK=1 to override." >&2
      exit 2
    fi ;;
esac
exit 0
