#!/usr/bin/env bash
# SubagentStop: run a fast backend smoke/contract test if present. Non-blocking on absence.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
if [[ -d "$ROOT/platform/backend/tests/contract" ]]; then
  ( cd "$ROOT/platform/backend" && pytest -q tests/contract ) 2>&1 | tail -20 \
    || { echo "CONTRACT TESTS FAILED — see above." >&2; exit 2; }
fi
exit 0
