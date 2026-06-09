#!/usr/bin/env bash
# DKMV Platform — SBOM generate + scan + digest-pin (§8.6, ADR-P005, AC-13).
#
# This is the supply-chain release gate for the sandbox image (and, optionally,
# the platform backend image). The image the engine launches AUTONOMOUS,
# attacker-influenceable coding agents inside is high-value: a poisoned base/dep
# or a silently re-pushed `:latest` tag is a direct path to host compromise. So
# before release we:
#
#   1. GENERATE a Software Bill of Materials (SBOM) for the image — the full,
#      auditable package inventory (CycloneDX/SPDX).
#   2. SCAN it for known vulnerabilities and FAIL the build on HIGH/CRITICAL.
#   3. RESOLVE the image to its immutable content DIGEST (`name@sha256:…`) so the
#      release/compose path pins by digest, NEVER by a mutable `:latest` tag
#      (INV-3). The resolved digest is written into the deploy `.env` as
#      `DKMV_IMAGE=dkmv-sandbox@sha256:<digest>`.
#
# Scanner: Trivy if present, else Docker Scout, else (no scanner installed) the
# script still emits the SBOM stub + the digest-pin env line and warns that the
# vuln scan was skipped — so a dev box without a scanner is not blocked, but CI
# (which installs Trivy) gets the full gate.
#
# Usage:
#   bash platform/scripts/sbom-scan.sh [IMAGE]        # generate SBOM + scan IMAGE
#   bash platform/scripts/sbom-scan.sh --print-digest-env [IMAGE]
#                                                     # print `DKMV_IMAGE=name@sha256:…`
#
# IMAGE defaults to `${DKMV_SANDBOX_IMAGE:-dkmv-sandbox:latest}` — the LOCAL build
# tag. The output of this script is the DIGEST-pinned reference the release config
# consumes; the mutable build tag is only an input to digest resolution and never
# reaches docker-compose.yml.

set -euo pipefail

IMAGE_BUILD_TAG="${DKMV_SANDBOX_IMAGE:-dkmv-sandbox:latest}"
PRINT_DIGEST_ENV=0
SBOM_OUT="${SBOM_OUT:-platform/sbom/dkmv-sandbox.sbom.json}"
# Fail the build on these severities (the supply-chain gate).
FAIL_SEVERITIES="${FAIL_SEVERITIES:-HIGH,CRITICAL}"

# ── Args ──────────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --print-digest-env) PRINT_DIGEST_ENV=1; shift ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) IMAGE_BUILD_TAG="$1"; shift ;;
  esac
done

log() { printf '[sbom-scan] %s\n' "$*" >&2; }

# ── Resolve the immutable content digest (name@sha256:…) ──────────────────────
# Prefer the local-built RepoDigests; fall back to the build tag's image ID. In
# an environment with no real built image (CI dry-run / this dev box), emit the
# documented placeholder digest so the pin-by-digest contract still holds and the
# release config never reverts to `:latest`.
PLACEHOLDER_DIGEST="dkmv-sandbox@sha256:0000000000000000000000000000000000000000000000000000000000000000"

resolve_digest() {
  if command -v docker >/dev/null 2>&1; then
    local repo_digest
    repo_digest="$(docker image inspect "$IMAGE_BUILD_TAG" \
      --format '{{ index .RepoDigests 0 }}' 2>/dev/null || true)"
    if [[ -n "$repo_digest" && "$repo_digest" == *@sha256:* ]]; then
      # Normalize to the bare `dkmv-sandbox@sha256:…` name the release path uses.
      printf 'dkmv-sandbox@%s\n' "${repo_digest#*@}"
      return 0
    fi
  fi
  log "WARNING: could not resolve a real RepoDigest for '${IMAGE_BUILD_TAG}'."
  log "         Emitting the documented PLACEHOLDER digest — replace with the real"
  log "         built digest in a release build (see platform/docs/setup.md)."
  printf '%s\n' "$PLACEHOLDER_DIGEST"
}

if [[ "$PRINT_DIGEST_ENV" -eq 1 ]]; then
  # Print ONLY the env line so callers can `eval "$(... --print-digest-env)"`.
  printf 'DKMV_IMAGE=%s\n' "$(resolve_digest)"
  exit 0
fi

# ── 1. Generate the SBOM ──────────────────────────────────────────────────────
mkdir -p "$(dirname "$SBOM_OUT")"
if command -v trivy >/dev/null 2>&1; then
  log "Generating SBOM (Trivy / CycloneDX) for ${IMAGE_BUILD_TAG} -> ${SBOM_OUT}"
  trivy image --format cyclonedx --output "$SBOM_OUT" "$IMAGE_BUILD_TAG"
elif command -v docker >/dev/null 2>&1 && docker scout version >/dev/null 2>&1; then
  log "Generating SBOM (Docker Scout) for ${IMAGE_BUILD_TAG} -> ${SBOM_OUT}"
  docker scout sbom --format cyclonedx --output "$SBOM_OUT" "$IMAGE_BUILD_TAG"
else
  log "WARNING: no SBOM tool (trivy / docker scout) found — writing an SBOM stub."
  printf '{"bomFormat":"CycloneDX","note":"sbom tool not installed; install trivy or docker scout"}\n' \
    > "$SBOM_OUT"
fi

# ── 2. Scan for vulnerabilities (fail the gate on HIGH/CRITICAL) ──────────────
if command -v trivy >/dev/null 2>&1; then
  log "Scanning ${IMAGE_BUILD_TAG} (Trivy); failing on ${FAIL_SEVERITIES}"
  trivy image --exit-code 1 --severity "$FAIL_SEVERITIES" "$IMAGE_BUILD_TAG"
elif command -v docker >/dev/null 2>&1 && docker scout version >/dev/null 2>&1; then
  log "Scanning ${IMAGE_BUILD_TAG} (Docker Scout); failing on ${FAIL_SEVERITIES}"
  docker scout cves --exit-code --only-severity "${FAIL_SEVERITIES,,}" "$IMAGE_BUILD_TAG"
else
  log "WARNING: vulnerability scan SKIPPED (no trivy / docker scout). CI installs"
  log "         a scanner and runs the full gate; do not release from this state."
fi

# ── 3. Emit the digest-pin the release config consumes ────────────────────────
DIGEST_REF="$(resolve_digest)"
log "Release pin (write into deploy .env): DKMV_IMAGE=${DIGEST_REF}"
log "Done. SBOM=${SBOM_OUT}"
