#!/usr/bin/env bash
# Blocks destructive / production commands. Override: PROD_OK=1
set -euo pipefail
INPUT="$(cat)"
CMD="$(jq -r '.tool_input.command // ""' <<< "$INPUT")"
DANGEROUS_PATTERNS=(
  'rm -rf'
  'git push --force'
  'git push -f'
  'docker system prune'
  'docker volume prune'
  'DROP TABLE'
  'fly deploy'
  'vercel --prod'
)
shopt -s nocasematch
for pattern in "${DANGEROUS_PATTERNS[@]}"; do
  if [[ "$CMD" == *"$pattern"* ]]; then
    if [[ "${PROD_OK:-0}" != "1" ]]; then
      echo "BLOCKED: dangerous command pattern '$pattern'. Set PROD_OK=1 to override." >&2
      exit 2
    fi
  fi
done
exit 0
