#!/usr/bin/env bash
# Tests for the DKMV sandbox Docker image.
# Usage: bash tests/docker/test_image.sh [image-name]
set -euo pipefail

IMAGE="${1:-dkmv-sandbox:latest}"
PASS=0
FAIL=0

run_test() {
    local desc="$1"
    shift
    if "$@"; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        FAIL=$((FAIL + 1))
    fi
}

echo "Testing image: $IMAGE"
echo "---"

# Helper to run commands inside the container
drun() {
    docker run --rm "$IMAGE" "$@"
}

# T025: Image structure assertions

# Non-root user dkmv at UID 1000
run_test "non-root user dkmv exists" \
    [ "$(drun id -un)" = "dkmv" ]

run_test "user dkmv has UID 1000" \
    [ "$(drun id -u)" = "1000" ]

# Required tools available
run_test "claude is available" \
    drun which claude

run_test "gh is available" \
    drun which gh

run_test "git is available" \
    drun which git

run_test "python3 is available" \
    drun which python3

# SWE-ReX
run_test "swerex-remote is available" \
    drun which swerex-remote

# Environment variables
run_test "IS_SANDBOX=1" \
    [ "$(drun printenv IS_SANDBOX)" = "1" ]

run_test "NODE_OPTIONS is set" \
    drun printenv NODE_OPTIONS

# Working directory
run_test "working directory is /home/dkmv/project" \
    [ "$(drun pwd)" = "/home/dkmv/project" ]

echo "---"
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
