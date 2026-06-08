#!/usr/bin/env bash
# Stop: append a session-end marker to the phase progress log (with missing-file fallback).
set -euo pipefail
LOG="docs/implementation/platform/phase_progress.log"
mkdir -p "$(dirname "$LOG")"
[[ -f "$LOG" ]] || echo "# DKMV Platform — phase progress log (auto-appended)" > "$LOG"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) session_end" >> "$LOG"
exit 0
