# DKMV Platform v1 — Implementation Plan

**Status:** Ready for pre-flight
**Owner:** Tawab (asaficontact)
**Implementation Lead:** Claude Code (super-orchestrator) + Opus sub-agents
**PRD:** `docs/design_docs/platform/PRD_dkmv_platform_v1.md` (v1.1, approved & locked for handoff)
**Design docs:** `docs/design_docs/platform/` (prototype JSX + `styles.css` + the 9-page PDF; LOCKED)
**Project prefix:** `dkmvp`
**Target:** a self-hostable web control plane in `platform/` that turns GitHub Issues into autonomous DKMV coding-agent runs ("assign it and walk away").

This directory was produced with the **PRD → Claude Code Implementation** methodology: decompose the PRD into phases, decompose each phase into parallel slices, dispatch slices to Opus implementer sub-agents in git worktrees, gate each with a fresh-context Opus evaluator + 3-lens polish, and PR for human review.

## How to read this directory

| File | Purpose |
|---|---|
| `README.md` | (you are here) overview + file inventory |
| `CLAUDE.md` | The agent operating manual — document map, ADRs, the phase loop, quality gates, DO-NOT-CHANGE |
| `CLAUDE_CODE_PROMPT.md` | **The master prompt to paste into Claude Code** (between BEGIN/END PROMPT), preceded by the one-time pre-flight |
| `orchestration.md` | Sub-agent topology + skills + hooks + MCP + worktree hygiene |
| `evaluation_protocol.md` | The build → evaluate → fix → 3-lens-polish → PR loop, escalation triggers, PR body + VERDICT formats, resume semantics |
| `claude-code-research.md` | Verified Claude Code feature reality (Agent tool, frontmatter, hooks, MCP, worktrees) — the source of truth for feature claims |
| `_conventions.md` | Shared stack + **system invariants INV-1..15** (with grep patterns) + locked files + verification commands |
| `phase_0_foundation.md` | Phase 0 — scaffold, persistence, engine bridge, sandbox/security baseline (PRD M0) |
| `phase_1_github_board.md` | Phase 1 — GitHub integration + Connect + Board (M1) |
| `phase_2_run_lifecycle.md` | Phase 2 — run launch + live run + HITL (M2) |
| `phase_3_durability.md` | Phase 3 — history, analytics, retries, crash recovery (M3) |
| `phase_4_workflows_viewer.md` | Phase 4 — read-only Workflows viewer (M4) |
| `phase_5_scale_ship.md` | Phase 5 — concurrency, cost governance, hardening, release (M5) |
| `phase_progress.log` | Session log (auto-appended by the Stop hook) |
| `self-eval-prompt.md` | Reusable unbiased self-evaluation prompt for refinement passes |
| `agents/` | Staged sub-agent files → copied to `.claude/agents/` at pre-flight |
| `skills/` | Staged skill files → copied to `.claude/skills/` at pre-flight |
| `hooks/` | Staged hook scripts → copied to `scripts/hooks/` at pre-flight |
| `settings.json` | Hook bindings → copied to `.claude/settings.json` at pre-flight |
| `CLAUDE_md_additions.md` | Block to append to the repo-root `CLAUDE.md` at pre-flight |
| `features.md`, `user_stories.md`, `tasks.md`, `adrs/` | Traceability appendix + locked architectural decisions (referenced by the phase briefs) |

## Implementation philosophy

1. The orchestrator never writes production code — it dispatches and advances.
2. Every implementer/evaluator sub-agent is Opus (test-runner is Sonnet).
3. Every slice is judged by an unbiased evaluator with fresh context (brief + branch only).
4. Worktree isolation for every implementer.
5. PR for human review at every phase boundary — **no auto-merge**.
6. Hooks + skills > prompt engineering (the PRD/design/engine locks are hooks).
7. No drift from the PRD, the design, or the engine.

## Project shape (drives the templates)

- **UI: yes** → DESIGN_FIDELITY checks + design-system skill + no-hardcoded-hex hook are ON.
- **Security surface: yes** → SECURITY_CHECKS (concrete greps for INV-1..13) are ON.
- **Solo developer: yes** → implementer + evaluator are the core (researcher/test-runner optional); 3-lens polish only for slices >3 files; Tawab is the merge gate; **serialized PR mode**.

## What the user (Tawab) does

1. PRD is already approved & locked (v1.1).
2. Run the one-time **pre-flight** at the top of `CLAUDE_CODE_PROMPT.md` (install GitHub MCP, copy `agents/`→`.claude/agents/`, `skills/`→`.claude/skills/`, `hooks/`→`scripts/hooks/` + `chmod +x`, `settings.json`→`.claude/settings.json`, append `CLAUDE_md_additions.md`, add `.claude/worktrees/` to `.gitignore`).
3. Paste the master prompt (between BEGIN/END PROMPT) into a **fresh** Claude Code session and say "go".
4. Review each phase PR; merge when satisfied; resolve any 🚨 BLOCKED escalations.

## Definition of done for DKMV Platform v1

From PRD §13: Screens 01–06 + Settings + a **read-only** Workflows viewer (07) built to the design specs; the backend domains live; a solo dev can `docker compose up` (after setup), connect `asaficontact/DKMV` with a fine-grained PAT, and complete the happy path **Connect → Board → Issue → Run → (pause → approve) → PR → History**, with correct (segment-sum) cost meters and clean restart recovery. All PRD §13 acceptance tests (AT-Connect/Board/Launch/Live/HITL/Recovery/History/Workflows/Concurrency/Isolation/PromptInjection/CodexCost) pass.

---
*Plan version v1.0 — built against PRD v1.1.*
