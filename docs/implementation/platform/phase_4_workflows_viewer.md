# Phase 4 — Workflows Viewer (read-only)

> **Phase brief** for the DKMV Platform. Source of truth is the PRD (`docs/design_docs/platform/PRD_dkmv_platform_v1.md`); shared rules are in `docs/implementation/platform/_conventions.md` (INV-1..15). This brief is **locked** during implementation (`lock-prd.sh`). Read the PRD §citations inline — do not implement from this brief alone where it points at the PRD.

**PRD version:** v1.1
**PRD milestone:** M4 (Workflows viewer, Screen 07, read-only)
**Features:** F12 (Workflows Viewer — read-only)
**User stories:** US-26 (Browse workflows)
**Tasks:** T106–T110 (`tasks.md`)
**Timing:** Weeks 13–14
**ADRs:** ADR-P010 (Workflows screen read-only in v1; full authoring → v1.1), ADR-P006 (consume `EmbeddedRuntime` in-process; engine is locked)

---

## 1. Phase goal

Ship the **read-only Workflows viewer** (Screen 07) and the read endpoints behind it. After Phase 4 a solo dev can open **Workflows** in the nav and browse every built-in + registered component (`plan/dev/qa/docs/ship` + any custom one authored on disk), see each one's **pipeline summary** (ordered stages, per-stage budget, pause points, est. total — e.g. `qa` = 3 stages / 1 pause / $2.00), and read its **"compiles to YAML" view** (`component.yaml` + task files). Editing is **disabled** with a *"Workflow authoring coming in v1.1 — edit the YAML directly for now"* note. A custom component authored on disk + `ComponentRegistry.register` **appears and is runnable**.

This phase is intentionally narrow: it is a viewer over the engine's introspection surface. The load-bearing commitments:

- The viewer is **READ-ONLY**. Only `GET /workflows` and `GET /workflows/{id}` exist; **no `POST/PUT /workflows` write endpoint is built in v1** (ADR-P010, N7). Authoring (form→YAML builder, pause-question/options sub-builder, for-each UX) is **deferred to v1.1**.
- All component data comes from the engine's introspection API — `list_components()` / `inspect_component()` / `preview_execution_plan()` — consumed **in-process** via the Phase-0 `RunService` (INV-13, ADR-P006). The platform never shells the `dkmv` CLI and never modifies `dkmv/`.
- The UI is built to the design prototype's **Screen F** (`dkmv_dashboard_design_prompt.md` §6) — the read-only subset only (pipeline summary rail + the read-only YAML peek) — using **design tokens only** + icon+label state (INV-14).

**Sequencing note (cross-phase pull — build 4.1 early):** slice **4.1-workflows-api** (`GET /workflows`, T106) is also a dependency of **Phase 2's run-panel** workflow picker (T062 depends on T106 — `tasks.md` cross-phase note; the run panel needs the workflow list to render the workflow cards with stages/pauses/est). T106 only needs Phase 0's `RunService` (T014), so **build 4.1 during Phase 0/early** even though the rest of Phase 4's UI (4.2) follows Phase 1. The Phase-4 *viewer UI* still lands here in Weeks 13–14; only the API slice is pulled forward.

---

## 2. Prerequisites (must be green before starting)

Phase 4 depends on **Phase 0** (engine introspection via `RunService`) and **Phase 1** (app shell/chrome). Do not begin a slice until its prerequisites exist and pass:

- **`RunService` over `EmbeddedRuntime`** (Phase 0, T014 / slice `0.2-runservice`) — constructed from `RuntimeConfig` with a platform-owned `output_dir`, consumed **in-process** (no CLI; INV-13, ADR-P006). 4.1 calls the engine's `list_components`/`inspect_component`/`preview_execution_plan`/`validate_component` through this service. **This is the only prerequisite 4.1 needs** (which is why 4.1 is pulled forward — see §1).
- **App access-control middleware** (Phase 0, T011/T016 / slice `0.2-runservice`) — `127.0.0.1` bind + local token + `Host`/`Origin` validation + CSRF. The new `GET /workflows` routes inherit this (INV-1); **do not** add an unauthenticated route.
- **API error-envelope / §8.9 conventions** (Phase 0) — `GET /workflows/{id}` for an unknown id returns `404 { "error": { "code": "workflow_not_found" } }`.
- **App shell + chrome + nav** (Phase 1, T049/T050 / slices `1.4-connect-shell`, `1.5-board`) — the router, the **Workflows** nav entry in the sidebar, the ported design tokens (`styles/tokens.css`), and the shared `StateBadge`/chip components. 4.2 mounts the Workflows screen on this shell (T107 depends on T049).
- **Run launch path** (Phase 2, T066 / `POST /runs`) — required **only** for the 4.2 "registered custom component is runnable" integration test (T110 depends on T066). The viewer itself does not launch runs; the test asserts a registered on-disk component can be dispatched through the normal launch path.

If any prerequisite is missing, stop and finish it first (per `CLAUDE.md` phase discipline). 4.1 can proceed as soon as Phase 0's `RunService` exists; 4.2 needs Phase 1's shell (and T110 needs Phase 2's launch).

---

## 3. Scope

### IN scope (this phase)

- **Read endpoints (4.1):** `GET /workflows` (list) + `GET /workflows/{id}` (detail), backed by the engine's `list_components()` / `inspect_component()` / `preview_execution_plan()`, consumed in-process via `RunService`. Each list/detail entry returns the **pipeline summary** (ordered stages, per-stage budget, pause points, est. total) and the **`component.yaml` + task YAML text** for the read-only view (F12 / §5.8 FR-07-1v, §6.2).
- **Viewer UI (4.2):** the Workflows list (built-in + registered components); a **pipeline-summary** component (stages / pauses / budget / est — e.g. `qa` = 3 stages / 1 pause / $2.00); a read-only **"compiles to YAML"** view of `component.yaml` + task files; editing **disabled** with the *"Workflow authoring coming in v1.1 — edit the YAML directly for now"* note; built to **Screen F** (`dkmv_dashboard_design_prompt.md` §6, read-only subset) with tokens-only + icon+label state (F12 / §5.8 FR-07-1v, §7).
- **Registered-component runnability test (4.2 / T110):** a component authored on disk + `ComponentRegistry.register` appears in the viewer **and** is runnable through the normal Phase-2 launch path (integration test).

### OUT of scope (explicitly deferred — N7, ADR-P010)

- **Full form→YAML workflow authoring** (the Screen F **workflow editor**: name/description/defaults/component-inputs/agent-instructions + the drag-reorderable task list) → **v1.1** (FR-07-1, N7). Build the read-only viewer only.
- **The pause-question / options builder** (authoring the HITL decision card: question text, options `label`+`description`, `default`) → **v1.1** (FR-07-3, N7).
- **The for-each / iteration authoring UX** and the per-task IO editor (Inputs/Outputs/commit-push/per-task overrides) → **v1.1** (FR-07-3, N7).
- **Templates** ("Start from plan/dev/qa/docs/blank") and **"Test run on an issue"** from an *edited* component → **v1.1** (FR-07-4/6).
- **Write endpoints.** Do **not** build `POST /workflows` or `PUT /workflows` (FR-07-5 is the v1.1 target). The viewer never writes `component.yaml`/task files, never calls `ComponentRegistry.register` from the API, and never calls `validate_component` to *save* (read-only inspection only). **No write route may exist** (see AC-2 / SECURITY_CHECKS).
- **Engine changes** (`dkmv/`) — consume the introspection API as-is; any engine need is a PRD §11 engine ask, not a Phase-4 edit (INV-13, ADR-P006).

---

## 4. Slices

Slice IDs are `4.k-name`. Each maps to F12 and a PRD §. "Files" lists the primary edit surface used by the wave plan (no two same-wave slices share a file).

### 4.1 — `4.1-workflows-api` (F12 / §5.8 FR-07-1v, §6.2)

**What:** `GET /workflows` + `GET /workflows/{id}`, read-only, backed by engine introspection. **Build this early** — it also unblocks Phase 2's run-panel workflow picker (T062).

- `GET /workflows` lists **built-in + registered** components via the engine's **`list_components()`** (so on-disk + `ComponentRegistry.register`'d custom components appear). For each, return the **pipeline summary**: ordered stages (from the component's task chain), per-stage budget, **pause points** (which task pauses after), and the **est. total** budget — derived from **`inspect_component()`** + **`preview_execution_plan()`** (the plan gives the executed stage ordering incl. for-each expansion). The `qa` summary must read **3 stages / 1 pause / $2.00** (§5.8 FR-07-1v authoritative example; the per-stage $0.80/$0.80/$0.40 split is illustrative — only the $2.00 total is authoritative, §7.2 FR-07-2).
- `GET /workflows/{id}` returns the same summary **plus** the **`component.yaml` + task YAML text** for the read-only "compiles to YAML" view. Unknown id → `404 { "error": { "code": "workflow_not_found" } }` (§8.9 envelope).
- Both endpoints are consumed **in-process via `RunService`** (INV-13, ADR-P006); the backend **never shells the `dkmv` CLI** and **never modifies `dkmv/`**. Introspection is **read-only** — no `validate_component`-to-save, no `register`, no file writes.
- **No write endpoint.** `POST /workflows` / `PUT /workflows` do **not** exist (ADR-P010, N7; AC-2).
- The routes inherit the Phase-0 app access-control middleware (loopback + token + Host/Origin + CSRF; INV-1) — no unauthenticated route.
- **Files:** `platform/backend/app/workflows/service.py` (introspection adapter over `RunService`), `platform/backend/app/api/workflows.py` (the two GET routes).
- **Tasks:** T106. (Pulled forward — also a dependency of T062.)

### 4.2 — `4.2-workflows-ui` (F12 / §5.8 FR-07-1v, §7)

**What:** the read-only Workflows screen built to Screen F (read-only subset).

- **Workflows list:** render every component from `GET /workflows` — **built-in** (`plan/dev/qa/docs/ship`, §7.2) **and registered** custom ones — as selectable rows/cards showing emoji, name, purpose, and a compact stage chain (FR-07-1v; Screen F level-1 list). A **registered on-disk custom component appears** in this list (verified by T110).
- **Pipeline-summary component** (Screen F summary rail, FR-07-2): for the selected component, show ordered stages with per-stage budget, the total **Stages** count, **Pause points** count, and **Est. total budget**. Authoritative `qa` rendering: **3 stages (Evaluate → Fix → Re-evaluate), 1 pause (after Evaluate), $2.00 total**.
- **Read-only "compiles to YAML" view** (FR-07-1v, Screen F's "this compiles to YAML" peek): render `component.yaml` + the task `*.yaml` text read-only (syntax-highlighted/monospace). **Editing is disabled.**
- **Authoring-deferred note:** a visible, verbatim note **"Workflow authoring coming in v1.1 — edit the YAML directly for now"** (FR-07-1v, ADR-P010). No editor, no save button, no "new workflow" CTA.
- **Runnable check (T110):** an integration test authors a component on disk, registers it via `ComponentRegistry.register`, asserts it appears in `GET /workflows`, and asserts it is **runnable** through the Phase-2 launch path (`POST /runs`).
- Built with **design tokens only** (no hardcoded hex outside `tokens.css`; INV-14), icon+label state, AA contrast — see DESIGN_FIDELITY.
- **Files:** `platform/frontend/src/screens/Workflows.tsx`, `platform/frontend/src/components/PipelineSummary.tsx`, `platform/frontend/src/components/YamlView.tsx`, `platform/frontend/src/api/workflows.ts`; backend test `platform/backend/tests/test_workflows_runnable.py` (T110 integration).
- **Tasks:** T107, T108 [P], T109 [P], T110.

---

## 5. Wave plan

Two slices, strictly ordered; no two same-wave slices edit the same file.

| Wave | Slices | Rationale / dependency |
|---|---|---|
| **W1** | `4.1-workflows-api` | **First.** Needs only Phase-0 `RunService` (T014). Establishes the read endpoints the viewer consumes — **and** unblocks Phase 2's run-panel workflow picker (T062), so it is pulled forward and built early. Backend-only (`app/workflows/`, `app/api/workflows.py`). |
| **W2** | `4.2-workflows-ui` | After 4.1 (consumes `GET /workflows` + `GET /workflows/{id}`) **and** Phase 1's shell (T049 nav/router/tokens). T110's runnable test additionally needs Phase 2's `POST /runs` (T066). Frontend (`screens/Workflows`, `components/PipelineSummary`, `components/YamlView`, `api/workflows.ts`) + one backend integration test — disjoint from 4.1's files. |

Within 4.2, T108 and T109 are `[P]` (the pipeline-summary and YAML-view components are independent files mounted by T107's screen). Critical path: **4.1 → 4.2**. No same-wave file collisions (4.1 is backend API; 4.2 is frontend + a separate backend test module).

---

## 6. Acceptance criteria (greppable, with PRD §citations)

Each criterion is verifiable by a grep/command + a test. Backend greps run under `platform/backend/`, frontend under `platform/frontend/src/`.

### F12 — Workflows Viewer (read-only)

- **AC-1 (4.1, §5.8 FR-07-1v / §6.2).** `GET /workflows` + `GET /workflows/{id}` exist and are backed by **engine introspection**. `grep -rni "list_components\|inspect_component\|preview_execution_plan" platform/backend/app/workflows` is **non-empty**; `grep -rn "/workflows" platform/backend/app/api/workflows.py` shows the two **GET** routes. A test asserts `GET /workflows` lists the five built-ins and `GET /workflows/{id}` returns the pipeline summary + YAML text; an unknown id returns `404 { "error": { "code": "workflow_not_found" } }` (§8.9).
- **AC-2 (4.1, ADR-P010 / N7 — binding, READ-ONLY).** **No write endpoint exists in v1.** `grep -rn "POST.*/workflows\|PUT.*/workflows" platform/backend/app` is **empty**. The service never writes `component.yaml`/task files and never calls `ComponentRegistry.register` or `validate_component`-to-save from the API path: `grep -rni "register\|validate_component\|open(.*component.yaml\|\.write" platform/backend/app/workflows` shows no write/register call (read-only introspection only). A test asserts `POST /workflows` and `PUT /workflows` return `404`/`405` (route absent).
- **AC-3 (4.1, §6.2 / N6 — INV-13, binding).** Introspection is consumed **in-process via `RunService`**; the backend never shells the CLI and never edits `dkmv/`. `grep -rnE "subprocess.*dkmv|os\.system.*dkmv|Popen.*\bdkmv\b" platform/backend` is **empty**; `grep -rn "RunService\|run_service" platform/backend/app/workflows` non-empty; `git diff --name-only main..HEAD -- dkmv/` is **empty**.
- **AC-4 (4.1, §5.8 FR-07-1v / §7.2 FR-07-2).** The summary returned by the API carries ordered stages, per-stage budget, **pause points**, and **est. total**, plus the `component.yaml` + task YAML text. A test asserts the **`qa`** component returns **3 stages / 1 pause (after Evaluate) / $2.00 total** (the $2.00 `max_budget_usd` total is authoritative; the per-stage split is not asserted).
- **AC-5 (4.2, §5.8 FR-07-1v).** The Workflows screen lists **built-in + registered** components from `GET /workflows`. A render test asserts the five built-ins (`plan/dev/qa/docs/ship`) render; an integration/render asserts a registered custom component also appears (ties to AC-8).
- **AC-6 (4.2, §7.2 FR-07-2).** The pipeline-summary component renders stages / pauses / budget / est. A render test asserts the `qa` selection shows **3 stages**, **1 pause**, and a **$2.00** total.
- **AC-7 (4.2, §5.8 FR-07-1v / ADR-P010 — binding).** A read-only "compiles to YAML" view renders `component.yaml` + task text with **editing disabled** and the verbatim authoring-deferred note present: `grep -rn "Workflow authoring coming in v1.1 — edit the YAML directly for now" platform/frontend/src` is **non-empty**. A render test asserts the YAML is read-only (no editable input / save control) and the note renders.
- **AC-8 (4.2 / T110, §5.8 FR-07-1v).** A component authored on disk + `ComponentRegistry.register` **appears** in the viewer **and** is **runnable** through the Phase-2 launch path. An integration test (`test_workflows_runnable`) registers an on-disk component, asserts it is returned by `GET /workflows`, and asserts `POST /runs` against it dispatches (engine `start(...)` invoked / claim-lock row created).
- **AC-9 (4.2, §7 / NFR-A11Y-1 — INV-14).** No hardcoded hex outside the tokens file; state is conveyed by **icon + label**, not color alone; AA contrast. `grep -rnE "#[0-9a-fA-F]{3,8}\b" platform/frontend/src --include=*.tsx --include=*.ts` excluding `styles/tokens.css` is **empty** (see DESIGN_FIDELITY).

---

## 7. SECURITY_CHECKS

**SECURITY_CHECKS = n/a — read-only viewer over local engine introspection; no new external surface.** Phase 4 adds **only two `GET` routes** that read component definitions already present on the local disk via the in-process engine. It introduces **no write path, no new external/network surface, no secret handling, no sandbox/run dispatch** of its own. The run-injection / egress / secret INVs (INV-3/4) are exercised in Phase 0/2/3 and are not re-verified here. Two invariants still apply and **must hold at phase exit**:

- **INV-1 — App access control still applies to the new GET routes (NFR-SEC-2).** `GET /workflows` and `GET /workflows/{id}` are behind the Phase-0 loopback + token + `Host`/`Origin` + CSRF middleware — they are **not** unauthenticated. `grep -rn "127.0.0.1\|Origin\|Host\|csrf" platform/backend/app/security/` non-empty; a test sends a request to `/workflows` with a foreign `Host` and gets **403**, and missing the token gets **401**. No Phase-4 route opts out.
- **INV-13 — Consume the engine in-process; engine is locked (§6.2, N6).** The viewer reads components via `RunService`/`EmbeddedRuntime`, never by shelling the CLI and never by editing `dkmv/`. `grep -rnE "subprocess.*dkmv|os\.system.*dkmv" platform/backend` empty; `git diff --name-only main..HEAD -- dkmv/` empty (AC-3).
- **Read-only guarantee (ADR-P010).** Because there is no write endpoint, there is no untrusted-input write surface to harden. `grep -rn "POST.*/workflows\|PUT.*/workflows" platform/backend/app` **empty** (AC-2) is itself the security check that this phase adds no state-changing surface.

> Phase 4 must not **regress** the out-of-phase security INVs (do not add a workflow route that bypasses the access-control middleware, writes to disk, or shells the engine).

## 8. DESIGN_FIDELITY (UI slice 4.2)

- **No hardcoded hex in `platform/frontend/src`** outside the tokens file (INV-14). `grep -rnE "#[0-9a-fA-F]{3,8}\b" platform/frontend/src --include=*.tsx --include=*.ts` excluding `styles/tokens.css` is **empty**. All color comes from the CSS variables ported from `styles.css` (accent indigo `#7b7bf5`; the §7.3 state palette `--st-*`; the §7.4 `LABELS` map) — these literals live **only** in `tokens.css`.
- **Built to Screen F (read-only subset).** The screen matches `dkmv_dashboard_design_prompt.md` §6 Screen F's **level-1 list** + **pipeline summary rail** + the **read-only "this compiles to YAML" peek** — and **omits** the form editor, task-editor drawer, templates, and "Test run" authoring affordances (those are v1.1; OUT of scope). The "qa" component is the reference render (3 tasks, Evaluate pauses), matching the prototype's loaded-qa state but **read-only**.
- **Pipeline summary** uses the shared state/badge vocabulary (icon + label, never color alone; §7.3) for stage status and the pause marker; per-stage budget + est. total use the mono numeric style (`JetBrains Mono`, `tnum`, §7.5). The $2.00 `qa` total is authoritative; per-stage splits are illustrative.
- **YAML view** is monospace, read-only, progressive-disclosure styling consistent with the prototype's "compiles to YAML" peek; no editable inputs, no save control.
- **Authoring-deferred note** renders as warm, plain microcopy (P4) — verbatim "Workflow authoring coming in v1.1 — edit the YAML directly for now" (AC-7) — not an error/blocker styling.
- **Type / radii / motion** per §7.5, sourced from the ported tokens (not re-declared). Dark+indigo default theme inherited from the Phase-1 shell.

## 9. Independent verification commands

The evaluator runs these; all must pass (exit 0 / empty where noted).

```bash
# ---- Backend: lint, type, test ----
cd platform/backend && ruff check . && mypy app && pytest -q

# ---- Frontend: type, test ----
cd platform/frontend && npx tsc --noEmit && npx vitest run

# ---- READ-ONLY: no workflows write endpoint exists in v1 (ADR-P010, N7) ----
grep -rn "POST.*/workflows\|PUT.*/workflows" platform/backend/app    # expect: empty

# ---- Engine introspection is the data source (§5.8/§6.2) ----
grep -rni "list_components\|inspect_component\|preview_execution_plan" platform/backend/app/workflows   # expect: non-empty

# ---- INV-13: consume engine in-process; never shell the CLI; engine untouched ----
grep -rnE "subprocess.*dkmv|os\.system.*dkmv|Popen.*\bdkmv\b" platform/backend   # expect: empty
git diff --name-only main..HEAD -- dkmv/                              # expect: empty

# ---- The viewer never writes/registers from the API path (read-only) ----
grep -rni "register\|\.write\|open(.*component.yaml" platform/backend/app/workflows   # expect: empty (read-only)

# ---- AC-7: the authoring-deferred note is present (verbatim) ----
grep -rn "Workflow authoring coming in v1.1 — edit the YAML directly for now" platform/frontend/src   # expect: non-empty

# ---- INV-14: no hardcoded hex outside the tokens file ----
grep -rnE "#[0-9a-fA-F]{3,8}\b" platform/frontend/src --include=*.tsx --include=*.ts \
  | grep -v "styles/tokens.css"                                       # expect: empty
bash scripts/hooks/post-edit-no-hardcoded-hex.sh                      # convention hook, expect: empty/pass

# ---- INV-1: the new GET routes are behind app access control ----
grep -rn "127.0.0.1\|Origin\|Host\|csrf" platform/backend/app/security/   # expect: non-empty

# ---- AC-8: a registered on-disk custom component appears + is runnable ----
cd platform/backend && pytest -q -k "workflows_runnable"             # expect: pass
```

## 10. Test plan

**Backend (pytest):**
- `test_workflows_api`: `GET /workflows` lists the five built-ins via `list_components`; `GET /workflows/{id}` returns the pipeline summary (stages / per-stage budget / pause points / est. total) + the `component.yaml` + task YAML text via `inspect_component`/`preview_execution_plan`; unknown id → `404 workflow_not_found` (AC-1).
- `test_workflows_qa_summary`: the `qa` component reports **3 stages / 1 pause (after Evaluate) / $2.00 total** (AC-4).
- `test_workflows_readonly`: `POST /workflows` and `PUT /workflows` are absent (`404`/`405`); the service performs no file write / no `register` / no `validate`-to-save (AC-2, ADR-P010).
- `test_workflows_in_process`: the service path uses `RunService`/`EmbeddedRuntime` (no `subprocess`/CLI); engine tree untouched (AC-3, INV-13).
- `test_workflows_access_control` (re-asserted from Phase 0): `GET /workflows` with a foreign `Host` → 403; missing token → 401 (SECURITY_CHECKS, INV-1).
- `test_workflows_runnable` (integration, T110): author a component on disk → `ComponentRegistry.register` → assert it appears in `GET /workflows` → assert `POST /runs` against it dispatches through the normal launch path (AC-8).

**Frontend (vitest + render):**
- `Workflows.test`: the screen lists built-in + registered components from `GET /workflows`; selecting one renders its summary + YAML (AC-5).
- `PipelineSummary.test`: the `qa` selection renders **3 stages**, **1 pause**, **$2.00** total; stage status uses icon+label not color alone (AC-6, AC-9).
- `YamlView.test`: the YAML view is read-only (no editable input / save control) and the verbatim **"Workflow authoring coming in v1.1 — edit the YAML directly for now"** note renders (AC-7).
- A repo-wide no-hardcoded-hex assertion mirrors the INV-14 grep (AC-9).

**Phase exit gate (per `CLAUDE.md`):** all AC checked off, every command in §9 passes (note the **empty** `POST/PUT /workflows` grep and the **non-empty** introspection grep), the §10 suites are green, and `ruff`/`mypy`/`tsc`/`vitest` are clean. Then update `progress.md` and proceed to Phase 5.

---

**PRD version:** v1.1 · **Phase:** 4 (M4) · **Feature:** F12 · **User story:** US-26 · **Tasks:** T106–T110 · **ADRs:** ADR-P010, ADR-P006 · Generated against `_conventions.md` INV-1..15.
