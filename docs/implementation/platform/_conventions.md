# DKMV Platform — Shared Implementation Conventions (internal reference)

> This file is the single source the sub-agent files, phase briefs, and skills draw from so every artifact stays consistent. Project prefix: **`dkmvp`**. It is NOT a phase brief; it is a convention sheet. Source of truth remains the PRD: `docs/design_docs/platform/PRD_dkmv_platform_v1.md`.

## Project shape decisions

- **UI?** Yes (React/Vite dashboard) → DESIGN_FIDELITY checks + design-system skill + no-hardcoded-hex hook are IN.
- **Security surface?** Yes (loopback control plane, host docker socket, autonomous agents on attacker-influenceable input, secrets) → SECURITY_CHECKS are IN (with concrete greps).
- **Solo developer?** Yes → compressed agent usage (implementer + evaluator are the core; researcher + test-runner provided but optional, test execution can be direct Bash); 3-lens polish only for slices >3 files; the human (Tawab) is the merge gate; **serialized PR mode** (one open PR at a time).

## Stack & layout

- New code lives in **`platform/`** (sibling to `dkmv/` inside the DKMV repo).
  - `platform/backend/` — **Python 3.12, FastAPI**, SQLite(WAL)+**Alembic**+aiosqlite, `sse-starlette`, in-process asyncio orchestrator. Consumes the `dkmv` engine **in-process** via `dkmv.runtime.EmbeddedRuntime`. Tests: **pytest**. Lint/type: **ruff** + **mypy**. Package layout: `app/{api,orchestrator,github,executor,db,sse,secrets,security}`.
  - `platform/frontend/` — **React 18 + Vite + TypeScript**; design tokens ported from `docs/design_docs/platform/styles.css`. Tests: **vitest**. Type: `tsc --noEmit`.
- API base path `/api/v1`. Error envelope `{ "error": { "code", "message", "details?" } }`. Cursor pagination `?limit&cursor` → `{ items, next_cursor }`. (PRD §8.9.)

## System invariants (every slice MUST honor; the evaluator greps these)

Each is `INV-n: rule — why (failure mode) — grep/verify`. Backend greps run under `platform/backend/`, frontend under `platform/frontend/src/`.

- **INV-1 App access control.** API binds `127.0.0.1` + requires the local token; validates `Host`/`Origin` (anti-DNS-rebinding); CSRF on state-changing POSTs. *Failure:* a malicious page drives the root-equivalent control plane. *Verify:* middleware present; `grep -rn "127.0.0.1\|Origin\|csrf" platform/backend/app/security/` non-empty; a request with a foreign `Host` returns 403 in tests. (PRD NFR-SEC-2.)
- **INV-2 SSE auth via cookie, token never in URL.** The SSE token rides an HttpOnly `SameSite=Strict` cookie. *Failure:* a token in the query string lands in logs/`events` (permanent leak). *Verify:* `grep -rnE "token=|\\?.*token" platform/frontend/src | grep -i eventsource` is empty; cookie set on connect. (PRD §8.3.)
- **INV-3 Sandbox isolation + egress allowlist.** Runs execute under gVisor (`runsc`, `SANDBOX_RUNTIME`); a network-enforced egress allowlist (GitHub + model APIs, pinned DNS) is default-on. *Failure:* injected prompt exfiltrates creds. *Verify:* executor sets the runtime + allowlist; a test asserts a non-allowlisted host is blocked. (PRD NFR-SEC-1/4, §8.6.)
- **INV-4 Secret hygiene.** GitHub token repo-scoped + ≤1 hr; secrets file-mounted + encrypted at rest; **redact-before-persist** in the event/log pipeline. *Failure:* secret in the append-only `events` table. *Verify:* `grep -rnE "sk-ant-|ghp_|github_pat_|ANTHROPIC_API_KEY" platform/backend/app | grep -iv "redact\|alias\|env\|test"` shows no secret being written to logs/events; redaction function covers those patterns. (PRD §8.6.)
- **INV-5 Dispatch idempotency (SQLite-correct).** Run dispatch = `UNIQUE(idempotency_key)` + `INSERT … ON CONFLICT DO NOTHING` under `BEGIN IMMEDIATE`. *Failure:* webhook+poll double-launch / double spend. *Verify:* `grep -rn "ON CONFLICT\|INSERT OR IGNORE" platform/backend/app/db` present; **`grep -rn "SKIP LOCKED\|FOR UPDATE" platform/backend` MUST be empty** (SQLite has neither). (PRD §8.2, R-5.)
- **INV-6 SQLite concurrency contract.** Connections set `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout>=5000`, `foreign_keys=ON`; all writes go through a **single serialized writer task** using `BEGIN IMMEDIATE`. *Failure:* `database is locked` under concurrent runs. *Verify:* pragma setup present; a 5-writer×4 Hz test yields zero lock errors. (PRD §6.5.)
- **INV-7 Segment-sum cost meter.** Run cost = Σ(final `cost_usd` of completed tasks) + latest within the active task, **deduped by `task_index`**; NEVER naive `SUM(cost_usd)` over events, NEVER keep-latest. `task_completed`/`task_failed` are meter-critical (never coalesced). *Failure:* meter resets at stage boundaries / double-counts. *Verify:* meter module dedups by `task_index`; a multi-stage test shows cost climbing to the run total. (PRD §6.4, §8.3, R-17.)
- **INV-8 Capability-aware cost enforcement.** Branch on `adapter.supports_budget()` / `supports_max_turns()`. Claude → hard budget+turns+timeout. Codex → **timeout-only**; the API **rejects** `max_budget_usd`/`max_turns` for Codex (`400 unsupported_for_agent`); Codex cost renders "—" and is excluded from spend. *Failure:* false hard-cap promise; runaway Codex run. *Verify:* `grep -rn "supports_budget\|supports_max_turns" platform/backend/app` present; a test asserts the 400 for Codex budget. (PRD NFR-COST-1, §7.2, R-10/R-16.)
- **INV-9 HITL correctness.** `POST /runs/{id}/answer` resolves exactly once (`UPDATE pause_decisions SET status='answered' WHERE id=? AND status='pending'`, fire on rowcount=1); pause **releases the concurrency slot**; `timeout_at` is UTC, re-evaluated each reconcile tick; Stop-during-pause uses `RunHandle.stop(force=True)`. Code/UI **never** promise "resumes exactly where it left off." *Failure:* double-resolve / hung idle container / lost slot. *Verify:* rowcount guard present; `grep -rni "resumes exactly\|resume in place" platform` empty. (PRD §8.5, ADR-P007.)
- **INV-10 No live-run re-attach; recovery = kill+interrupt+retry.** Boot recovery kills the orphan container, marks the run `interrupted`, offers `start_task` retry; graceful drain on SIGTERM stops containers. The code MUST NOT attempt to re-attach an observer to a container started by a dead process. *Failure:* orphaned money-spending container. *Verify:* recovery path kills orphans; `grep -rni "reattach\|re-attach" platform/backend` (if present) is only in comments explaining it's unsupported. (PRD §8.2, R-15, ADR-P007.)
- **INV-11 GitHub label state machine.** All `agent:*` transitions go through `set_agent_state()` using GitHub `PUT .../issues/{n}/labels` **replace-all** (single-occupancy invariant); for an active run the **DB row is authoritative** over the label; all mutating GitHub calls go through the **single serialized write-queue** (80/min secondary-limit + `Retry-After`). The fictional `PATCH .../label` MUST NOT appear. *Failure:* two `agent:*` labels / rate-limit storm / echo loop. *Verify:* `grep -rn "PUT.*labels\|set_agent_state" platform/backend/app/github` present; `grep -rni "PATCH.*/label" platform` empty. (PRD §8.1, ADR-P004.)
- **INV-12 Sync→async observer bridge.** The engine's sync `EventObserver.on_event` pushes via `loop.call_soon_threadsafe(queue.put_nowait, event)`. NEVER bare `put_nowait`, `loop.create_task`, or per-event `run_coroutine_threadsafe` from the observer. *Failure:* event-loop heisenbug / dropped events. *Verify:* `grep -rn "call_soon_threadsafe" platform/backend/app/sse` present; observer does not call `create_task`/`run_coroutine_threadsafe`. (PRD §8.3.)
- **INV-13 Consume engine in-process; engine is locked.** The backend calls `dkmv.runtime.EmbeddedRuntime` directly; it **never shells the `dkmv` CLI** and **never modifies `dkmv/`** (engine changes are out of scope — tracked as PRD §11 engine asks). *Failure:* CLI-scraping brittleness / out-of-scope engine edits. *Verify:* `grep -rn "subprocess.*dkmv\|os.system.*dkmv" platform/backend` empty; no diff under `dkmv/`. (PRD §6.2, N6, ADR-P006; enforced by `lock-engine.sh`.)
- **INV-14 Design tokens only + a11y.** Frontend uses design tokens (no hardcoded hex outside the tokens file); state is conveyed by icon+label, not color alone; AA contrast. *Failure:* design drift / inaccessible state. *Verify:* `grep -rnE "#[0-9a-fA-F]{3,8}\b" platform/frontend/src --include=*.tsx --include=*.ts` outside the tokens file is empty; state components render an icon+label. (PRD §7, NFR-A11Y-1.)
- **INV-15 PRD is the source of truth.** No drift. Ambiguity → conservative choice + `open_questions`. The PRD, design prototype, ADRs, and phase briefs are **locked** during implementation (enforced by hooks).

## Locked / DO-NOT-EDIT (hook-enforced)

- `docs/design_docs/platform/PRD_dkmv_platform_v1.md` and `docs/implementation/platform/phase_*.md`, `docs/implementation/platform/adrs/*` → `lock-prd.sh` (override `PRD_UNLOCK=1`).
- `docs/design_docs/platform/*` (the prototype + styles.css) → `lock-design.sh` (override `DESIGN_UNLOCK=1`).
- `dkmv/**` (the engine) → `lock-engine.sh` (override `ENGINE_UNLOCK=1`). Consume only.

## Independent verification commands (the evaluator runs these)

- Backend: `cd platform/backend && ruff check . && mypy app && pytest -q` (exit 0).
- Frontend: `cd platform/frontend && npx tsc --noEmit && npx vitest run` (exit 0).
- No-hardcoded-hex: `bash scripts/hooks/post-edit-no-hardcoded-hex.sh` style grep over `platform/frontend/src` (empty).
- SQLite-lock guard: `grep -rn "SKIP LOCKED\|FOR UPDATE" platform/backend` (empty).
- Engine untouched: `git diff --name-only main..<branch> -- dkmv/` (empty).
- Secret-in-events guard: `grep -rnE "sk-ant-|ghp_|github_pat_" platform/backend/app | grep -i "event\|log"` (empty / only redaction).

## Phase brief expectations (every brief)

Greppable acceptance criteria with PRD §citations; explicit OUT-of-scope; a SECURITY_CHECKS section (concrete greps from the INVs above, those that apply); a DESIGN_FIDELITY section for UI slices; an "Independent verification commands" bash block; a Wave plan (no two same-wave slices edit the same file). Slice IDs `N.k-name`. Map slices to the feature IDs in `features.md` and PRD sections.
