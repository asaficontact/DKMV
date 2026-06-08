# DKMV Platform v1 — Orchestrator Operating Manual

This is the orchestrator's quick manual. The orchestrator reads this + `orchestration.md` + `evaluation_protocol.md` + the current phase brief. It does **not** read the whole PRD (context is sacred — sub-agents read cited sections).

## What we're building

A self-hostable web control plane in `platform/` that turns GitHub Issues into autonomous DKMV coding-agent runs. It wraps the existing **locked** DKMV engine (`dkmv/`) via `dkmv.runtime.EmbeddedRuntime` — consume only, never edit.

- **PRD (source of truth, LOCKED):** `docs/design_docs/platform/PRD_dkmv_platform_v1.md` (v1.1)
- **Design prototype (LOCKED):** `docs/design_docs/platform/` (JSX + `styles.css` + PDF)
- **Plan dir:** `docs/implementation/platform/`
- **ADRs (locked decisions / system invariants):** `docs/implementation/platform/adrs/`
- **System invariants the evaluator greps:** `docs/implementation/platform/_conventions.md` (INV-1..15)

## Document map

- `README.md` — overview + file inventory.
- `orchestration.md` — sub-agent topology, skills, hooks, MCP, worktree hygiene, orchestrator read-list.
- `evaluation_protocol.md` — the build→evaluate→fix→polish→PR loop, escalation triggers, VERDICT/PR formats, resume.
- `claude-code-research.md` — verified Claude Code feature reality (use this, not assumptions).
- `phase_0_foundation.md … phase_5_scale_ship.md` — the six phase briefs. Read only the current one.
- `_conventions.md` — stack + invariants + locked files + verification commands.
- `phase_progress.log` — session log (auto-appended).
- `features.md` / `user_stories.md` / `tasks.md` — traceability appendix (slices map to F/US/T IDs).

## Relevant ADRs (one-liners)

- **P001** in-process FastAPI + asyncio orchestrator (no Celery/Temporal; DBOS is the later escalation).
- **P002** SQLite (WAL, single-writer, event log) → Postgres later; idempotency = UNIQUE key, not SKIP LOCKED.
- **P003** SSE streaming; sync→async via `call_soon_threadsafe`; HttpOnly-cookie auth; segment-sum meters.
- **P004** fine-grained PAT + poll-only + `agent:*` labels (App/webhooks deferred); `set_agent_state` PUT replace-all.
- **P005** gVisor runtime + default-on egress allowlist + brokered docker socket + loopback/token/Host/CSRF.
- **P006** consume `EmbeddedRuntime` in-process; platform owns the DB index + UUID PK; engine is locked.
- **P007** best-effort-durable HITL (no live-run re-attach; resume from pushed boundary; recovery = kill+interrupt).
- **P008** `Executor` interface (LocalDocker now, remote later).
- **P009** capability-aware cost (Codex = timeout-only; reject budget/turns 400).
- **P010** Workflows screen read-only in v1 (authoring → v1.1).

## Implementation process (per phase)

1. **Read** the phase brief (Prerequisites, Scope, Slices, Wave plan, Acceptance criteria, SECURITY/DESIGN checks, Independent verification).
2. **For each wave:** create worktrees via Bash → dispatch `dkmvp-implementer` per slice in parallel → collect JSON → one retry on test failure → dispatch `dkmvp-evaluator` (brief + branch only) → resolve verdicts (≤3 fix loops; CRITICAL → escalate) → 3-lens polish (slices >3 files).
3. **PR** per slice, serialized (one open at a time); structured body (`evaluation_protocol.md`).
4. **Wait** for Tawab to merge (never auto-merge); read the next brief while waiting.
5. **Cleanup** worktrees + branches; append `PHASE-N-COMPLETE`; advance.

## Quality gates (every slice, before APPROVED)

- Backend: `cd platform/backend && ruff check . && mypy app && pytest -q` (exit 0).
- Frontend: `cd platform/frontend && npx tsc --noEmit && npx vitest run` (exit 0).
- INV greps clean (no `SKIP LOCKED`/`FOR UPDATE`; no `PATCH .../label`; no token in URL; no `dkmv/` diff; no hardcoded hex in `platform/frontend/src`).

## Conventions

- Conventional commits, scope = subsystem (`api`, `db`, `github`, `sse`, `orchestrator`, `executor`, `secrets`, `ui`).
- Branch per slice: `phase-N-impl-<slice>`. Worktrees under `.claude/worktrees/` (gitignored).
- Solo mode: implementer + evaluator core; serialized PRs; Tawab is the merge gate; 3-lens polish only for slices >3 files.

## DO NOT CHANGE (hook-enforced)

- `dkmv/**` — the engine. Consume via `dkmv.runtime`; gaps are PRD §11 asks (`lock-engine.sh`).
- `docs/design_docs/platform/PRD_dkmv_platform_v1.md`, `docs/implementation/platform/phase_*.md`, `adrs/*` (`lock-prd.sh`).
- `docs/design_docs/platform/*` — the prototype + tokens; port tokens, don't edit (`lock-design.sh`).
- The orchestrator never writes production code, never edits its own agent files, never auto-merges.

---
*Operating manual v1.0 — PRD v1.1.*
