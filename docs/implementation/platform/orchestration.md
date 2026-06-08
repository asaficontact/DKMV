# DKMV Platform v1 — Orchestration Architecture

> Feature claims here are grounded in `claude-code-research.md` (verified 2026-06). Re-verify with `claude --version` at pre-flight. Note: the dispatch tool is **`Agent`** in current Claude Code (the old name `Task` still works as an alias); a per-call `model` parameter exists but we keep `model` in agent frontmatter as the default.

## 1. Topology

```
                         ┌─────────────────────────────┐
                         │   ORCHESTRATOR (you)        │
                         │   Claude Code main session   │
                         │   — reads briefs, dispatches │
                         │   — parses structured returns│
                         │   — NEVER writes prod code   │
                         └──────────────┬──────────────┘
        Agent() dispatch (parallel)     │
   ┌───────────────┬───────────────┬────┴──────────┬────────────────┐
   ▼               ▼               ▼               ▼                ▼
┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
│ dkmvp-     │ │ dkmvp-     │ │ dkmvp-     │ │ dkmvp-     │ │ (built-in) │
│ implementer│ │ evaluator  │ │ researcher │ │ test-runner│ │ Explore    │
│ Opus       │ │ Opus       │ │ Opus (opt) │ │ Sonnet(opt)│ │ read-only  │
│ worktree   │ │ read-only  │ │ web        │ │ run tests  │ │ search     │
└────────────┘ └────────────┘ └────────────┘ └────────────┘ └────────────┘
   writes code    judges diff     external Q     test matrix    fan-out search
   → JSON report  → VERDICT block
```

Solo-mode note: `dkmvp-implementer` + `dkmvp-evaluator` are the core. `dkmvp-researcher` and `dkmvp-test-runner` are provided but optional — the orchestrator may run tests directly via Bash and use `WebSearch`/the built-in `Explore` agent instead, to save dispatch overhead.

## 2. Sub-agent definitions (canonical source the pre-flight copies)

The four agent files are staged at `docs/implementation/platform/agents/` and copied to `.claude/agents/` at pre-flight. Frontmatter (verified-real fields only — `name`, `description`, `model`, `tools`):

| Agent | model | tools | role |
|---|---|---|---|
| `dkmvp-implementer` | opus | Read, Write, Edit, Glob, Grep, Bash, TodoWrite | writes one slice in a worktree; returns JSON (first char `{`). **No `Agent`/`Task` tool → cannot spawn children (leaf).** |
| `dkmvp-evaluator` | opus | Read, Glob, Grep, Bash | read-only; returns a strict VERDICT block; fresh context (brief + branch only). |
| `dkmvp-researcher` | opus | Read, Glob, Grep, WebSearch, WebFetch | one focused external question → cited summary. Optional. |
| `dkmvp-test-runner` | sonnet | Read, Glob, Grep, Bash | runs suites → pass/fail matrix. Optional. |

The full system prompts (including the system invariants the evaluator greps) live in those files — do not duplicate them here.

## 3. Skills

Staged at `docs/implementation/platform/skills/`, copied to `.claude/skills/` at pre-flight. Frontmatter fields: `name`, `description`, `allowed-tools` (hyphenated).

| Skill | When |
|---|---|
| `dkmvp-backend-implementer` | any `platform/backend` slice |
| `dkmvp-design-system-applier` | any `platform/frontend` UI slice (token enforcement) |
| `dkmvp-sse-streaming` | streaming + meter slices (2.3, 2.4) |
| `dkmvp-github-control-plane` | GitHub slices (1.1–1.3, reconcile) |
| `dkmvp-prd-evaluator` | validate against a cited PRD § (argument = section number) |

## 4. Hooks

Staged at `docs/implementation/platform/hooks/` → `scripts/hooks/`; bindings staged at `settings.json` → `.claude/settings.json`. Every hook reads stdin JSON via `jq`, exits `2` to block (and returns stderr to Claude), `0` to allow.

| Hook | Lifecycle (matcher) | Effect | Override |
|---|---|---|---|
| `lock-prd.sh` | PreToolUse (Edit\|Write) | block edits to PRD / phase briefs / ADRs | `PRD_UNLOCK=1` |
| `lock-design.sh` | PreToolUse (Edit\|Write) | block edits to the design prototype + tokens | `DESIGN_UNLOCK=1` |
| `lock-engine.sh` | PreToolUse (Edit\|Write) | block edits to `dkmv/**` (engine; consume only) | `ENGINE_UNLOCK=1` |
| `forbid-dangerous.sh` | PreToolUse (Bash) | block `rm -rf`, `git push --force`, prune, prod deploy, `DROP TABLE` | `PROD_OK=1` |
| `post-edit-typecheck.sh` | PostToolUse (Edit\|Write) | `.py`→ruff+mypy; `.ts/.tsx`→tsc | — |
| `post-edit-no-hardcoded-hex.sh` | PostToolUse (Edit\|Write) | block hardcoded hex in `platform/frontend/src` (INV-14) | — |
| `contract-test.sh` | SubagentStop | run `platform/backend/tests/contract` if present | — |
| `update-phase-progress.sh` | Stop | append a marker to `phase_progress.log` | — |

The `lock-engine.sh` hook is DKMV-specific and load-bearing (the platform consumes a locked engine). Each script was smoke-tested (lock-prd blocks with exit 2; lock-engine allows `platform/` paths).

## 5. MCP servers

- **GitHub MCP** (required for opening phase-boundary PRs): install user-level at pre-flight; attaches on the NEXT session start. Current recommended install is the hosted HTTP server — verify the exact command in `claude-code-research.md` at pre-flight (the stdio Docker form `ghcr.io/github/github-mcp-server` also works). Tool prefix `mcp__github__*`.
- No backend-platform MCP (the platform's own DB is local SQLite the orchestrator never queries directly; sub-agents inspect it via Bash in their worktree).
- Restriction: only the orchestrator and the human use `mcp__github__*` (for PRs/reviews). Implementer sub-agents do NOT have GitHub MCP in their tools — they interact with GitHub only through the platform code they're building, against test fixtures.

## 6. CLAUDE.md additions

Append the block in `CLAUDE_md_additions.md` to the repo-root `CLAUDE.md` at pre-flight (keep the root file ≤ ~100 lines — workflows live in skills, not CLAUDE.md).

## 7. Worktree hygiene

- The **orchestrator** creates one worktree per slice via Bash (NOT a dispatch parameter):
  `git worktree add .claude/worktrees/phase-N-impl-<slice> -b phase-N-impl-<slice> platform`
- The implementer `cd`s into its worktree as its first action and works there.
- `.claude/worktrees/` is gitignored (added at pre-flight).
- Cleanup after merge: `git worktree remove .claude/worktrees/<branch>` then `git branch -D <branch>`.
- Resume-safe: `git worktree add` is idempotent on an existing dir; a corrupted worktree is `git worktree remove --force` + re-dispatch.
- **Fresh-checkout deps:** a worktree does NOT inherit a venv / `node_modules`. The implementer bootstraps deps on entry (`dkmvp-implementer.md` §6.1a — backend venv + editable install of `platform/backend` and the `dkmv` engine; frontend `npm ci`). Phase 0 slice `0.1-scaffold` creates the lockfiles/`pyproject.toml`/`package.json` those later bootstraps rely on, so it runs first.
- (Alternative noted in research: `isolation: worktree` frontmatter exists, but we use the orchestrator-Bash pattern so the worktree paths are explicit and the resume/cleanup model in `evaluation_protocol.md` works.)

## 8. The orchestrator's read-list before starting work

1. `docs/implementation/platform/CLAUDE.md` (the operating manual).
2. `docs/implementation/platform/orchestration.md` (this file).
3. `docs/implementation/platform/evaluation_protocol.md` (the loop).
4. PRD **§0 + §1 only** (overview + problem) — never the whole PRD (context is sacred; sub-agents read the cited sections).
5. The **current** phase brief only, when that phase begins.

The orchestrator does NOT read `_conventions.md` invariant bodies, agent system prompts, or deep PRD sections — those are sub-agent reads.
