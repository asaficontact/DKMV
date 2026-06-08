# Phase 1 — GitHub Integration + Connect + Board

> **Phase brief** for the DKMV Platform. Source of truth is the PRD (`docs/design_docs/platform/PRD_dkmv_platform_v1.md`); shared rules are in `docs/implementation/platform/_conventions.md` (INV-1..15). This brief is **locked** during implementation (`lock-prd.sh`). Read the PRD §citations inline — do not implement from this brief alone where it points at the PRD.

**PRD version:** v1.1
**PRD milestone:** M1 (GitHub integration + Connect + Board)
**Features:** F4 (GitHub Integration), F5 (Connect & Onboarding), F6 (Board & Navigation)
**User stories:** US-05, US-06, US-07, US-08 (F4); US-09 (F5); US-10, US-11 (F6)
**Tasks:** T033–T058 (`tasks.md`)
**Timing:** Weeks 3–6
**ADRs:** ADR-P004 (fine-grained PAT + poll-only + labels-as-control-plane; App/webhooks deferred)

---

## 1. Phase goal

Stand up the GitHub control plane and the first two productionized screens. After Phase 1 a solo dev can: paste a fine-grained PAT, pick one repo, see its issues imported onto a six-column Kanban board keyed by an `agent:*` label state machine, and drag issues between Backlog and Queued — with the global app chrome (sidebar, top bar, theme) in place. **Nothing runs yet** — run launch/streaming is Phase 2.

The load-bearing technical commitments of this phase:

- A single `GitHubClient` interface (so the deferred GitHub App is an additive backend, ADR-P004) with fine-grained PAT auth and an **effective-write-permission** preflight.
- A paginated **GraphQL** board read (issues + labels + linked PRs) with `since`/cursor + a bounded Done window.
- The `set_agent_state()` label primitive over GitHub `PUT .../issues/{n}/labels` **replace-all** (single-occupancy invariant), with the **authority rule** (active-run DB row > label) and **state-machine completeness**.
- A **single serialized, token-bucket-paced write-queue** for all mutating GitHub calls (80/min secondary-limit + `Retry-After`).
- The Connect flow and Board built to the design prototype (`connect.jsx`, `styles.css` tokens, `dkmv_dashboard_design_prompt.md` §5/§6) with **design tokens only** + icon+label state badges.

---

## 2. Prerequisites (from Phase 0 — must be green before starting)

Phase 1 consumes the Phase 0 (M0) foundation. Do not begin a slice until its prerequisites below exist and pass:

- **`RunService`** wrapper over `EmbeddedRuntime` (T014) and **`GET /preflight`** via `get_capabilities()` (T015) — Connect's preflight box (1.4) and the standing checks reuse this.
- **Persistence + repository layer** (T018–T024): SQLite WAL pragmas + single serialized writer task, Alembic migrations for `projects/issues/...`, the repository seam, and the idempotency-key claim helper. The issue cache (1.2) writes through the repository, never raw SQL.
- **`SecretStore`** (encrypted, file-mount, repo-scoped ≤1 hr token, T030) — the PAT is stored here (1.1), never in plain env or the DB in cleartext.
- **App-shell config / app access-control middleware** (T011, T016): `127.0.0.1` bind + local token + `Host`/`Origin` validation + CSRF on state-changing POSTs. Every Phase 1 endpoint inherits this; **do not** add an unauthenticated route.
- **Vite frontend skeleton** (T012): router + design-token port + theme + EventSource client primitive — 1.4 finalizes the shell on top of this.

If any prerequisite is missing, stop and finish Phase 0 first (per `CLAUDE.md` phase discipline).

---

## 3. Scope

### IN scope (this phase)

- `GitHubClient` interface + fine-grained PAT auth + secret storage; `GET /repos`; effective-write-permission preflight (F4 / §8.1).
- Paginated GraphQL board read (issues + labels + linked PRs) + `since`/cursor + Done window; `POST /projects/{repo}/sync`; `GET /repos/{repo}/issues` with derived `state` per §5.3.1; create the four `agent:*` labels on connect (F4 / §8.1, §5.3.1).
- `set_agent_state(repo, num, target|none)` via `PUT .../labels` replace-all (single-occupancy + precedence); `POST /issues/{num}/agent-state`; authority rule; state-machine completeness (In Review→Done on merge, closed/reopened, failed-run demotion); serialized token-bucket write-queue; secondary-limit + `Retry-After` handling; GraphQL hash-cache (F4 / §8.1, §5.3.1).
- Connect flow UI (`disconnected→connecting→picker→syncing`, build to `connect.jsx`) + `POST /connect/github` + repo picker + "What we'll do" card + preflight box; app-shell finalize (router, ported tokens, dark/indigo default, EventSource client) (F5 / §5.2, §7, FR-01).
- Global chrome (sidebar + top bar) + board (six columns, issue cards, aggregate strip, filter bar, Populated/Empty/Syncing states, drag Backlog↔Queued) + shared state-badge palette (F6 / §5.1, §5.3, §5.3.1).

### OUT of scope (explicitly deferred)

- **Launching runs / live run streaming / SSE / HITL** → **Phase 2** (F7–F9). The issue card "⋯ → Run" and "+ Run an issue" CTA route to the issue-detail/run screen which is Phase 2; in Phase 1 they may navigate to a placeholder or be disabled, but they do **not** dispatch.
- **GitHub App + webhooks** (bot identity, per-install tokens, HMAC-verified delivery, echo-suppression `expected_label_events`) → **deferred / post-v1** per ADR-P004 and PRD §8.1. v1 is **PAT-first + poll-only**. Do not build a webhook receiver; the `X-Hub-Signature-256`/`X-GitHub-Delivery` machinery is not in this phase.
- **GitHub Projects v2 status** (GraphQL-only status field) → **post-v1** (N3). Labels are the v1 state machine.
- **Orchestrator tick loop / dispatch / reconcile / retry / crash recovery** → Phase 3 (F11). Phase 1 ships the label primitive and authority rule the orchestrator will later call, but **not** the loop that calls them on a cadence. Board/chip "live status" is **poll-driven** (FR-NAV-2 last-synced), not an orchestrator tick.
- **Issue detail screen, run panel, comments-as-launch-context** → Phase 2 (`GET /issues/{num}` detail is T059, Phase 2). Phase 1's `GET /repos/{repo}/issues` returns the board list shape only.
- **Runs history, analytics, `/stats`, retry queue, spend chart** → Phase 3 (F10). The board aggregate strip's "spent today" is computed from the Phase 0 `spend` projection (Codex-excluded), not from a `/stats` endpoint.
- **Workflow chips** appear on issue cards when an issue already carries a `workflow_id` in the DB cache, but **workflow assignment UI** is Phase 2.

---

## 4. Slices

Slice IDs are `1.k-name`. Each maps to a feature and PRD §. "Files" lists the primary edit surface used by the wave plan (no two same-wave slices share a file).

### 1.1 — `1.1-github-client` (F4 / §8.1)

**What:** `GitHubClient` interface + fine-grained PAT auth + secret storage; `GET /repos`; effective-write-permission preflight on the selected repo.

- Define `GitHubClient` as an interface (Protocol/ABC) with a `PatGitHubClient` implementation; the deferred App backend must slot behind the same interface (ADR-P004, §8.1). Auth is a fine-grained PAT read from / written to the Phase-0 `SecretStore` (never plain env, never the DB in cleartext; INV-4).
- `GET /repos` lists the token's accessible repos in the `Repo` shape `{org, name, lang, langColor, private, updated, issues, stars?, desc?}` (PRD §6.1, `data.jsx REPOS`).
- **Effective-write-permission preflight** on the *selected* repo (not mere token presence): probe that the token can actually write (`issues:write` / `contents:write` / `pull_requests:write`) so a read-only token fails fast at connect, not late at PR time (§8.1, §5.2 FR-01-6). Surfaced via `GET /preflight` (reuse Phase-0 `get_capabilities()` for the standing GitHub/Anthropic/Docker rows; add the write-permission check for the chosen repo).
- **Files:** `platform/backend/app/github/client.py` (interface), `platform/backend/app/github/pat_client.py`, `platform/backend/app/api/repos.py`.
- **Tasks:** T033, T034, T035.

### 1.2 — `1.2-issue-sync` (F4 / §8.1, §5.3.1)

**What:** paginated GraphQL board read + import; derived board state; `agent:*` label creation.

- One **GraphQL** board read per project: issues + state + labels + linked PRs, paginated `first:100` + cursors, persisting a `since`/cursor for incremental polls, bounding **Done** to a window (closed in last N days or last 50) (§8.1). GraphQL has no ETag — **cache results yourself keyed by a query+variables hash** (the hash-cache; shared with 1.3's rate-limit work).
- `POST /projects/{repo}/sync` imports issues into the DB `issues` cache (repository layer) (T037).
- `GET /repos/{repo}/issues` returns the board list with **`state` derived per §5.3.1** (label→column) and the authority rule applied (§8.1): for an issue with an active run the DB `runs` row wins; otherwise the `agent:*` label governs. Precedence when multiple `agent:*` labels are seen: `in-progress > paused > review > queued`.
- **Create the four `agent:*` labels on connect** if absent — `agent:queued | agent:in-progress | agent:paused | agent:review` with defined colors (§8.1).
- **Files:** `platform/backend/app/github/graphql.py`, `platform/backend/app/github/sync.py`, `platform/backend/app/github/labels.py` (label-create only; mutation primitive lives in 1.3), `platform/backend/app/api/issues.py`.
- **Tasks:** T036, T037, T038, T039.

### 1.3 — `1.3-label-statemachine` (F4 / §8.1, §5.3.1)

**What:** the label state-machine primitive + write-queue + rate-limit handling.

- `set_agent_state(repo, num, target | none)` implemented with GitHub **`PUT /repos/{o}/{r}/issues/{num}/labels`** (replace-all over the `agent:*` set, preserving non-agent labels) — **the fictional `PATCH .../label` MUST NOT appear anywhere** (INV-11, §8.1). The replace-all `PUT` enforces the **single-occupancy invariant** and is idempotent.
- `POST /issues/{num}/agent-state` (body `{target: queued|none}`) calls `set_agent_state` for the Backlog↔Queued drag (§8.1 endpoints, FR-02-3).
- **Authority rule** wired into derivation: active-run DB row > label (§8.1); label→column derivation completes here against 1.2's read.
- **State-machine completeness** (§8.1): In Review→Done on PR merge (`pull_request.closed merged:true` in webhook mode, or the GraphQL PR `merged` field in poll mode + issue↔PR linkage via `runs.pr_num` / "Closes #N"); closed→Done (and cancel a live run — the cancel call is a no-op stub in Phase 1 since runs don't exist yet, but the demotion/label logic is built and unit-tested); reopened→out of Done; **failed-run demotion** off `agent:in-progress` (to `agent:queued` if it will auto-retry, else strip to Backlog) so the board never strands a failed issue in In Progress.
- **Serialized token-bucket write-queue:** route **all** mutating GitHub calls (labels now; branches/PRs/comments later) through a **single serialized write-queue with token-bucket pacing** (§8.1). Handle the **content-creation secondary limit (~80/min, 500/hr)** distinctly from primary limits: it is not reflected in `X-RateLimit-Remaining` and returns 403 + `Retry-After` — honor `Retry-After`, capped backoff. Surface `X-RateLimit-*` + secondary-limit state for the later UI row (FR-06-2, built in Phase 3; expose the accounting now).
- **GraphQL hash-cache** (the cache from 1.2) is consulted for reads to spend fewer points.
- **Files:** `platform/backend/app/github/state_machine.py` (`set_agent_state`, derivation, completeness), `platform/backend/app/github/write_queue.py`, `platform/backend/app/api/agent_state.py`.
- **Tasks:** T040, T041, T042, T043, T044.

### 1.4 — `1.4-connect-shell` (F5 / §5.2, §7, FR-01)

**What:** the Connect flow + the productionized app shell.

- Connect flow local state machine `disconnected → connecting → picker → syncing` built to **`connect.jsx`** (top Segmented tabs Welcome / Pick repo / Syncing) (FR-01-1).
- **Disconnected:** hero copy verbatim — "Turn your GitHub issues into work that runs itself." + reassurance line "Read-only on your code. We only read issues and add `agent:*` labels. Nothing runs until you say so." (FR-01-2).
- **PAT entry screen** listing the **four** permissions to grant (`issues:write`, `pull_requests:write`, `contents:write`, `metadata:read`) scoped to the one repo (§8.1) + `POST /connect/github`. On success → picker (FR-01-3).
- **Picker:** searchable repo list from `GET /repos`; selecting a repo shows the **"What we'll do"** card (Read issues / Add `agent:*` labels / Nothing runs until Run) + the **Preflight** box from `GET /preflight`; primary **Open project** → syncing → `POST /projects/{repo}/sync` (FR-01-4, FR-01-5, FR-01-6). Build to `connect.jsx`'s `ConfirmRow` + preflight rows.
- **App-shell finalize:** Vite router, **design tokens ported from `styles.css`** (no hardcoded hex; INV-14), dark/indigo default theme (`data-mode="dark" data-theme="indigo"`, persisted to `localStorage` `dkmv-mode`/`dkmv-skin`; indigo accent `#7b7bf5` lives in the tokens file only), EventSource client primitive (instantiated, not yet consuming a run stream — Phase 2) (FR-NAV-3, §7.1, §7.6).
- **Files:** `platform/frontend/src/screens/Connect.tsx`, `platform/frontend/src/app/router.tsx`, `platform/frontend/src/app/theme.ts`, `platform/frontend/src/styles/tokens.css` (the **only** file permitted to contain hex), `platform/frontend/src/api/client.ts`, `platform/backend/app/api/connect.py`.
- **Tasks:** T045, T046, T047, T048, T049.

### 1.5 — `1.5-board` (F6 / §5.1, §5.3, §5.3.1)

**What:** global chrome + the Board (HOME).

- **Global chrome** (build to `dkmv_dashboard_design_prompt.md` §5): left sidebar with project switcher (repo + avatar), a global **"+ New run"** button, primary nav **Board / Runs / Workflows / Settings**, and a bottom **live status chip** ("2 running · $12.40 · 1 needs you", amber dot + count when paused); top bar with breadcrumb/title, a **Refresh** affordance + "last synced 12s ago" (poll, not SSE), theme toggle (dark default), GitHub avatar (FR-NAV-1, FR-NAV-2, FR-NAV-4). The chip + aggregate strip refresh via **polling**, not per-card SSE (§8.3 "Board/chip use polling").
- **Board:** render the six columns left→right (Backlog, Queued, In Progress, Needs You, In Review, Done) keyed by `agent:*` state per **§5.3.1** with horizontal scroll; each header shows a count; In Progress also shows aggregate live cost (FR-02-1).
- **Issue card:** number + title; ~2 GitHub labels (color from the `LABELS` map via tokens, §7.4); workflow chip + agent chip if assigned; a **live mini-meter** (turn count + running cost + thin progress bar with the running pulse) if running; assignee avatar; a "⋯" menu (Assign workflow, Run, Open on GitHub, Stop — Run/Stop are **disabled/placeholder** in Phase 1 per OUT scope); Needs-You cards get amber treatment + a **Review decision** button (the CTA target is Phase 2) (FR-02-2).
- **Drag Backlog↔Queued** → `POST /issues/{num}/agent-state` → `set_agent_state` replace-all, preserving single-occupancy (FR-02-3). Cards are draggable **only** between Backlog and Queued; other columns are run-driven and not user-draggable.
- **Aggregate strip** (compact, Symphony-style): "{in_progress} in progress · {needs_you} needs you · ${spent_today} spent today · {tokens_today} tokens." **"Spent today" excludes $0-cost Codex runs** from the spend figure while their tokens still count (FR-02-4, FR-06-1a, INV-8); poll-driven.
- **Filter bar** (label / workflow / agent / state) + **"+ Run an issue"** primary; **states** Populated (hero) / Empty (friendly "Create an issue on GitHub or import") / Syncing (FR-02-5, FR-02-6).
- **Shared state-badge palette component** (icon + label, never color-alone; INV-14, §7.3, `components.jsx STATE_OF`/`StateBadge`) used here and reused everywhere (board card, chip, later run header/history row).
- **Files:** `platform/frontend/src/chrome/Sidebar.tsx`, `platform/frontend/src/chrome/TopBar.tsx`, `platform/frontend/src/screens/Board.tsx`, `platform/frontend/src/components/IssueCard.tsx`, `platform/frontend/src/components/AggregateStrip.tsx`, `platform/frontend/src/components/StateBadge.tsx`, `platform/frontend/src/components/FilterBar.tsx`, `platform/backend/app/api/board.py` (aggregate counters).
- **Tasks:** T050, T051, T052, T053, T054, T055, T056, T057, T058.

---

## 5. Wave plan

No two slices in the same wave edit the same file (backend `app/github/*` and `app/api/*` are split per slice; frontend screens/components are split per slice; the only shared frontend file — `tokens.css` — is created once in Wave B and only read thereafter).

| Wave | Slices | Rationale / dependency |
|---|---|---|
| **A** | `1.1-github-client` | First. Needs Phase-0 `SecretStore` + `/preflight`. Establishes the `GitHubClient` interface everything else calls. |
| **B** | `1.4-connect-shell` | Starts after the Phase-0 shell config (T012/T016); runs **in parallel** with 1.1 (different files: frontend `screens/Connect`, `app/*`, `tokens.css` + backend `api/connect.py` vs. 1.1's `github/*`, `api/repos.py`). Creates `tokens.css`. |
| **C** | `1.2-issue-sync` | After 1.1 (needs `GitHubClient` + `GET /repos`). Adds GraphQL read, sync, issue list, label creation + the hash-cache. |
| **D** | `1.3-label-statemachine` | After 1.2 (needs the issues read + the hash-cache) — builds the write-queue and `set_agent_state`. Note the intra-phase pull: **T040 depends on T043** (write-queue before the label primitive); sequence 1.3's internal tasks T043 → T040 → T041 → T042 → T044. |
| **E** | `1.5-board` | After 1.4 (chrome/shell + tokens) **and** 1.2 (issues data) + 1.3 (`POST /issues/{num}/agent-state` for the drag). |

Critical path: A → C → D → E. 1.4 (B) runs alongside A–D and only gates E.

---

## 6. Acceptance criteria (greppable, with PRD §citations)

Each criterion is verifiable by a grep/command + a test. Backend greps run under `platform/backend/`, frontend under `platform/frontend/src/`.

### F4 — GitHub Integration

- **AC-1 (1.1, §8.1).** A single `GitHubClient` interface exists with a PAT implementation; the App is not built. `grep -rn "class GitHubClient\|Protocol" platform/backend/app/github/client.py` is non-empty; `grep -rni "webhook\|X-Hub-Signature\|X-GitHub-Delivery" platform/backend/app/github` is empty (App/webhooks are OUT). The PAT is read from `SecretStore`, not env: `grep -rn "SecretStore\|secret_store" platform/backend/app/github` non-empty.
- **AC-2 (1.1, §8.1 / §5.2 FR-01-6).** Effective-write-permission preflight: a read-only token on the selected repo returns a `preflight_blocked`/blocker, not a success. A test asserts the write-permission probe fails fast at connect.
- **AC-3 (1.2, §8.1).** The board read is **GraphQL** (not REST issue-list), paginated with cursors, persists a `since`/cursor, and bounds Done. `grep -rni "graphql\|first: *100\|endCursor\|pageInfo" platform/backend/app/github` non-empty. A test asserts incremental sync re-reads only changed issues and the Done window is bounded.
- **AC-4 (1.2, §8.1).** The four `agent:*` labels are created on connect if absent. `grep -rn "agent:queued\|agent:in-progress\|agent:paused\|agent:review" platform/backend/app/github` non-empty; a test asserts idempotent creation (no duplicate-label error on re-connect).
- **AC-5 (1.2, §5.3.1).** `GET /repos/{repo}/issues` derives `state` per the §5.3.1 table (Backlog/Queued/In Progress/Needs You/In Review/Done) and applies the authority rule (active-run DB row > label). A test feeds an issue with both an active run and a stale label and asserts the DB row wins. Multi-label precedence `in-progress > paused > review > queued` is unit-tested.
- **AC-6 (1.3, §8.1 — INV-11, binding).** All `agent:*` transitions go through `set_agent_state()` using GitHub **`PUT .../labels` replace-all**. `grep -rn "PUT.*labels\|set_agent_state" platform/backend/app/github` is **non-empty**; `grep -rni "PATCH.*/label" platform` is **empty**. A test asserts single occupancy: after `set_agent_state(..., target=queued)` on an issue that had `agent:review`, exactly one `agent:*` label remains and non-agent labels are preserved.
- **AC-7 (1.3, §8.1 — INV-11).** All mutating GitHub calls go through a **single serialized write-queue** with token-bucket pacing; a 403 + `Retry-After` (secondary limit) is honored, not retried immediately. `grep -rni "write_queue\|token.bucket\|Retry-After\|retry_after" platform/backend/app/github` non-empty; a test simulates a 403/`Retry-After` and asserts the queue waits the advertised interval and does not interleave a second mutation.
- **AC-8 (1.3, §8.1).** State-machine completeness: In Review→Done on PR merge (linkage via `runs.pr_num` / "Closes #N"); `issues.closed`→Done; `issues.reopened`→out of Done; **failed-run demotion** moves the label off `agent:in-progress` (no failed issue stranded in In Progress). Each transition has a unit test.
- **AC-9 (1.3, §8.1).** `POST /issues/{num}/agent-state` (body `{target: queued|none}`) drives the Backlog↔Queued drag through `set_agent_state`. A test asserts `target:none` strips `agent:queued` (→ Backlog) and `target:queued` sets it.

### F5 — Connect & Onboarding

- **AC-10 (1.4, FR-01-1).** The connect flow implements the `disconnected→connecting→picker→syncing` machine built to `connect.jsx`. The PAT entry screen lists the **four** permissions (`issues:write`, `pull_requests:write`, `contents:write`, `metadata:read`). `grep -rn "issues:write\|pull_requests:write\|contents:write\|metadata:read" platform/frontend/src` non-empty.
- **AC-11 (1.4, FR-01-2).** Verbatim reassurance copy "Nothing runs until you say so." is present: `grep -rn "Nothing runs until you say so" platform/frontend/src` non-empty.
- **AC-12 (1.4, FR-01-4/6).** The picker renders `GET /repos`, a "What we'll do" card, and a Preflight box from `GET /preflight`; **Open project** triggers `POST /projects/{repo}/sync`. A test/render asserts the three confirm rows + preflight rows render and "Open project" calls sync.
- **AC-13 (1.4, §7.1 FR-NAV-3 — INV-14).** The app shell defaults to `data-mode="dark" data-theme="indigo"`, persists `dkmv-mode`/`dkmv-skin` to `localStorage`, and ports tokens from `styles.css`. `grep -rn "dkmv-mode\|dkmv-skin" platform/frontend/src` non-empty; the indigo accent hex lives only in `tokens.css` (see DESIGN_FIDELITY).
- **AC-14 (1.4, NFR-SEC-2 — INV-1).** `POST /connect/github` and every Phase-1 endpoint pass through the app access-control middleware (loopback + token + Host/Origin + CSRF). A request with a foreign `Host` returns 403 in tests (see SECURITY_CHECKS).

### F6 — Board & Navigation

- **AC-15 (1.5, §5.3.1).** The board renders exactly the six columns in §5.3.1 order keyed by `agent:*` state. A render test asserts column titles/order match `data.jsx COLUMNS` (Backlog, Queued, In Progress, Needs You, In Review, Done).
- **AC-16 (1.5, FR-02-3).** Dragging a card Backlog↔Queued calls `POST /issues/{num}/agent-state`; other columns are not user-draggable. A test asserts the drag handler posts the correct `target`.
- **AC-17 (1.5, FR-02-4 / FR-06-1a — INV-8).** The aggregate strip's "spent today" **excludes $0-cost Codex runs** while counting their tokens. `grep -rni "codex" platform/frontend/src/components/AggregateStrip.tsx platform/backend/app/api/board.py` shows the exclusion; a backend test with one Claude + one Codex run asserts spend = Claude-only and tokens = both.
- **AC-18 (1.5, §5.3 FR-02-6).** Populated / Empty / Syncing board states render; Empty shows the "Create an issue on GitHub or import" copy. `grep -rn "Create an issue on GitHub" platform/frontend/src` non-empty.
- **AC-19 (1.5, §7.3 / NFR-A11Y-1 — INV-14).** The shared state badge conveys state by **icon + label**, not color alone, and is reused for board card + sidebar chip. The `StateBadge` component renders an icon element + a text label (test asserts both present).
- **AC-20 (1.5, FR-NAV-1/2, §8.3).** The sidebar live-status chip and aggregate strip refresh by **polling** (last-synced indicator), not per-card SSE. `grep -rni "EventSource" platform/frontend/src/screens/Board.tsx platform/frontend/src/chrome` is **empty** (only the single run view holds an SSE stream — Phase 2).

---

## 7. SECURITY_CHECKS

Concrete greps/tests from the applicable INVs (`_conventions.md`). All must hold at phase exit.

- **INV-1 — App access control (NFR-SEC-2).** Every Phase-1 route is behind the loopback+token+Host/Origin+CSRF middleware. `grep -rn "127.0.0.1\|Origin\|Host\|csrf" platform/backend/app/security/` non-empty; a request with a foreign `Host` returns **403** in tests; state-changing POSTs (`/connect/github`, `/issues/{num}/agent-state`, `/projects/{repo}/sync`) require the CSRF token. No Phase-1 endpoint opts out.
- **INV-4 — Token scope & secret hygiene (§8.6).** The GitHub PAT is fine-grained, scoped to the single selected repo, with the four minimum permissions; it is stored in the encrypted `SecretStore` (file-mount), never in plain env or the DB cleartext, and never written to logs/events. `grep -rnE "ghp_|github_pat_" platform/backend/app | grep -iv "redact\|alias\|test\|secretstore"` shows **no** token literal being persisted/logged; the connect flow rejects a non-repo-scoped or over-broad token at preflight (AC-2).
- **INV-11 — Label write-queue + no PATCH endpoint (§8.1).** `grep -rni "PATCH.*/label" platform` is **empty**; `grep -rn "PUT.*labels\|set_agent_state" platform/backend/app/github` non-empty; all mutating GitHub calls demonstrably route through the single serialized write-queue (AC-6, AC-7). A 403-secondary/`Retry-After` test proves no rate-limit storm.
- **Webhooks stay out (ADR-P004).** `grep -rni "webhook\|X-Hub-Signature\|hmac" platform/backend/app/github` is empty — no unverified inbound endpoint is introduced in v1.

> Out-of-phase security INVs (INV-3 egress allowlist, INV-5 dispatch idempotency, INV-12 observer bridge) are exercised by Phase 0/2/3 and are not re-verified here, but Phase 1 must not regress them (e.g. do not add a GitHub call that bypasses the write-queue).

## 8. DESIGN_FIDELITY (UI slices 1.4, 1.5)

- **No hardcoded hex in `platform/frontend/src`** outside the tokens file (INV-14). `grep -rnE "#[0-9a-fA-F]{3,8}\b" platform/frontend/src --include=*.tsx --include=*.ts` excluding `styles/tokens.css` is **empty**. All color comes from CSS variables ported from `styles.css` (`--accent` indigo `#7b7bf5`, `--st-queued #94a3b8`, `--st-running #4f8cff`, `--st-paused #f5a623`, `--st-review #a78bfa`, `--st-done #34c98a`, `--st-failed #f2666b`, `--st-cancel #7c7a82`; GitHub label colors from the §7.4 `LABELS` map) — these literals live **only** in `tokens.css`.
- **Board columns + labels match §5.3.1 + the prototype.** Six columns in the `data.jsx COLUMNS` order; column→state mapping matches `components.jsx STATE_OF` (`backlog/queued→queued, progress→running, needsyou→paused, review→review, done→done`). Issue cards match `data.jsx ISSUES` fields (labels, workflow/agent chips, live mini-meter from `liveCost/liveTurns/progress`).
- **State badges are icon + label** (never color alone), pulsing on running/paused, matching `StateBadge` in `components.jsx` and the §7.3 palette + `.state.s-*` classes — AA contrast in both dark and light (NFR-A11Y-1).
- **Connect screen** matches `connect.jsx`: Segmented Welcome/Pick repo/Syncing tabs, the hero + reassurance copy, the repo-row layout (avatar + `org/name` + private/public `gh-label` + lang dot + issue count), the "What we'll do" `ConfirmRow`s, the Preflight rows, and the "Importing your issues…" `run-bar` syncing state.
- **Theme** dark+indigo default, six selectable skins available, persisted to `localStorage` (`dkmv-mode`/`dkmv-skin`); surfaces via `oklch()` per skin (§7.1).
- **Type/radii/motion** per §7.5 (`Plus Jakarta Sans` UI, `JetBrains Mono` for ids/numbers/meters with `tnum`; radii/easing tokens) — sourced from the ported tokens, not re-declared.

## 9. Independent verification commands

The evaluator runs these; all must pass (exit 0 / empty where noted).

```bash
# ---- Backend: lint, type, test ----
cd platform/backend && ruff check . && mypy app && pytest -q

# ---- Frontend: type, test ----
cd platform/frontend && npx tsc --noEmit && npx vitest run

# ---- INV-11: the fictional PATCH .../label MUST NOT appear; the real primitive MUST ----
grep -rni "PATCH.*/label" platform            # expect: empty
grep -rn  "PUT.*labels\|set_agent_state" platform/backend/app/github   # expect: non-empty

# ---- INV-14: no hardcoded hex outside the tokens file ----
grep -rnE "#[0-9a-fA-F]{3,8}\b" platform/frontend/src --include=*.tsx --include=*.ts \
  | grep -v "styles/tokens.css"               # expect: empty
bash scripts/hooks/post-edit-no-hardcoded-hex.sh   # convention hook, expect: empty/pass

# ---- INV-1: app access control present on the control plane ----
grep -rn "127.0.0.1\|Origin\|Host\|csrf" platform/backend/app/security/   # expect: non-empty

# ---- INV-4: no GitHub token literal persisted/logged ----
grep -rnE "ghp_|github_pat_" platform/backend/app \
  | grep -iv "redact\|alias\|test\|secretstore"     # expect: empty

# ---- App/webhooks stay deferred (ADR-P004) ----
grep -rni "webhook\|X-Hub-Signature\|X-GitHub-Delivery" platform/backend/app/github   # expect: empty

# ---- INV-8: aggregate strip excludes Codex spend ----
grep -rni "codex" platform/backend/app/api/board.py   # expect: non-empty (exclusion logic)

# ---- Engine untouched (INV-13) ----
git diff --name-only main..HEAD -- dkmv/      # expect: empty
```

## 10. Test plan

**Backend (pytest):**
- `test_github_client`: PAT auth reads from `SecretStore`; `GET /repos` returns the `Repo` shape; effective-write-permission probe (read-only token → blocker) (AC-1, AC-2).
- `test_github_sync`: GraphQL pagination + cursor persistence; incremental `since` read; Done-window bounding; idempotent `agent:*` label creation (AC-3, AC-4); GraphQL hash-cache hit avoids a duplicate fetch.
- `test_state_machine`: `set_agent_state` replace-all → single occupancy + non-agent labels preserved; multi-label precedence; authority rule (active-run DB row > label); In Review→Done, closed/reopened, failed-run demotion (AC-5, AC-6, AC-8).
- `test_write_queue`: serialized ordering of concurrent mutations; 403+`Retry-After` secondary-limit honored (waits, no interleave); `X-RateLimit-*` accounting surfaced (AC-7).
- `test_agent_state_api`: `POST /issues/{num}/agent-state` `queued`/`none` round-trips (AC-9).
- `test_board_aggregate`: "spent today" excludes $0 Codex, counts Codex tokens (AC-17, INV-8).
- `test_access_control` (shared from Phase 0, re-asserted): foreign-`Host` 403; CSRF required on the three state-changing POSTs (AC-14, INV-1).
- `test_secret_hygiene`: token never appears in event/log writes (INV-4).

**Frontend (vitest + render):**
- `Connect.test`: state-machine transitions; four permissions listed; verbatim reassurance copy; picker renders repos + "What we'll do" + preflight; "Open project" calls sync (AC-10, AC-11, AC-12).
- `theme.test`: default `dark`/`indigo`; `localStorage` persistence of `dkmv-mode`/`dkmv-skin` (AC-13).
- `Board.test`: six columns in §5.3.1 order; drag Backlog↔Queued posts agent-state, other columns not draggable; Populated/Empty/Syncing states; Empty copy (AC-15, AC-16, AC-18).
- `StateBadge.test`: renders icon + label (not color alone); correct palette class per state (AC-19).
- `Board.test` (negative): no `EventSource` in board/chrome (poll-only) (AC-20).
- A repo-wide no-hardcoded-hex assertion mirrors the INV-14 grep.

**Phase exit gate (per `CLAUDE.md`):** all AC checked off, every command in §9 passes, the §10 suites are green, and `ruff`/`mypy`/`tsc`/`vitest` are clean. Then update `progress.md` and proceed to Phase 2.

---

**PRD version:** v1.1 · **Phase:** 1 (M1) · **Features:** F4, F5, F6 · **Tasks:** T033–T058 · **ADR:** ADR-P004 · Generated against `_conventions.md` INV-1..15.
