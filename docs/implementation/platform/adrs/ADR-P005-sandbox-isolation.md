# ADR-P005: gVisor runtime + egress allowlist + brokered socket

## Status

Accepted

## Context

The platform runs autonomous agents on **attacker-influenceable input** (an issue body *is* the prompt, repo content *is* the context) while holding a live GitHub token + model keys + network egress, on a host whose Docker socket it must reach to launch containers. Plain `runc` shares the host kernel and "is not a security boundary" for untrusted agent code; a raw docker-socket mount is root-equivalent.

## Decision

Defense-in-depth, default-on:
1. **gVisor (`runsc`)** as the default sandbox runtime (microVM for the cloud/multi-tenant path); a documented weaker-isolation opt-in + warning if `runsc` is unavailable (OQ-6).
2. **Network-enforced egress allowlist** (GitHub + model APIs only, pinned DNS) — a *requirement*, not a recommendation; the primary exfiltration control.
3. **Repo-scoped, ≤1 hr GitHub token**; secrets encrypted at rest, file-mount-injected, redacted-before-persist.
4. **Brokered Docker socket** (method-allowlisted proxy / rootless / Sysbox), never a raw mount.
5. **App access control:** bind `127.0.0.1` + local auth token + `Host`/`Origin` validation (anti-DNS-rebinding) + CSRF on POSTs.
6. Sandbox image **digest-pinned + SBOM-scanned**; a platform-injected human-approval gate on the irreversible PR push (NFR-SEC-5).

## Consequences

- + Minimum-responsible posture for untrusted-code execution; injected creds are hard to exfiltrate.
- − gVisor adds ~10–30% I/O overhead (irrelevant at ≤3 concurrent runs); some Docker Desktop hosts lack `runsc` (OQ-6 fallback).
- Implication: isolation is a runtime flag + network/proxy config, not a rewrite; multi-tenant later mandates microVM + per-tenant secret isolation.

## PRD Reference

§8.6, §8.8, NFR-SEC-1..5, R-3/R-13/R-14, OQ-6.
