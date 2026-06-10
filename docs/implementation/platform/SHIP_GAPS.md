# DKMV Platform v1 — Ship-Gap Remediation Tracker

Tracks every gap from the 6-lens ship-readiness review (2026-06). Each item:
severity · root cause · chosen approach · status. Scope decision (Tawab):
**Hybrid** — all platform-side fixes + the small low-risk engine passthrough
(`RuntimeConfig` runtime/network/dns + file-mount creds); push-gate reclassified
honestly; no heavy engine surgery.

Status legend: ☐ todo · ◐ in-progress · ☑ done (merged) · ⊘ reclassified/documented.

---

## BLOCKING (security + durability + lifecycle)

### G1 — Sandbox isolation not enforced on real runs (gVisor + egress) · CRITICAL ☑ (PR#32)
- **Root cause:** the live path is `launch → RunService → EmbeddedRuntime` (engine), which assembles its own docker args with no `--runtime`/`--network`/`--dns`; `LocalDockerExecutor` (which has them) is never instantiated; `dkmv-egress` network is not in compose. Engine §11.3.
- **Approach (hybrid):** (a) **platform** — fail-closed boot/preflight check that the Docker daemon effective runtime is gVisor (`docker info`) when `SANDBOX_RUNTIME=runsc`, and block dispatch otherwise; (b) **engine passthrough** — `RuntimeConfig` gains `sandbox_runtime`/`egress_network`/`dns`, threaded into the engine container args; (c) **infra** — deploy the `dkmv-egress` internal network + a filtering-proxy sidecar in `docker-compose.yml`, pinned DNS; (d) thread all three from `Settings`.
- **Status:** ☑ done (PR#32) — gVisor fail-closed gate + egress infra + opt-in engine passthrough.

### G2 — Sandbox holds the full operator PAT as an env var · CRITICAL ☑ (PR#32)
- **Root cause:** `build_runtime_config` threads `GITHUB_TOKEN` into the engine which sets it as `env_vars["GITHUB_TOKEN"]` (visible in `docker inspect`); the `SecretStore` file-mount path is unused; per-run minting is the ADR-P004 deferral.
- **Approach (hybrid):** **engine** — inject the credential as a read-only file mount under `/run/secrets/` instead of an env var; **platform** — pass via the mount. (Per-run minting stays a documented post-v1/GitHub-App ask.)
- **Status:** ☑ done (PR#32) — PAT now file-mounted at /run/secrets/github_token; not in env/docker inspect.

### G3 — Mid-run crash orphans a money-spending container recovery can't kill · CRITICAL
- **Root cause:** `runs.engine_run_id` (the only container handle) is written only at completion; recovery's reaper returns `False` on a `NULL` id → no `docker kill`. Tests pre-seed the id → vacuous pass.
- **Approach (platform):** persist `engine_run_id` to the DB on the **first stamped engine frame** (via the observer bridge/pump), not at completion; add a backstop (engine-labelled container or the engine's filesystem-scan reconcile); add the `engine_run_id=NULL` recovery test.
- **Status:** ◐ in-progress — `EventPump._persist_engine_run_id_early` writes `engine_run_id` the moment the hub first captures it (first stamped engine frame), shrinking the orphan window from "the whole run" to "before the first engine frame". The completion back-fill is kept as a harmless backstop. Non-vacuous recovery tests added: a run WITH the early-persisted id drives the **real** `DockerOrphanReaper` to issue a `docker kill`; a `NULL`-id orphan is reliably marked `interrupted` (never stranded) but cannot be killed — the documented **residual window**. **RESIDUAL WINDOW (accepted, §11 ask):** a crash strictly *before* the first engine frame leaves `engine_run_id` NULL → no container handle → the platform cannot label-sweep/kill it (the engine does not tag containers with the platform run_id and is LOCKED, INV-13). Negligible budget exposure (no container spends before its first frame). **Recommended future engine hardening:** label each container with the platform run_id (or a filesystem-scan reconcile) so the platform can sweep + kill an orphan with no DB id.

### G4 — PR-push approval gate (NFR-SEC-5) never wired / cannot intercept in-container push · CRITICAL
- **Root cause:** `require_pr_push_approval` has no production caller; the agent pushes in-container, so there is no platform chokepoint without an engine pre-push hook.
- **Approach (hybrid — reclassify honestly):** wire the gate where it CAN fire (a workflow-authored pre-push pause), and **reclassify NFR-SEC-5 as a documented known-limitation**; stop the acceptance matrix asserting the push is gated in production; record the engine pre-push-hook ask. (No heavy engine surgery.)
- **Status:** ⊘ reclassified (docs) — gate fires for workflow-authored pre-push pauses; in-container push interception is an engine §11 ask; acceptance_matrix + Known-Limitations updated; compensating control = egress allowlist (G1).

### G5 — Board lifecycle never completes (no In-Review/PR-link transition) · CRITICAL
- **Root cause:** on success `_supervise` writes only the terminal status — never sets `agent:review`, never persists `runs.pr_num`, never demotes a failed run. `merged_pr_transition` is dead code.
- **Approach (platform):** on completion, resolve the PR (via `find_open_pr_for_branch`/board sync), persist `pr_num`, set `agent:review` via the write-queue (INV-11), and demote a failed run to backlog/in-progress per §5.3.1.
- **Status:** ◐ in-progress — the completion supervisor (`_supervise` → `_complete_board_lifecycle`, wired via a `LifecycleDeps` resolved at launch from the same client/write-queue/cache singletons in `runs.py`, `tick.py`, `retry_deps.py`) now: on **success** resolves the open PR for the run's branch via `find_open_pr_for_branch`, persists `runs.pr_num`, and moves the issue to `agent:review` via `set_agent_state` (replace-all `PUT` through the serialized write-queue — INV-11, never a direct/PATCH call); on **failure** demotes the issue off `agent:in-progress` (→ Backlog) per §5.3.1. Best-effort + non-blocking (a GitHub hiccup is swallowed; the run still records its terminal status) and idempotent (an already-`agent:review` issue / already-set `pr_num` skips the redundant write). Tests cover all four paths incl. the write-queue assertion + the GitHub-error best-effort path.

### G6 — Settings screen + `GET/PUT /settings` missing (v1 DoD) · MAJOR
- **Root cause:** no Settings screen/route/endpoint though §13 DoD + FR-SET-1 require it (defaults, the $25/day spend alert, switch-repo).
- **Approach (platform):** add `GET/PUT /settings` over the `settings` table + the Settings screen + nav.
- **Status:** ☑ done (PR#35).

### G7 — Live-run `⋯` run-actions menu missing (FR-04-1) · MAJOR
- **Root cause:** `LiveRun` shows only Stop; the backend `exec` endpoint exists but no UI for exec / keep-alive / view-PR / retry.
- **Approach (platform):** add the `⋯` menu to `LiveRun` wiring the existing endpoints.
- **Status:** ☑ done (PR#36).

---

## SHOULD-FIX (operability + scale + reliability)

### G8 — `DKMV_SECRET_KEY` not in compose → PAT silently breaks on restart · MAJOR (day-2 data loss)
- **Approach:** add `DKMV_SECRET_KEY` (+ the other dropped vars `HOST_MEMORY_BUDGET`/`PER_STATE_CAPS`/`DKMV_PROJECT_ROOT`/timeouts) to the compose backend env; emit a loud boot WARN when the secret key resolves to an ephemeral generated key. **Status:** ☑ done (PR#38) — warn + preflight row + compose env complete.

### G9 — Unbounded `events` table + full-scan spend; no retention · MAJOR
- **Approach:** `/stats` + dashboard spend read `run_totals` for terminal runs (fast-path) and only segment-sum active runs; add an events-retention prune (configurable horizon) in the orchestrator tick. **Status:** ☑ done (PR#37) — run_totals fast-path (== full segment-sum) + EVENTS_RETENTION_DAYS prune.

### G10 — Audit log + loop health collected but unreachable · MAJOR
- **Approach:** add an authenticated health/observability endpoint exposing the `TickGauges` snapshot (+ raise the heartbeat to INFO), and an `/audit` read endpoint (paginated, redacted). **Status:** ☑ done (PR#38) — GET /health/orchestrator + GET /audit + heartbeat→INFO.

### G11 — Retry duplicate-PR guard fails-open + `fire_due_retries` drops a transient retry · MAJOR
- **Approach:** treat an errored `find_open_pr_for_branch` + `NULL pr_num` as "unknown → do not duplicate" (defer the retry, don't re-dispatch); only clear `due_at` on an intentional PR-skip/successful launch, not a transient failure. **Status:** ☑ done (PR#34) — tri-state detection (fail-closed) + DEFER re-arms due_at.

### G12 — Per-tick full-board scan (no queued predicate/index) · MAJOR
- **Approach:** index/predicate the candidate read so the tick doesn't read + JSON-parse the whole board every cycle. **Status:** ☑ done (PR#37) — indexed issues.agent_state column.

### G13 — Segment-sum CTE duplicated ~6× · MAJOR (maintenance trap)
- **Approach:** extract one shared `last_per_task` SQL fragment/constant reused by all spend projections + the Python meter. **Status:** ☑ done (PR#37) — app/db/spend_sql.py canonical CTE.

### G14 — Frontend ships only the Vite dev server · MAJOR (deploy hardening)
- **Approach:** add a hardened multi-stage static build (`vite build` → a static server) as the production `Dockerfile.frontend` path; keep dev-server for local dev. **Status:** ☑ done (PR pending) — multi-stage nginx static build mirroring the dev proxy; live-validated runbook.

### G15 — Single-repo orchestration ceiling undocumented · MINOR
- **Approach:** document the one-repo orchestration limit explicitly. **Status:** ☑ done — acceptance_matrix Known-Limitations + README scope note.

---

## DOCS
### G16 — Update docs to the real posture + finalize this tracker · (rolls up with each fix)
- README/acceptance_matrix/setup reflect: egress now enforced (G1), push-gate reclassified (G4), the lifecycle (G5), the single-repo ceiling (G15), the new /audit + /health/orchestrator endpoints (G10), Settings (G6), retention (G9). **Status:** ☑ done — acceptance_matrix updated; README scope note.

---

*Execution: implementer → evaluator → fix → gate → squash-merge to `platform`, in severity-ordered waves. Final unbiased evaluation at the end.*
