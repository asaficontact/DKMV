"""PRD §13 end-to-end acceptance suite (slice 5.4 — AC-15/16/17, the v1 ship gate).

This package maps the **full** PRD §13 acceptance matrix — one module per AT —
against the real FastAPI app + the real platform components + fakes (no live
Docker / engine for the in-process ATs). The matrix:

    AT-Connect        GitHub PAT intake + permission contract + secret hygiene
    AT-Board          board aggregate / state derivation + Codex-excluded spend
    AT-Launch         POST /runs claim-lock + capability validation + label move
    AT-Live           segment-sum cost climbs to run total (no reset); SSE replay
                      no-gaps-no-dups; no token in the SSE URL (cookie auth)
    AT-HITL           resolve-exactly-once + concurrency-slot release on pause
    AT-Recovery       kill-orphan + interrupted + start_task; no dup PR; no orphan
    AT-History        Codex-excluded spend in the history/board projections
    AT-Workflows      the read-only workflows viewer surfaces the built-ins
    AT-Concurrency    only N at once + admission deny/requeue over memory/spend
    AT-Isolation      gVisor runsc + egress allowlist deny + repo-scoped token +
                      secret-free events/logs/audit (Docker-gated parts self-skip)
    AT-PromptInjection the NFR-SEC-5 PR-push gate fires on an injected issue body
    AT-CodexCost      "—" not "$0.00", excluded from spend, tokens still counted

**HONEST live-vs-skipped split (the brief's environment note).** The in-process
ATs run for REAL. The ATs that need a LIVE gVisor container + real network egress
(a real sandboxed run, a real egress-deny over the wire) assert the *configuration*
+ the *Python-level enforcement* in-process, and GATE the live-container assertions
behind a Docker/runsc-availability ``skipif`` (see :mod:`tests.e2e.gating`) that
self-skips — clearly reported as skipped, never faked, never silently passed.
"""
