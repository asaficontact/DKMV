# Phase 0 — Foundation (Skeleton, Persistence, Sandbox)

**PRD version:** v1.1
**PRD milestone:** M0 — Skeleton & engine bridge (PRD §12).
**Features:** F1 Platform Skeleton & Engine Bridge · F2 Persistence & Event Log · F3 Sandbox Security & Execution (`features.md`).
**User stories:** US-01, US-02, US-03, US-04, US-23.
**Tasks:** T010–T032 (`tasks.md`).
**Timing:** Weeks 1–3.
**Depends on:** none (first product phase).
**Blocks:** Phase 1 (F4 GitHub needs F1/F2/F3), Phase 2 (F7 Run Launch needs F1/F2/F3).
**ADRs:** ADR-P001 (in-process orchestrator), ADR-P002 (SQLite event log), ADR-P005 (sandbox isolation), ADR-P006 (embedded engine), ADR-P008 (Executor seam).
**Conventions:** `docs/implementation/platform/_conventions.md` (stack, INV-1..15, locked files, verification commands). Project prefix `dkmvp`.

> **Goal of this phase (product framing).** Stand up the `platform/` repo so a run can be launched via the API against a local repo, streamed into a durable event log, and executed inside a hardened sandbox — *without any UI beyond the frontend scaffold and without GitHub*. Exit bar (PRD §12 M0): "launch a run via API against a local repo, see it complete, artifacts + `run_totals` indexed." This is the load-bearing foundation every later phase builds on; correctness of the SQLite concurrency contract, the in-process engine bridge, and the sandbox security baseline matter more here than feature breadth.

---

## Phase 0a — methodology pre-flight (human, NOT orchestrator-run)

This sub-section is a **human pre-flight checklist**, performed by Tawab *before* the orchestrator dispatches any product slice below. It is **not** an orchestrator-run slice and has no T-ID. The orchestrator's Phase 0 work begins at slice `0.1-scaffold`.

During pre-flight the human installs the methodology scaffolding that the orchestrator and its sub-agents depend on. These artifacts are **staged** in the repo under `docs/implementation/platform/{agents,skills,hooks}/` and **copied into place** per the steps in `CLAUDE_CODE_PROMPT.md`:

- **Sub-agent files** → `.claude/agents/dkmvp-*.md` (implementer, evaluator, and the optional researcher / test-runner — solo-dev compressed usage per `_conventions.md`).
- **Skills** (e.g. the design-system skill referenced for later UI phases) → the Claude Code skills location.
- **Hook scripts** → `scripts/hooks/` and registered in **`.claude/settings.json`**: `lock-prd.sh`, `lock-design.sh`, `lock-engine.sh` (the DO-NOT-EDIT guards), and `post-edit-no-hardcoded-hex.sh`.
- **`.gitignore`** entry for `.claude/worktrees/` (serialized-PR worktree mode).
- **MCP servers** the agents use are configured.

**Pre-flight exit check (human):** `.claude/agents/dkmvp-*.md` exist; `.claude/settings.json` registers all eight hook scripts (lock-prd / lock-design / lock-engine, forbid-dangerous, post-edit-typecheck, post-edit-no-hardcoded-hex, contract-test, update-phase-progress); `git check-ignore .claude/worktrees/x` returns a match; the lock hooks reject a write to `dkmv/`, the PRD, and the design prototype unless the documented override env var is set. Only once these pass does the orchestrator start `0.1-scaffold`.

> Everything from `0.1-scaffold` onward is orchestrator-run product work. The pre-flight above is documented here for traceability only; it is **out of scope for every slice's acceptance criteria**.

---

## Slices

| Slice | What | PRD § | Feature |
|---|---|---|---|
| `0.1-scaffold` | `platform/` repo scaffold (`backend/`, `frontend/`, `docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.frontend`, `pyproject.toml`, `alembic/`); `dkmv` editable install (Python ≥ 3.12); documented `docker build -t dkmv-sandbox:latest dkmv/images/`; consolidated config/env surface (§8.8 env table) loaded via a typed settings object. | §8.8 | F1 |
| `0.2-runservice` | `RunService` over `EmbeddedRuntime` (constructed from `RuntimeConfig`, platform-owned `output_dir`); `GET /api/v1/preflight` via `get_capabilities()`; app access-control middleware (`127.0.0.1` bind + local token + `Host`/`Origin` validation + CSRF); API error-envelope / status-code conventions (§8.9). | §6.2, §8.8, §8.9 | F1 |
| `0.3-persistence` | SQLite connection mgmt (WAL / `synchronous=NORMAL` / `busy_timeout≥5000` / `foreign_keys=ON` + single serialized writer task); Alembic initial migration (all tables `projects/issues/runs/run_stages/events/pause_decisions/run_totals/settings/secrets` + indexes + FK `ON DELETE CASCADE`); repository layer; append-only event log (monotonic `events.id`); `run_totals` snapshot + `VACUUM INTO` backup; `spend` projection (last-cumulative per `(run_id, task_index)`, Codex excluded); idempotency-key claim-insert helper. | §6.5, §6.4, §8.2 | F2 |
| `0.4-executor` | `Executor` interface + `LocalDockerExecutor` (wraps `RunService`/`EmbeddedRuntime` + local Docker); gVisor `runsc` default runtime + documented weaker-isolation opt-in/warning (OQ-6); brokered Docker socket (method-allowlisted proxy / rootless / Sysbox), never a raw mount. | §8.7, §8.8 | F3 |
| `0.5-secrets-egress` | Network-enforced egress allowlist (GitHub + model APIs only, pinned DNS); encrypted `SecretStore` + file-mount injection + repo-scoped ≤1 hr GitHub token; redact-before-persist in the event/log pipeline; security baseline tests. | §8.6, NFR-SEC-1..5 | F3 |

Slice → task map: `0.1`→T010–T013 · `0.2`→T014–T017 · `0.3`→T018–T025 · `0.4`→T026–T028 · `0.5`→T029–T032.

---

## Wave plan

Serialized-PR mode (one open PR at a time, human is the merge gate). The waves below express **dependency order**; within a wave no two slices edit the same file.

| Wave | Slice(s) | Rationale | Primary files touched (disjoint within wave) |
|---|---|---|---|
| **W1** | `0.1-scaffold` | Everything depends on the repo skeleton + settings object existing. | `platform/` tree, `pyproject.toml`, `compose`, `Dockerfile.*`, `backend/app/config.py` |
| **W2** | `0.2-runservice` ∥ `0.3-persistence` | Independent: `0.2` builds `app/{api,security,executor-stub,runtime}`; `0.3` builds `app/db`. No shared file. | `0.2`→ `app/api/`, `app/security/`, `app/runtime/run_service.py`; `0.3`→ `app/db/` + `alembic/` |
| **W3** | `0.4-executor` | Needs the `RunService` from `0.2` to wrap. | `app/executor/` |
| **W4** | `0.5-secrets-egress` | Needs `0.4` (executor injects egress/runtime flags) **and** `0.3` (`secrets` table + redact-before-persist into `events`). | `app/secrets/`, egress config in `app/executor/`, redaction in `app/db/`-`app/sse`-adjacent pipeline |

Conflict check: `0.2` touches `app/security/` (access-control middleware, INV-1); `0.5` also touches `app/security`-adjacent secret handling — but `0.5` is **W4**, a different wave, so no same-wave file collision. `0.4` and `0.5` both touch `app/executor/` egress wiring but are in different waves (W3 then W4).

---

## IN scope (with PRD citations)

- **F1 — repo + bridge.**
  - `platform/` scaffold with `backend/` (FastAPI), `frontend/` (Vite skeleton only), `docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.frontend`, `pyproject.toml`, `alembic/` (PRD §8.8).
  - Editable install of the engine (`pip install -e ../dkmv`), Python ≥ 3.12 pin; documented `docker build -t dkmv-sandbox:latest dkmv/images/` step in the README (PRD §8.8, US-01).
  - Consolidated config/env surface loaded via a typed settings object: `DKMV_PLATFORM_TOKEN`, `DKMV_PLATFORM_BIND` (default `127.0.0.1:8787`), `DATABASE_URL`, `OUTPUT_DIR`, `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, `CODEX_API_KEY`, `DKMV_IMAGE`, `MAX_CONCURRENT_RUNS`, `HOST_MEMORY_BUDGET`, `DAILY_SPEND_CAP`, `TICK_INTERVAL_S`, `STALL_TIMEOUT_S`, `PAUSE_TIMEOUT_S`, `SANDBOX_RUNTIME` (default `runsc`), `EGRESS_ALLOWLIST` (PRD §8.8 env table).
  - `RunService` thin wrapper over `EmbeddedRuntime` constructed from `RuntimeConfig` with a **platform-owned `output_dir`** (PRD §6.2, §6.5 OQ-4; ADR-P006).
  - `GET /api/v1/preflight` returning `get_capabilities()` results (PRD §8.9, FR-01-6).
  - App access-control middleware: `127.0.0.1` bind + local token + `Host`/`Origin` validation + CSRF on state-changing POSTs (PRD §8.8, NFR-SEC-2; INV-1).
  - API error-envelope `{ "error": { "code", "message", "details?" } }` + status-code conventions; cursor-pagination shape registered for later list endpoints (PRD §8.9).
- **F2 — persistence + event log.**
  - SQLite connection management with the **binding concurrency contract**: `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout≥5000`, `foreign_keys=ON` per connection; all writes through a **single serialized writer task** using `BEGIN IMMEDIATE` (PRD §6.5; ADR-P002; INV-6).
  - Alembic initial migration creating all nine tables (`projects, issues, runs, run_stages, events, pause_decisions, run_totals, settings, secrets`) with the binding indexes (`UNIQUE(events.run_id, sequence)`, `events(run_id, id)`, `runs(status, started_at)`, `runs(issue_num)`, `pause_decisions(status, timeout_at)`) and FK `ON DELETE CASCADE` on child tables → `runs(id)` (PRD §6.5).
  - `runs.id` = platform **UUID** PK; `engine_run_id` a separate non-unique column; `idempotency_key` **UNIQUE** (PRD §6.5; R-8; ADR-P002).
  - Repository layer — all DB access behind it (SQLite→Postgres seam, NFR-PORT-1).
  - Append-only `events` log with a monotonic `id` (the SSE replay cursor) + batched append API (PRD §6.4, §6.5).
  - `run_totals` snapshot at completion + a `VACUUM INTO` backup command (PRD §6.5).
  - `spend` as a **materialized projection** — last-cumulative `cost_usd` per `(run_id, task_index)`, summed per run, **Codex excluded** — never `SUM` over events (PRD §6.5, FR-06-1a; **INV-7 persistence prep**).
  - Idempotency-key claim-insert helper: `INSERT … ON CONFLICT(idempotency_key) DO NOTHING` under `BEGIN IMMEDIATE`; act only on the won row (PRD §8.2; ADR-P002; INV-5).
- **F3 — sandbox security baseline.**
  - `Executor` interface (`start/stream/signal/cleanup`, `stream()` re-attachable by `run_id` per the seam contract) + `LocalDockerExecutor` wrapping `RunService`/`EmbeddedRuntime` + local Docker (PRD §8.7; ADR-P008).
  - gVisor `runsc` default runtime via `SANDBOX_RUNTIME`; documented weaker-isolation opt-in + explicit warning when `runsc` is unavailable (PRD §8.8, NFR-SEC-4, OQ-6; ADR-P005; INV-3).
  - Brokered Docker socket — method-allowlisted proxy / rootless / Sysbox — never a raw `-v /var/run/docker.sock` mount (PRD §8.8; ADR-P005).
  - Default-on **network-enforced** egress allowlist (GitHub + model APIs only, pinned DNS) (PRD §8.6, NFR-SEC-1; INV-3).
  - Encrypted `SecretStore` + file-mount injection + repo-scoped ≤1 hr GitHub token (PRD §8.6, NFR-SEC-1; INV-4).
  - Redact-before-persist in the event/log pipeline for `sk-ant-…`, `ghp_…`, `github_pat_…`, `ANTHROPIC_API_KEY` (PRD §8.6; INV-4).
  - Security baseline tests: egress denial, no-secret-in-`events`, Host/Origin/CSRF rejection, token-scope (PRD §13 security profile; US-04, US-23).

---

## OUT of scope (deferred — do not build in Phase 0)

- **GitHub integration, Connect, Board, all chrome/UI screens → Phase 1** (F4/F5/F6). No `GitHubClient`, no `set_agent_state`, no issue import, no board, no design-token-driven screens. The frontend is a **scaffold only** (Vite boots, router stub) — no Screens 01–07.
- **Run launch endpoint, SSE streaming, live-run UI, segment-sum *meter*, HITL → Phase 2** (F7/F8/F9). Phase 0 builds the *persistence and security substrate* a run needs, plus a `RunService`/`Executor` that can drive `EmbeddedRuntime`; it does **not** ship `POST /runs`, the SSE endpoint, the observer→queue pump, or the live meter. (Phase 0's `spend` projection and event-log schema are the persistence-side prerequisites for the Phase 2 meter — INV-7 proper lands in F8.)
- **Orchestrator tick / dispatch / retry / reconcile / recovery / governance → Phases 3 & 5** (F11/F13). No `asyncio.Semaphore` dispatch loop, no boot crash-recovery, no concurrency caps in Phase 0.
- **Post-v1 (PRD N8):** full OpenTelemetry GenAI tracing, Redis fan-out, the Postgres repository implementation, the GitHub App + webhooks. Keep the structured-log schema OTel-compatible and all DB access behind the repository layer (additive later), but **do not** implement these now.
- **Workflow authoring builder (N7):** out of v1 entirely; the read-only viewer is Phase 4.
- **`SSHRemoteDockerExecutor` / `K8sJobExecutor` (PRD N2, ADR-P008):** YAGNI — ship `LocalDockerExecutor` only; the *interface* anticipates remote, the *implementation* does not.
- **Any change to `dkmv/` (the engine).** Engine asks (PRD §11) are tracked, not implemented (INV-13; `lock-engine.sh`).

---

## Acceptance criteria (greppable / testable)

Each item cites a PRD § and gives a concrete verify command or grep. Backend greps run under `platform/backend/`. All must pass before the phase is done.

### 0.1-scaffold (F1; PRD §8.8; US-01)

- **AC-0.1-1** Repo tree exists. *Verify:* `test -d platform/backend/app && test -d platform/frontend && test -f platform/docker-compose.yml && test -f platform/Dockerfile.backend && test -f platform/Dockerfile.frontend && test -f platform/pyproject.toml && test -d platform/alembic` (exit 0). (PRD §8.8)
- **AC-0.1-2** Engine is editable-installed and importable in-process (not shelled). *Verify:* `cd platform/backend && python -c "import dkmv.runtime; from dkmv.runtime import EmbeddedRuntime"` (exit 0); `python -c "import sys; assert sys.version_info[:2] >= (3,12)"`. (PRD §8.8, §6.2; INV-13)
- **AC-0.1-3** Sandbox-image build step is documented. *Verify:* `grep -n "docker build -t dkmv-sandbox:latest dkmv/images/" platform/README.md` non-empty. (PRD §8.8)
- **AC-0.1-4** Typed settings object exposes the full §8.8 env surface. *Verify:* `grep -rnE "DKMV_PLATFORM_TOKEN|DKMV_PLATFORM_BIND|OUTPUT_DIR|SANDBOX_RUNTIME|EGRESS_ALLOWLIST|MAX_CONCURRENT_RUNS|DAILY_SPEND_CAP" platform/backend/app/config.py` covers every key; default bind is `127.0.0.1:8787` and default `SANDBOX_RUNTIME` is `runsc`. (PRD §8.8)
- **AC-0.1-5** `docker compose up` boots backend + frontend and the API answers on loopback. *Verify (smoke):* `cd platform && docker compose up -d && curl -fsS -H "Authorization: Bearer $DKMV_PLATFORM_TOKEN" http://127.0.0.1:8787/api/v1/preflight` returns 200. (PRD §8.8, §12 M0)

### 0.2-runservice (F1; PRD §6.2, §8.8, §8.9; US-02, US-23)

- **AC-0.2-1** `RunService` constructs `EmbeddedRuntime` from `RuntimeConfig` with a platform-owned `output_dir`. *Verify:* `grep -rn "EmbeddedRuntime(" platform/backend/app/runtime` shows `RuntimeConfig(...)` + an `output_dir=` argument bound to `settings.OUTPUT_DIR`. (PRD §6.2, §6.5 OQ-4; ADR-P006)
- **AC-0.2-2** The backend never shells the CLI (INV-13). *Verify:* `grep -rnE "subprocess.*dkmv|os\.system.*dkmv|Popen.*\bdkmv\b" platform/backend` is **empty**. (PRD §6.2, N6; INV-13)
- **AC-0.2-3** `GET /api/v1/preflight` returns `get_capabilities()` checks. *Verify:* `grep -rn "get_capabilities" platform/backend/app/api` present; a test asserts the response shape `{ ready, checks:[{id,label,sub,ok}], blockers }`. (PRD §8.9, FR-01-6)
- **AC-0.2-4 (INV-1)** Access-control middleware binds loopback + requires the local token + validates `Host`/`Origin` + applies CSRF. *Verify:* `grep -rnE "127\.0\.0\.1|Origin|Host|csrf" platform/backend/app/security/` is non-empty; a test sends a request with a foreign `Host` → **403**, and a request missing the token → **401**. (PRD §8.8, NFR-SEC-2; INV-1)
- **AC-0.2-5** Error envelope + status conventions are implemented. *Verify:* a test asserts a validation failure returns `400 { "error": { "code": "validation_error", ... } }` and an unknown run returns `404 { "error": { "code": "run_not_found" } }`. (PRD §8.9)
- **AC-0.2-6** Integration: a component runs end-to-end through `RunService` against a throwaway repo (M0 exit). *Verify:* `cd platform/backend && pytest -q -k "runservice and integration"` completes a run and asserts terminal status + artifacts. (PRD §12 M0; US-02)

### 0.3-persistence (F2; PRD §6.5, §6.4, §8.2; US-03)

- **AC-0.3-1 (INV-6)** Pragmas set on every connection. *Verify:* `grep -rnE "journal_mode\s*=\s*WAL|synchronous\s*=\s*NORMAL|busy_timeout|foreign_keys\s*=\s*ON" platform/backend/app/db` covers all four. (PRD §6.5; INV-6)
- **AC-0.3-2 (INV-6)** A single serialized writer task funnels all writes via `BEGIN IMMEDIATE`. *Verify:* `grep -rn "BEGIN IMMEDIATE" platform/backend/app/db` present; `grep -rn "writer" platform/backend/app/db` shows a single dedicated writer task/connection; reads use separate connections. (PRD §6.5; ADR-P002; INV-6)
- **AC-0.3-3 (INV-6 load test)** 5 writers × ~4 Hz → zero `database is locked`. *Verify:* `cd platform/backend && pytest -q -k "writer_load"` passes (asserts 0 lock errors over a 5-writer×4 Hz×N-second run). (PRD §6.5, NFR-SCALE-1; INV-6)
- **AC-0.3-4** Alembic initial migration creates all nine tables + indexes + FK CASCADE. *Verify:* `cd platform/backend && alembic upgrade head` (exit 0); a test queries `sqlite_master` and asserts the table set `{projects,issues,runs,run_stages,events,pause_decisions,run_totals,settings,secrets}`, the five binding indexes, and `ON DELETE CASCADE` on `run_stages/events/pause_decisions/run_totals`. (PRD §6.5)
- **AC-0.3-5** `runs` PK is a UUID; `engine_run_id` separate; `idempotency_key` UNIQUE. *Verify:* migration/test asserts `runs.id` populated by a platform UUID (not the engine id) and a `UNIQUE` constraint on `idempotency_key`. (PRD §6.5; R-8)
- **AC-0.3-6** `events` is append-only with a monotonic id. *Verify:* a test inserts N events and asserts strictly increasing `events.id`; there is no `UPDATE`/`DELETE` path on `events` in the repository (`grep -rnE "UPDATE events|DELETE FROM events" platform/backend/app/db` empty). (PRD §6.4, §6.5)
- **AC-0.3-7 (INV-7 prep)** `spend` is a projection: last-cumulative `cost_usd` per `(run_id, task_index)`, Codex excluded — never `SUM` over events. *Verify:* `grep -rn "task_index" platform/backend/app/db` shows the dedup key in the spend query; `grep -rnE "SUM\(\s*cost_usd\s*\)" platform/backend/app/db` is **empty** (no naive sum); a unit test feeds a multi-task event sequence and asserts the projected run cost equals Σ(final-per-task), with a Codex run contributing $0. (PRD §6.5, §6.4, FR-06-1a; INV-7)
- **AC-0.3-8 (INV-5)** Idempotency claim-insert helper. *Verify:* `grep -rnE "ON CONFLICT.*DO NOTHING|INSERT OR IGNORE" platform/backend/app/db` present and wrapped by `BEGIN IMMEDIATE`; a test fires two concurrent claims for the same `idempotency_key` and asserts exactly one wins. (PRD §8.2; INV-5)
- **AC-0.3-9** `run_totals` snapshot + `VACUUM INTO` backup. *Verify:* `grep -rn "run_totals" platform/backend/app/db` shows a completion-time snapshot writer; `grep -rn "VACUUM INTO" platform/backend` present and a test produces a restorable backup file. (PRD §6.5)

### 0.4-executor (F3; PRD §8.7, §8.8; US-04)

- **AC-0.4-1** `Executor` interface + `LocalDockerExecutor` exist; the orchestrator depends only on the interface (no direct Docker calls outside the executor). *Verify:* `grep -rn "class Executor" platform/backend/app/executor` present with `start/stream/signal/cleanup`; `grep -rn "class LocalDockerExecutor" platform/backend/app/executor` present. (PRD §8.7; ADR-P008)
- **AC-0.4-2 (INV-3)** gVisor `runsc` is the default runtime, wired from `SANDBOX_RUNTIME`. *Verify:* `grep -rnE "runsc|SANDBOX_RUNTIME|runtime=" platform/backend/app/executor` shows the runtime flag passed to the container start, defaulting to `runsc`. (PRD §8.8, NFR-SEC-4; ADR-P005; INV-3)
- **AC-0.4-3** Documented weaker-isolation opt-in + warning (OQ-6). *Verify:* `grep -rni "runsc.*unavailable\|weaker isolation\|isolation warning" platform/backend platform/README.md` non-empty; a test asserts a non-`runsc` runtime logs/raises the documented warning. (PRD §8.8, OQ-6; ADR-P005)
- **AC-0.4-4** Docker socket is brokered, not raw-mounted. *Verify:* `grep -rnE "docker-socket-proxy|tecnativa|rootless|sysbox" platform/docker-compose.yml platform/backend/app/executor` present; `grep -rn "/var/run/docker.sock" platform/docker-compose.yml` shows it mounted **only** into the broker/proxy service, never directly into the backend. (PRD §8.8; ADR-P005)

### 0.5-secrets-egress (F3; PRD §8.6, NFR-SEC-1..5; US-04, US-23)

- **AC-0.5-1 (INV-3)** Network-enforced egress allowlist, default-on, GitHub + model APIs only, pinned DNS. *Verify:* `grep -rnE "EGRESS_ALLOWLIST|egress|allowlist" platform/backend/app/executor` shows the allowlist applied at the network layer; a test asserts a non-allowlisted host is **blocked** and an allowlisted one is reachable. (PRD §8.6, NFR-SEC-1; INV-3)
- **AC-0.5-2 (INV-4)** Encrypted `SecretStore` + file-mount injection (not env). *Verify:* `grep -rn "class SecretStore" platform/backend/app/secrets` present with encrypt-at-rest; `grep -rni "file.*mount\|mount.*secret" platform/backend/app/secrets platform/backend/app/executor` shows secrets injected via file mount; a test round-trips an encrypted secret. (PRD §8.6, NFR-SEC-1; INV-4)
- **AC-0.5-3 (INV-4)** GitHub token is repo-scoped + ≤1 hr TTL. *Verify:* `grep -rnE "ttl|expires|3600|1 ?hr|repo.scoped" platform/backend/app/secrets` shows the ≤1 hr scoping; a test asserts the minted token cannot push to a second repo (mock). (PRD §8.6, NFR-SEC-1; INV-4)
- **AC-0.5-4 (INV-4)** Redact-before-persist covers known secret patterns. *Verify:* `grep -rnE "sk-ant-|ghp_|github_pat_|ANTHROPIC_API_KEY" platform/backend/app | grep -iv "redact|alias|env|test|settings|config"` shows **no** secret value written toward `events`/logs; a unit test feeds each pattern through the redactor and asserts the persisted payload is scrubbed. (PRD §8.6; INV-4)
- **AC-0.5-5** Security baseline test suite green. *Verify:* `cd platform/backend && pytest -q -k "security_baseline"` passes (egress-denied, no-secret-in-events, Host/Origin/CSRF reject, token-scope). (PRD §13 security profile; US-04, US-23)

### Cross-cutting (INV-13 — engine locked)

- **AC-X-1 (INV-13)** No file under `dkmv/` changes in any Phase 0 PR. *Verify:* `git diff --name-only main..<branch> -- dkmv/` is **empty** for every slice branch. (PRD §6.2, N6; `lock-engine.sh`; INV-13)
- **AC-X-2** Quality gates green for the whole phase. *Verify:* `cd platform/backend && ruff check . && mypy app && pytest -q` (exit 0); `cd platform/frontend && npx tsc --noEmit` (exit 0 — scaffold only). (PRD §13; `_conventions.md`)

---

## SECURITY_CHECKS

Concrete greps drawn from the INVs that apply to Phase 0 (INV-1, INV-3, INV-4, INV-5, INV-6, INV-13). The evaluator runs every line; the expected result is noted.

```bash
cd platform   # repo root for the platform

# INV-1 — App access control (loopback + token + Host/Origin + CSRF)
grep -rnE "127\.0\.0\.1|Origin|Host|csrf" backend/app/security/        # non-empty
# (+ a test: foreign Host → 403, missing token → 401)

# INV-3 — Sandbox isolation + egress allowlist (gVisor + network-enforced allowlist)
grep -rnE "runsc|SANDBOX_RUNTIME" backend/app/executor                 # non-empty (default runsc)
grep -rnE "EGRESS_ALLOWLIST|egress|allowlist" backend/app/executor     # non-empty
grep -rn "/var/run/docker.sock" docker-compose.yml                     # only on the broker/proxy service, never the backend

# INV-4 — Secret hygiene (no secret written to events/logs; redaction covers patterns)
grep -rnE "sk-ant-|ghp_|github_pat_|ANTHROPIC_API_KEY" backend/app | grep -iv "redact|alias|env|test|settings|config"   # empty
grep -rni "redact" backend/app/secrets backend/app/db                  # non-empty (redactor present)

# INV-5 — Dispatch idempotency (SQLite-correct: ON CONFLICT, never SKIP LOCKED)
grep -rnE "ON CONFLICT.*DO NOTHING|INSERT OR IGNORE" backend/app/db    # present
grep -rn "SKIP LOCKED\|FOR UPDATE" backend                             # MUST be empty (SQLite has neither)

# INV-6 — SQLite concurrency contract (pragmas + single writer + BEGIN IMMEDIATE)
grep -rnE "journal_mode\s*=\s*WAL|synchronous\s*=\s*NORMAL|busy_timeout|foreign_keys\s*=\s*ON" backend/app/db  # all four
grep -rn "BEGIN IMMEDIATE" backend/app/db                              # present

# INV-13 — Engine consumed in-process, never shelled, never modified
grep -rnE "subprocess.*dkmv|os\.system.*dkmv" backend                  # empty
git diff --name-only main..HEAD -- ../dkmv/                            # empty (engine untouched)
```

---

## DESIGN_FIDELITY

**n/a — Phase 0 has no UI slices except the scaffold.** The only frontend work in this phase is the Vite **scaffold** in `0.1-scaffold` (app boots, router stub, design-token file ported but no screens). There are no Screens 01–07, no chrome, and no state-conveying components in Phase 0, so INV-14 (design-tokens-only + a11y) has nothing to check beyond verifying the scaffold compiles. Design-fidelity and the no-hardcoded-hex hook become live in **Phase 1** (F5/F6) when the first real screens land.

- The one scaffold-level check: `cd platform/frontend && npx tsc --noEmit` (exit 0). No `show_widget`/design-review pass is required in Phase 0.

---

## Test plan

| Profile | What it covers | Where |
|---|---|---|
| **Unit** | Settings parsing of the §8.8 env surface; error-envelope shaping; `spend` projection math (last-cumulative per `(run_id, task_index)`, Codex $0 excluded); idempotency claim-insert (two racers → one wins); event-log monotonic id + append-only; redactor pattern coverage (`sk-ant-`/`ghp_`/`github_pat_`/`ANTHROPIC_API_KEY`). | `platform/backend/tests/unit/` |
| **Concurrency** | 5-writer × ~4 Hz load test → **zero** `database is locked` (INV-6, NFR-SCALE-1). | `platform/backend/tests/unit/test_writer_load.py` |
| **Integration** | `RunService` drives `EmbeddedRuntime` against a throwaway repo + the `dkmv-sandbox` image to a terminal status with artifacts (M0 exit); Alembic `upgrade head` then schema/index/FK assertions. | `platform/backend/tests/integration/` |
| **Security baseline** | Egress denial of a non-allowlisted host; no secret value in the `events` table after a run; Host/Origin/CSRF rejection (403) + missing-token (401); GitHub token cannot push to a second repo; brokered-socket (backend has no direct `docker.sock`). | `platform/backend/tests/security/` |
| **Smoke** | `docker compose up` → `GET /api/v1/preflight` 200 on `127.0.0.1:8787`. | manual / CI smoke |

Coverage gate: `pytest -q --cov` ≥ 80% on the backend (per `_conventions.md` quality bar). The frontend ships only a scaffold, so `npx tsc --noEmit` is the gate there (no vitest suites required until Phase 1).

---

## Independent verification commands

The evaluator runs this block; every command must exit 0 / match the noted expectation.

```bash
# --- Backend quality gates (lint, types, tests, coverage) ---
cd platform/backend
ruff check .
ruff format --check .
mypy app
pytest -q --cov --cov-fail-under=80

# --- Frontend scaffold type-check (no screens yet) ---
cd ../frontend
npx tsc --noEmit

# --- SQLite-lock guard: SKIP LOCKED / FOR UPDATE must NOT appear (INV-5/INV-6) ---
cd ..
grep -rn "SKIP LOCKED\|FOR UPDATE" backend && echo "FAIL: forbidden SQLite-incompatible locking" || echo "OK: no SKIP LOCKED/FOR UPDATE"

# --- 5-writer load test: zero 'database is locked' (INV-6) ---
cd backend && pytest -q -k "writer_load" -o log_cli=true

# --- Engine untouched (INV-13): no diff under dkmv/ on any slice branch ---
cd ..
test -z "$(git diff --name-only main..HEAD -- ../dkmv/)" && echo "OK: engine untouched" || { echo "FAIL: engine modified"; git diff --name-only main..HEAD -- ../dkmv/; }

# --- Secret-in-events guard (INV-4) ---
grep -rnE "sk-ant-|ghp_|github_pat_" backend/app | grep -i "event\|log" && echo "FAIL: secret near events/log" || echo "OK: no secret near events/log"

# --- In-process engine consumption (INV-13): no CLI shelling ---
grep -rnE "subprocess.*dkmv|os\.system.*dkmv" backend && echo "FAIL: shells the dkmv CLI" || echo "OK: engine consumed in-process"
```

---

*Phase 0 — Foundation · PRD v1.1 · Features F1/F2/F3 · Tasks T010–T032 · INV-1/3/4/5/6/7-prep/13. Last aligned to PRD v1.1 (2026-06-07).*
