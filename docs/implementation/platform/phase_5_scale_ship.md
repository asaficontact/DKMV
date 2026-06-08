# Phase 5 — Scale & Ship (Concurrency, Cost Governance, Hardening, Release)

> **Phase brief** for the DKMV Platform. Source of truth is the PRD (`docs/design_docs/platform/PRD_dkmv_platform_v1.md`); shared rules are in `docs/implementation/platform/_conventions.md` (INV-1..15). This brief is **locked** during implementation (`lock-prd.sh`). Read the PRD §citations inline — do not implement from this brief alone where it points at the PRD.

**PRD version:** v1.1
**PRD milestone:** M5 (Concurrency, hardening, observability — "run 3+ issues concurrently within budget + memory; NFRs met")
**Features:** F13 (Concurrency & Cost Governance), F14 (Hardening & Release)
**User stories:** US-27, US-28 (F13); US-23 (security verification) + cross-cutting (F14)
**Tasks:** T111–T126 (`tasks.md`)
**Timing:** Weeks 14–16
**ADRs:** ADR-P009 (capability-aware cost enforcement — Codex = timeout-only), ADR-P005 (gVisor runtime + egress allowlist + brokered socket + digest/SBOM + PR-push gate); also draws on ADR-P001 (in-process orchestrator), ADR-P002 (SQLite event log / spend projection).

---

## 1. Phase goal

Take the feature-complete platform (Phases 0–4) to a shippable v1: make concurrent dispatch **bounded and resource-admitted**, make cost enforcement **honest per agent capability**, pass the **accessibility + observability** bar, and **harden + release** with a supply-chain-pinned sandbox image, a verified backup story, and an end-to-end acceptance suite that maps the PRD §13 acceptance tests. After Phase 5 a solo dev can `docker compose up` (after the §8.8 setup), run **3+ issues concurrently within budget + memory**, trust that Codex runs are time-bounded, navigate the whole app by keyboard with AA contrast, and the §13 acceptance matrix is signed off.

The load-bearing technical commitments of this phase:

- **Bounded concurrency + aggregate admission** in dispatch: `asyncio.Semaphore(max_concurrent_runs)` (default 3) + optional per-state caps **and** admit only when `Σ container memory ≤ HOST_MEMORY_BUDGET` and `Σ daily spend ≤ DAILY_SPEND_CAP` (PRD §8.2, NFR-SCALE-1).
- A **non-blocking** event loop: all SQLite writes off-loop (executor / `aiosqlite`), event appends batched; loop self-observability **gauges + heartbeat** so a wedged loop is detectable (PRD §8.2, INV-6).
- **Capability-aware cost enforcement** (INV-8 / ADR-P009): branch on `adapter.supports_budget()` / `supports_max_turns()` — Claude → hard budget+turns+timeout; Codex → **timeout-only**, tighter default Codex timeout, API rejects `max_budget_usd`/`max_turns` with `400 unsupported_for_agent`, launch-UI copy "time-bounded, not cost-bounded" (PRD NFR-COST-1, §7.2, §8.10).
- An **accessibility** pass (icon+label state, AA contrast, keyboard nav across board/forms) + **structured logging** (OTel-compatible schema) + an **audit log** (launches, token use, egress denials, decision resolutions) (PRD NFR-A11Y-1, NFR-OBS-1, §8.6).
- A **release** posture: sandbox image **digest-pinned (not `:latest`) + SBOM-scanned** in the build, backup verification + restore doc (`VACUUM INTO`), the **PRD §13 end-to-end acceptance suite**, `docker compose up` docs + README + setup guide, and a final acceptance-matrix sign-off (PRD §13, §8.8, §8.6).

---

## 2. Prerequisites (from prior phases — must be green before starting)

Phase 5 is cross-cutting and depends on **Phase 3 (orchestrator) + all prior phases**. Do not begin a slice until its prerequisites exist and pass:

- **Orchestrator tick / dispatch / reconcile / drain / boot recovery** (F11, T096–T105): the tick loop, UTC-persisted deadlines, idempotent retries, graceful drain, and kill-orphan+`interrupted`+`start_task` boot recovery. 5.1 layers the semaphore + per-state caps + aggregate admission **into the existing dispatch path** (T111 depends on T096), and 5.4's recovery acceptance test (AT-Recovery) drives the Phase-3 recovery path. **No re-attach** (INV-10) — Phase 5 must not regress this.
- **Capability-aware launch baseline** (F7, T063, T066): the run panel that hides budget/turn fields for Codex and the `validate_agent_model` resolution. 5.2 enforces the same capability split **server-side** (T116 depends on T066; T117 depends on T063) and tightens the Codex default timeout.
- **HITL bridge incl. the PR-push approval gate** (F9, T080, T087): the platform-injected approval checkpoint (NFR-SEC-5). 5.3's audit log records decision resolutions (T123 depends on T080); 5.4's AT-PromptInjection drives the gate.
- **Sandbox security baseline** (F3, T026–T032): `LocalDockerExecutor` under gVisor (`runsc`, `SANDBOX_RUNTIME`), the default-on network-enforced egress allowlist, the brokered docker socket, the encrypted `SecretStore` with repo-scoped ≤1 hr token, and redact-before-persist. 5.4's release config **pins** these on (AT-Isolation, AT-Security); 5.4's image work adds digest+SBOM on top.
- **Persistence + spend projection + backup hook** (F2, T018, T022, T023): WAL pragmas + single serialized writer, the `spend` materialized projection (Codex-excluded), and the `VACUUM INTO` backup hook. 5.1's non-blocking loop offloads writes through this layer (T113); 5.4 verifies the backup+restore (T122 depends on T022); admission reads the daily-spend rollup (T112 depends on T023).
- **Live run observability + meters** (F8, T068–T079, esp. T090 board/run UI): 5.3's a11y pass extends the existing screens (T119 depends on T090).

If any prerequisite is missing or red, stop and finish the owning phase first (per `CLAUDE.md` phase discipline).

---

## 3. Scope

### IN scope (this phase)

- **Bounded concurrency + aggregate admission** in dispatch: `asyncio.Semaphore(max_concurrent_runs)` (default 3) + optional per-state caps; admit only if `Σ(running container memory) + this run's memory ≤ HOST_MEMORY_BUDGET` **and** `Σ(today's spend) ≤ DAILY_SPEND_CAP`; non-blocking loop (off-loop DB writes + batched appends); loop self-observability gauges + heartbeat; concurrency tests (F13 / §8.2, NFR-SCALE-1).
- **Capability-aware cost enforcement** (F13 / NFR-COST-1, §7.2, ADR-P009): hard budget+turns+timeout for Claude; timeout-only for Codex (branch on `supports_budget()` / `supports_max_turns()`); tighter default Codex timeout; API `400 unsupported_for_agent` for Codex budget/turn caps; launch-UI copy "time-bounded, not cost-bounded"; cost-governance tests.
- **Accessibility + observability** (F14 / NFR-A11Y-1, NFR-OBS-1, §8.6): a11y pass (icon+label state, AA contrast, keyboard nav across board + forms); structured logging (OTel-compatible schema; full OTel **deferred**, N8); audit log (run launches, token mint/use, egress denials, decision resolutions).
- **Release** (F14 / §13, §8.8, §8.6): sandbox image **digest pinning + SBOM scan** in the build; backup verification + restore doc (`VACUUM INTO`); the **end-to-end §13 acceptance test suite** (AT-Connect / Board / Launch / Live / HITL / Recovery / History / Workflows / Concurrency / Isolation / PromptInjection / CodexCost); `docker compose up` docs + platform README + setup guide; final integration verification + acceptance-matrix sign-off.

### OUT of scope (explicitly deferred — all post-v1)

- **GitHub App + webhooks** (bot identity, per-install tokens, HMAC `X-Hub-Signature-256`, `X-GitHub-Delivery` dedupe, echo-suppression) → deferred / "Later" per ADR-P004, PRD §8.1, §12. v1 stays **PAT-first + poll-only**. The webhook-integrity NFR-SEC-3 grep MUST stay empty (no inbound receiver).
- **Cloud / remote executor** (`SSHRemoteDockerExecutor`, Fargate, Modal, K8s) → post-v1 (N2, §8.7); requires the engine ask §11.3. v1 ships `LocalDockerExecutor` only. The `Executor` seam already exists (F3) — do **not** add a remote backend here.
- **Full workflow authoring UI** (form→YAML builder, pause-question editor, for-each UX) → v1.1 (N7, §5.8). Phase 4 shipped the read-only viewer; Phase 5 adds nothing to authoring.
- **Full OpenTelemetry GenAI tracing** (`invoke_agent`→`chat`/`execute_tool` spans, `gen_ai.usage.*_tokens`, tail-sampling) → post-v1 (N8, NFR-OBS-1). v1 ships structured logs with an **OTel-compatible schema** only — an additive upgrade later, not the tracer.
- **Redis fan-out** and the **Postgres** repository abstraction → post-v1 (N8, §8.3, NFR-PORT-1). v1 is in-process SSE fan-out + direct SQLite. The dispatch/concurrency model intentionally does **not** port as-is (single-process `UNIQUE`-key claim; multi-process would need `FOR UPDATE SKIP LOCKED` + leader election — NFR-PORT-1). Do not add `SKIP LOCKED`/`FOR UPDATE` (INV-5 guard stays empty).
- **Multi-tenant / RBAC / orgs** → post-v1 (N1). The nullable `tenant_id` hedge stays; no tenancy logic is built.
- **Engine changes** (`dkmv/`) → out of scope (INV-13, N6). The capability-aware Codex cost signal (§11.7) is an *engine ask*, not built here; v1 works around it with timeout-only + tighter default timeout + daily-spend admission.

---

## 4. Slices

Slice IDs are `5.k-name`. Each maps to a feature and PRD §. "Files" lists the primary edit surface used by the wave plan (no two same-wave slices share a file).

### 5.1 — `5.1-concurrency` (F13 / §8.2, NFR-SCALE-1)

**What:** bounded concurrency + aggregate-resource admission + non-blocking, self-observable loop, layered into the Phase-3 dispatch path.

- **Bounded concurrency:** gate dispatch with `asyncio.Semaphore(max_concurrent_runs)` (config `MAX_CONCURRENT_RUNS`, **default 3**) + **optional per-state caps** (e.g. throttle `agent:queued`). A pause **releases the slot** (already wired in F9 §8.5) and re-acquires on resume — Phase 5 must not regress that (INV-9). `grep` target: `asyncio.Semaphore` in the orchestrator (§8.2).
- **Aggregate-resource admission:** per-run caps alone don't bound the expensive dimensions, so a run is admitted **only if** `Σ(running container memory) + this run's memory ≤ HOST_MEMORY_BUDGET` **and** `Σ(today's spend) ≤ DAILY_SPEND_CAP` (§8.2). Daily spend reads the Phase-0 `spend` projection (Codex-excluded, INV-8/FR-06-1a — Codex runs contribute `$0` and never trip the spend cap; their memory still counts toward the memory budget). Admission denial re-queues the candidate for a later tick, never silently drops it.
- **Non-blocking loop:** all SQLite writes go through an off-loop executor / `aiosqlite` and event appends are **batched** so a blocking call can't wedge the single event loop (§8.2, §6.5 / INV-6). No synchronous DB I/O on the loop thread.
- **Loop self-observability (full):** emit gauges — tick duration, time-since-last-successful-tick, slots-in-use, queue depth, reconcile actions, dispatch latency — plus a loop **heartbeat**, so a wedged loop is detectable (§8.2). (Phase 3 may have stubbed a subset; 5.1 completes them.)
- **Concurrency tests:** launch `> max_concurrent_runs` issues → only N execute at once, the rest queue (NFR-SCALE-1); a run exceeding `HOST_MEMORY_BUDGET` / `DAILY_SPEND_CAP` is admission-denied and re-queued.
- **Files:** `platform/backend/app/orchestrator/dispatch.py` (semaphore + per-state caps), `platform/backend/app/orchestrator/admission.py` (aggregate memory/spend admission), `platform/backend/app/orchestrator/loop_metrics.py` (gauges + heartbeat), `platform/backend/app/orchestrator/writer.py` (off-loop batched writes — extends the F2 single-writer task), `platform/backend/tests/test_concurrency.py`.
- **Tasks:** T111, T112, T113, T114, T115.

### 5.2 — `5.2-cost-governance` (F13 / NFR-COST-1, §7.2, ADR-P009)

**What:** capability-aware cost enforcement — Claude hard-capped, Codex timeout-only.

- **Branch on capability, not assumption** (INV-8, ADR-P009): enforce via `adapter.supports_budget()` / `adapter.supports_max_turns()` — never a blanket "budget cap exists." `grep` target: `supports_budget` / `supports_max_turns` present in `platform/backend/app` (§8.2/§8.10).
- **Claude** (`supports_budget`/`supports_max_turns` = true): enforce `max_budget_usd` + `max_turns` + `timeout_minutes` as **hard caps** (not suggestions), with an optional soft-threshold pause-for-approval and the Settings daily spend alert. The aggregate daily-spend admission cap (5.1) bounds total spend across runs.
- **Codex** (both false — verified: cost `$0.00`, no budget, no turn cap): `timeout_minutes` is the **only** runtime guardrail. (a) The API **rejects** `max_budget_usd` / `max_turns` for a resolved Codex agent with `400 unsupported_for_agent` (§8.10 validation — extend the Phase-2 validator, do not silently ignore). (b) Codex workflows default to a **tighter** `timeout_minutes` than the prototype's `dev=40`/`docs=20` (§7.2 footnote ³ — it is the sole bound). (c) The launch UI states **"Codex runs are time-bounded, not cost-bounded."** (d) Codex cost renders "—" and is excluded from spend (already F8/F10; 5.2 must not regress).
- **Cost-governance tests:** a Codex run with `max_budget_usd` → `400 unsupported_for_agent`; a Codex run is bounded by timeout (no budget cap fires); a Claude run is budget-capped (hard cap fires). Assert the Codex default timeout is **strictly tighter** than the equivalent Claude default.
- **Files:** `platform/backend/app/orchestrator/enforcement.py` (capability-aware cap application), `platform/backend/app/api/validation.py` (extend with the Codex `400 unsupported_for_agent` for budget/turns — same module as §8.10), `platform/backend/app/config/defaults.py` (tighter Codex default timeout), `platform/frontend/src/components/RunGuardrails.tsx` (the "time-bounded, not cost-bounded" copy in the run panel only), `platform/backend/tests/test_cost_governance.py`.
- **Tasks:** T116, T117, T118.

### 5.3 — `5.3-a11y-obs` (F14 / NFR-A11Y-1, NFR-OBS-1, §8.6)

**What:** the accessibility pass + structured logging + audit log. Runs **in parallel** with 5.2 on disjoint files (frontend a11y primitives + backend logging/audit, never the run-panel copy or the enforcement path).

- **Accessibility pass** (NFR-A11Y-1 / INV-14): **state by icon+label, not color alone** (the shared `StateBadge` already enforces this — verify it everywhere); **AA contrast** in dark and light (audited against the ported tokens); **keyboard navigation** across the board (column/card focus order, drag Backlog↔Queued operable by keyboard) and forms (run panel, settings, decision card). Deliver via new a11y primitives (focus management, skip link, keyboard-drag handler, roving-tabindex hook) + an **axe-based** render test over the key screens — **without** editing per-component copy (so 5.2's run-panel copy line is untouched).
- **Structured logging** (NFR-OBS-1): structured logs carrying `run_id` / `issue` / `session` context across the backend, schema **OTel-compatible** so the deferred OTel tracer (N8) is an additive upgrade — but **not** the tracer itself. Redact-before-persist applies (INV-4 — no secret in a log line).
- **Audit log** (§8.6, separate from the agent event stream): record **run launches, token mint/use, egress denials, decision resolutions** to a durable audit sink. Secrets are redacted (INV-4); the audit log is a security-evidence trail, not a debug log.
- **Files:** `platform/frontend/src/a11y/focus.ts`, `platform/frontend/src/a11y/keyboard-drag.ts`, `platform/frontend/src/a11y/SkipLink.tsx`, `platform/frontend/tests/a11y.test.tsx` (axe), `platform/backend/app/observability/logging.py` (structured-log schema + context), `platform/backend/app/security/audit.py` (audit sink), `platform/backend/tests/test_audit.py`.
- **Tasks:** T119, T120, T123.

### 5.4 — `5.4-release` (F14 / §13, §8.8, §8.6)

**What:** supply-chain pinning, backup verification, the §13 end-to-end acceptance suite, docs, and sign-off. Runs **last** (depends on 5.1 + 5.2 + 5.3).

- **Image digest pinning + SBOM scan in the build** (§8.6, ADR-P005): pin the sandbox image **by digest** (`dkmv-sandbox@sha256:…`), **not `:latest`**, in the release/compose config, and generate/scan an SBOM (Trivy / Docker Scout) in the build. `DKMV_IMAGE` resolves to a digest in prod config. `grep` targets: a `@sha256:` pin present in the release config; **no `dkmv-sandbox:latest` in the release/compose config** (dev may still use the tag, but the prod/release path pins).
- **Backup verification + restore doc** (§6.5): verify the `VACUUM INTO` snapshot path produces a restorable DB and document the restore procedure (the single SQLite file is the source of truth for spend + audit). A test asserts a snapshot round-trips (snapshot → restore → row counts + a spend rollup match).
- **End-to-end §13 acceptance suite:** an e2e suite mapping the PRD §13 acceptance tests — **AT-Connect, AT-Board, AT-Launch, AT-Live, AT-HITL, AT-Recovery, AT-History, AT-Workflows, AT-Concurrency, AT-Isolation, AT-PromptInjection, AT-CodexCost** (PRD §13). Concurrency/CodexCost reuse 5.1/5.2; Isolation/PromptInjection assert the gVisor runtime + egress denial + repo-scoped token + PR-push gate (§13, NFR-SEC-1/4/5). Integration tests run against a throwaway repo + the `dkmv-sandbox` image.
- **`docker compose up` docs + README + setup guide:** document the §8.8 dev-env setup (editable engine install, `docker build -t dkmv-sandbox` then digest-pin, brokered socket, platform-owned `output_dir`, the consolidated env surface) and the `docker compose up` deploy; ship `platform/README.md`.
- **Final integration verification + acceptance-matrix sign-off:** run the full §13 matrix, confirm every AT passes, and record the sign-off.
- **Files:** `platform/docker-compose.yml` (digest pin), `platform/Dockerfile.backend` / `platform/scripts/sbom-scan.sh` (SBOM scan step), `platform/backend/app/db/backup.py` (verify + restore helper, extends the F2 hook), `platform/backend/tests/e2e/` (the §13 suite), `platform/backend/tests/test_backup.py`, `platform/README.md`, `platform/docs/setup.md`.
- **Tasks:** T121, T122, T124, T125, T126.

---

## 5. Wave plan

No two slices in the same wave edit the same file. Backend orchestrator/observability/security and frontend a11y/run-panel surfaces are split per slice; 5.2's only frontend touch is `RunGuardrails.tsx` (launch copy), 5.3's a11y work lives in new `a11y/*` modules + an axe test (it does **not** edit the run panel copy), so 5.2 and 5.3 are disjoint and run in the same wave.

| Wave | Slices | Rationale / dependency |
|---|---|---|
| **A** | `5.1-concurrency` | First. Layers the semaphore + per-state caps + aggregate admission + non-blocking loop + gauges into the Phase-3 dispatch path (T111 → T096). Everything else assumes bounded dispatch. |
| **B** | `5.2-cost-governance`, `5.3-a11y-obs` | **In parallel** (different files). 5.2 after 5.1 (admission/daily-spend cap is the spend-side companion to per-run caps; T116 → T066). 5.3 is independent (frontend a11y primitives + backend logging/audit) and shares no file with 5.2 — 5.2 edits `RunGuardrails.tsx`, `enforcement.py`, `validation.py`, `defaults.py`; 5.3 edits `a11y/*`, `observability/logging.py`, `security/audit.py`. |
| **C** | `5.4-release` | **Last.** Depends on 5.1 (concurrency AT), 5.2 (Codex-cost AT), and 5.3 (a11y/audit evidence in the security ATs). Adds digest/SBOM, backup verification, the full §13 e2e suite, docs, and sign-off. |

Critical path: A → B → C. Within B, 5.2 and 5.3 are concurrent.

**Intra-slice ordering note:** in 5.2, sequence T116 (Claude hard caps) → T117 (Codex timeout-only + tighter default + UI copy) → T118 (tests). In 5.4, the e2e suite (T124) must come after 5.1's T115 and 5.2's T118 land (it reuses AT-Concurrency / AT-CodexCost), and the sign-off (T126) is strictly last.

---

## 6. Acceptance criteria (greppable, with PRD §citations)

Each criterion is verifiable by a grep/command + a test. Backend greps run under `platform/backend/`, frontend under `platform/frontend/src/`.

### F13 — Concurrency & Cost Governance

- **AC-1 (5.1, §8.2 / NFR-SCALE-1).** Dispatch is gated by `asyncio.Semaphore(max_concurrent_runs)` (default 3). `grep -rn "asyncio.Semaphore\|max_concurrent_runs\|MAX_CONCURRENT_RUNS" platform/backend/app/orchestrator` is non-empty. A test launches **> `max_concurrent_runs`** issues and asserts **only N run at once**, the rest queue, then drain as slots free.
- **AC-2 (5.1, §8.2).** Optional **per-state caps** exist in dispatch (e.g. throttle `agent:queued`). `grep -rni "per.state\|state_cap\|per_state" platform/backend/app/orchestrator/dispatch.py` non-empty; a test asserts a configured per-state cap throttles that state.
- **AC-3 (5.1, §8.2 — aggregate admission, binding).** A run is admitted only if `Σ(running container memory) + this run ≤ HOST_MEMORY_BUDGET` **and** `Σ(today's spend) ≤ DAILY_SPEND_CAP`. `grep -rn "HOST_MEMORY_BUDGET\|DAILY_SPEND_CAP" platform/backend/app` non-empty. A test asserts a run that would exceed the memory budget **or** the daily-spend cap is **admission-denied and re-queued** (not dropped, not dispatched). Daily spend uses the Codex-excluded `spend` projection (INV-8).
- **AC-4 (5.1, §8.2 / §6.5 — INV-6).** The loop is **non-blocking**: SQLite writes go off-loop (executor / `aiosqlite`) and event appends are batched. `grep -rni "run_in_executor\|aiosqlite\|batch" platform/backend/app/orchestrator` non-empty; no synchronous `sqlite3` write call runs on the loop thread (reviewed + tested). `grep -rn "SKIP LOCKED\|FOR UPDATE" platform/backend` is **empty** (INV-5).
- **AC-5 (5.1, §8.2 — loop observability).** Loop gauges + a heartbeat are emitted (tick duration, time-since-last-successful-tick, slots-in-use, queue depth, reconcile actions, dispatch latency). `grep -rni "heartbeat\|tick_duration\|slots_in_use\|gauge" platform/backend/app/orchestrator` non-empty; a test asserts the heartbeat advances each tick and the slots-in-use gauge tracks the semaphore.
- **AC-6 (5.2, INV-8 / NFR-COST-1 — binding, capability-aware).** Enforcement **branches on adapter capability**. `grep -rn "supports_budget\|supports_max_turns" platform/backend/app` is **non-empty**. A test asserts a Codex run launched with `max_budget_usd` (or `max_turns`) is rejected with **`400 unsupported_for_agent`** (asserting the `400` status + `unsupported_for_agent` code).
- **AC-7 (5.2, NFR-COST-1 / §7.2 — Codex timeout-only).** Codex enforcement is **timeout-only** and the Codex default timeout is **strictly tighter** than the Claude default. A test asserts a Codex run is bounded by `timeout_minutes` (no budget/turn cap fires) and that `codex_default_timeout < claude_default_timeout`.
- **AC-8 (5.2, NFR-COST-1 — Claude hard caps).** For Claude (`supports_budget` true), `max_budget_usd` + `max_turns` + `timeout_minutes` are enforced as **hard caps**. A test asserts a Claude run hitting its budget cap is stopped (cap fires, not a suggestion).
- **AC-9 (5.2, NFR-COST-1 / §7.2 — launch-UI copy).** The launch UI states Codex runs are time-bounded, not cost-bounded. `grep -rni "time-bounded, not cost-bounded\|time-bounded" platform/frontend/src/components/RunGuardrails.tsx` non-empty; a render test asserts the copy shows for a Codex selection and budget/turn fields stay hidden (FR-03-2, R-10).

### F14 — Hardening & Release

- **AC-10 (5.3, NFR-A11Y-1 — INV-14).** State is conveyed by **icon + label**, not color alone, everywhere the `StateBadge` is used; **AA contrast** holds in dark and light; **keyboard navigation** works across the board (card focus + keyboard drag Backlog↔Queued) and forms. An **axe** render test over the board + run panel + decision card reports **no critical violations**; a keyboard-only test moves a card Backlog→Queued without a mouse.
- **AC-11 (5.3, NFR-OBS-1).** Structured logs carry `run_id`/`issue`/`session` context in an OTel-compatible schema (the tracer itself is deferred, N8). `grep -rni "run_id\|structlog\|structured" platform/backend/app/observability/logging.py` non-empty; a test asserts a log record includes the run/issue context fields and that **no secret pattern** appears (INV-4).
- **AC-12 (5.3, §8.6 — audit log).** An audit log records **run launches, token mint/use, egress denials, decision resolutions**. `grep -rni "audit" platform/backend/app/security/audit.py` non-empty; a test asserts each of the four event kinds is recorded and that no secret literal is written (INV-4).
- **AC-13 (5.4, §8.6 — INV-3, image supply chain).** The sandbox image is **digest-pinned (not `:latest`)** in the release/compose config and an **SBOM scan** runs in the build. `grep -rn "@sha256:" platform/docker-compose.yml platform/Dockerfile.backend` non-empty; `grep -rni "dkmv-sandbox:latest" platform/docker-compose.yml` is **empty** (release path pins by digest); `grep -rni "sbom\|trivy\|scout" platform` non-empty (SBOM scan step present).
- **AC-14 (5.4, §6.5 — backup).** The `VACUUM INTO` backup round-trips and the restore procedure is documented. A test asserts snapshot → restore → row counts + a spend rollup match; `platform/docs/setup.md` (or README) documents restore.
- **AC-15 (5.4, §13 — INV-3/4 verified in release tests, binding).** The release suite verifies the egress allowlist (a non-allowlisted host is **blocked + logged**), the gVisor runtime (`runsc`/`SANDBOX_RUNTIME`), the **repo-scoped** GitHub token (cannot push to another repo), and **no secret in logs/events/audit**. `grep -rn "runsc\|SANDBOX_RUNTIME" platform/backend/app` non-empty (AT-Isolation); the e2e `AT-Isolation` + `AT-Security` tests assert egress-deny, repo-scope, and secret-hygiene.
- **AC-16 (5.4, §13 / NFR-SEC-5 — PR-push gate, binding).** A run whose issue body contains an injected instruction still requires **human approval before the PR push** (the NFR-SEC-5 gate fires via the HITL pause primitive). The e2e `AT-PromptInjection` test asserts the PR is not pushed until the approval decision resolves.
- **AC-17 (5.4, §13 — acceptance matrix).** The end-to-end suite maps **all** PRD §13 acceptance tests — AT-Connect, AT-Board, AT-Launch, AT-Live (segment-sum cost climbs to run total, no reset; SSE replay no-gaps-no-dups; no token in the SSE URL), AT-HITL (resolve-exactly-once + slot release), AT-Recovery (kill-orphan + `interrupted` + `start_task`, no duplicate PR, no orphaned container — INV-10), AT-History (Codex-excluded spend), AT-Workflows, AT-Concurrency, AT-Isolation, AT-PromptInjection, AT-CodexCost ("—" not "$0.00", excluded from spend, tokens counted). `grep -rni "AT-Concurrency\|AT-CodexCost\|AT-PromptInjection\|AT-Isolation" platform/backend/tests/e2e` non-empty; **the full §13 e2e suite passes**.

---

## 7. SECURITY_CHECKS

Concrete greps/tests from the applicable INVs (`_conventions.md`). All must hold at phase exit.

- **INV-3 — Sandbox isolation + egress allowlist (NFR-SEC-1/4, §8.6, ADR-P005).** The release config pins the **gVisor (`runsc`) runtime** on and the **network-enforced egress allowlist** default-on (GitHub + model APIs, pinned DNS). `grep -rn "runsc\|SANDBOX_RUNTIME\|EGRESS_ALLOWLIST" platform/backend/app` non-empty; the `AT-Isolation` e2e test asserts a **non-allowlisted host is blocked + the denial is logged** (and surfaced to the audit log per AC-12). Phase 5 must not weaken the Phase-0 default-on posture.
- **INV-4 — Secret hygiene (no secret in logs/audit, §8.6).** Structured logs and the audit log are **redact-before-persist**; no secret pattern reaches them. `grep -rnE "sk-ant-|ghp_|github_pat_|ANTHROPIC_API_KEY|CODEX_API_KEY" platform/backend/app | grep -iv "redact\|alias\|env\|test"` shows **no** secret being written to a log/audit/event line; the redaction function covers those patterns; `AT-Security` asserts the `events` table + logs + audit are secret-free. The GitHub token stays **repo-scoped + ≤1 hr** (verified in `AT-Isolation`).
- **Image supply chain (digest + SBOM, §8.6, ADR-P005).** The sandbox image is **digest-pinned, not `:latest`**, in the release/compose path and an SBOM is generated + scanned in the build. `grep -rn "@sha256:" platform/docker-compose.yml platform/Dockerfile.backend` non-empty; `grep -rni "dkmv-sandbox:latest" platform/docker-compose.yml` **empty**; `grep -rni "sbom\|trivy\|scout" platform` non-empty (AC-13).
- **NFR-SEC-5 — Prompt-injection PR-push gate.** The platform-injected human-approval gate on the irreversible **PR push** fires for an injected issue body (defense-in-depth, not prevention). The `AT-PromptInjection` e2e test asserts the gate (AC-16). This reuses the F9 pause primitive — do not bypass it.
- **App access control + no `SKIP LOCKED` regression.** The loopback+token+Host/Origin+CSRF middleware (INV-1) and the SQLite single-writer model (INV-5/6) are not regressed: `grep -rn "SKIP LOCKED\|FOR UPDATE" platform/backend` stays **empty**; no new unauthenticated route is added; `grep -rni "webhook\|X-Hub-Signature\|X-GitHub-Delivery" platform/backend/app` stays **empty** (App/webhooks OUT, ADR-P004).

> Out-of-phase security INVs (INV-9 HITL resolve-once + slot release, INV-10 no re-attach, INV-11 label write-queue, INV-12 observer bridge) are owned by Phases 1–3 and re-verified here only through the §13 e2e ATs (AT-HITL, AT-Recovery). Phase 5 must not regress them.

## 8. DESIGN_FIDELITY (UI slices 5.2, 5.3)

- **No hardcoded hex in `platform/frontend/src`** outside the tokens file (INV-14). `grep -rnE "#[0-9a-fA-F]{3,8}\b" platform/frontend/src --include=*.tsx --include=*.ts` excluding `styles/tokens.css` is **empty** — the a11y primitives and the run-panel copy add **no** new color literals; all color stays in the ported tokens (`--accent` indigo, `--st-*` state palette, §7.3).
- **AA contrast** in dark and light, audited against the ported tokens — the a11y pass adds no token that fails AA (NFR-A11Y-1). The axe test (AC-10) flags contrast violations.
- **State is never color-only** (INV-14, §7.3): every state surface (board card, run header, history row, sidebar chip, decision card) pairs an **icon + label** via the shared `StateBadge`; running/paused pulse. The a11y pass verifies this everywhere it renders.
- **Keyboard operability** matches the desktop-first interaction model (§7, NFR-A11Y-1): board cards are focusable, the Backlog↔Queued drag is keyboard-operable, the run panel + decision card + settings forms are fully tabbable with a visible focus ring sourced from tokens.
- **Launch-panel copy** ("Codex runs are time-bounded, not cost-bounded") matches the §7.2 footnote framing and the FR-03-2 run panel layout — it appears for a Codex selection only and budget/turn fields stay hidden (R-10).

## 9. Independent verification commands

The evaluator runs these; all must pass (exit 0 / empty where noted).

```bash
# ---- Backend: lint, type, test ----
cd platform/backend && ruff check . && mypy app && pytest -q

# ---- Frontend: type, test ----
cd platform/frontend && npx tsc --noEmit && npx vitest run

# ---- INV-8 / NFR-COST-1: capability-aware enforcement present ----
grep -rn "supports_budget\|supports_max_turns" platform/backend/app   # expect: non-empty
cd platform/backend && pytest -q tests/test_cost_governance.py        # Codex budget -> 400 unsupported_for_agent; Codex tighter default timeout; Claude budget-capped

# ---- NFR-SCALE-1 / §8.2: bounded concurrency + aggregate admission ----
grep -rn "asyncio.Semaphore\|MAX_CONCURRENT_RUNS\|HOST_MEMORY_BUDGET\|DAILY_SPEND_CAP" platform/backend/app   # expect: non-empty
cd platform/backend && pytest -q tests/test_concurrency.py            # > max_concurrent_runs -> only N at once; admission denies+re-queues over memory/spend caps

# ---- INV-5/6: no SQLite SKIP LOCKED / FOR UPDATE; off-loop writes ----
grep -rn "SKIP LOCKED\|FOR UPDATE" platform/backend                    # expect: empty
grep -rni "run_in_executor\|aiosqlite" platform/backend/app/orchestrator   # expect: non-empty

# ---- NFR-A11Y-1 / INV-14: a11y axe check + no hardcoded hex ----
cd platform/frontend && npx vitest run tests/a11y.test.tsx            # axe: no critical violations; keyboard drag Backlog->Queued
grep -rnE "#[0-9a-fA-F]{3,8}\b" platform/frontend/src --include=*.tsx --include=*.ts \
  | grep -v "styles/tokens.css"                                       # expect: empty

# ---- §8.6 / INV-3: image digest-pinned (not :latest) + SBOM scan in build ----
grep -rn "@sha256:" platform/docker-compose.yml platform/Dockerfile.backend   # expect: non-empty
grep -rni "dkmv-sandbox:latest" platform/docker-compose.yml          # expect: empty (release path pins by digest)
grep -rni "sbom\|trivy\|scout" platform                               # expect: non-empty

# ---- INV-3: gVisor runtime + egress allowlist in release config ----
grep -rn "runsc\|SANDBOX_RUNTIME\|EGRESS_ALLOWLIST" platform/backend/app   # expect: non-empty

# ---- INV-4: no secret written to logs/audit/events ----
grep -rnE "sk-ant-|ghp_|github_pat_|CODEX_API_KEY" platform/backend/app \
  | grep -iv "redact\|alias\|env\|test"                              # expect: empty

# ---- §8.6: audit log present ----
grep -rni "audit" platform/backend/app/security/audit.py             # expect: non-empty

# ---- App/webhooks stay deferred (ADR-P004) ----
grep -rni "webhook\|X-Hub-Signature\|X-GitHub-Delivery" platform/backend/app   # expect: empty

# ---- §13: the full end-to-end acceptance suite ----
cd platform/backend && pytest -q tests/e2e                           # all §13 ATs pass (Connect/Board/Launch/Live/HITL/Recovery/History/Workflows/Concurrency/Isolation/PromptInjection/CodexCost)

# ---- Engine untouched (INV-13) ----
git diff --name-only main..HEAD -- dkmv/                              # expect: empty
```

## 10. Test plan

**Backend (pytest):**
- `test_concurrency`: `> max_concurrent_runs` issues → only N run at once, rest queue then drain (AC-1, NFR-SCALE-1); per-state cap throttles (AC-2); aggregate admission denies+re-queues a run over `HOST_MEMORY_BUDGET` **or** `DAILY_SPEND_CAP` (AC-3); daily spend uses the Codex-excluded projection (INV-8).
- `test_loop_observability`: heartbeat advances each tick; slots-in-use gauge tracks the semaphore; gauges populated (AC-5); a simulated blocking call is detectable (loop non-blocking — AC-4).
- `test_cost_governance`: Codex `max_budget_usd`/`max_turns` → `400 unsupported_for_agent` (AC-6); Codex bounded by timeout only + Codex default timeout strictly tighter than Claude (AC-7); Claude hard budget cap fires (AC-8); enforcement branches on `supports_budget`/`supports_max_turns` (INV-8).
- `test_audit`: run launch, token mint/use, egress denial, decision resolution each recorded; no secret literal written (AC-12, INV-4).
- `test_logging`: structured log carries `run_id`/`issue`/`session`; OTel-compatible schema; redaction holds (AC-11, INV-4).
- `test_backup`: `VACUUM INTO` snapshot → restore → row counts + spend rollup match (AC-14).
- `test_security` (release): egress-deny to a non-allowlisted host (blocked + logged); repo-scoped token cannot push to another repo; `runsc`/`SANDBOX_RUNTIME` asserted; no secret in events/logs/audit (AC-15, INV-3/4).

**Backend e2e (`tests/e2e/`, integration against a throwaway repo + the `dkmv-sandbox` image):**
- The PRD §13 acceptance matrix: `AT-Connect`, `AT-Board`, `AT-Launch`, `AT-Live` (segment-sum cost climbs to run total, no reset; SSE `Last-Event-ID` replay no-gaps-no-dups; no token in the SSE URL), `AT-HITL` (resolve-exactly-once, slot released), `AT-Recovery` (kill-orphan + `interrupted` + `start_task` retry, no duplicate PR, no orphaned container — INV-10), `AT-History` (Codex-excluded spend), `AT-Workflows`, `AT-Concurrency` (AC-1/3), `AT-Isolation` (AC-15), `AT-PromptInjection` (PR-push gate fires — AC-16), `AT-CodexCost` ("—" not "$0.00", excluded from spend, tokens counted) (AC-17).

**Frontend (vitest + render):**
- `a11y.test`: axe over board + run panel + decision card reports no critical violations; AA contrast holds; keyboard-only drag Backlog→Queued; full tab order through forms (AC-10).
- `RunGuardrails.test`: "time-bounded, not cost-bounded" copy shows for a Codex selection; budget/turn fields stay hidden for Codex (AC-9, R-10).
- A repo-wide no-hardcoded-hex assertion mirrors the INV-14 grep (DESIGN_FIDELITY).

**Phase exit gate (per `CLAUDE.md`):** all AC checked off, every command in §9 passes, the §10 suites (incl. the full §13 e2e matrix) are green, `ruff`/`mypy`/`tsc`/`vitest` are clean, and the acceptance-matrix sign-off (T126) is recorded. Then update `progress.md` — **this is the v1 ship gate.**

---

**PRD version:** v1.1 · **Phase:** 5 (M5) · **Features:** F13, F14 · **Tasks:** T111–T126 · **ADRs:** ADR-P009, ADR-P005 · Generated against `_conventions.md` INV-1..15.
