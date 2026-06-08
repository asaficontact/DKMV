# DKMV Platform — Pre-flight Status

## ✅ Done for you (installed + verified in the working tree)

- `.claude/agents/` — `dkmvp-implementer`, `dkmvp-evaluator`, `dkmvp-researcher`, `dkmvp-test-runner`.
- `.claude/skills/` — 5 skills (`dkmvp-backend-implementer`, `-design-system-applier`, `-github-control-plane`, `-prd-evaluator`, `-sse-streaming`).
- `scripts/hooks/` — 8 hooks, all `chmod +x`, all smoke-tested (lock-prd/-design/-engine, forbid-dangerous, post-edit-typecheck, post-edit-no-hardcoded-hex, contract-test, update-phase-progress).
- `.claude/settings.json` — valid JSON, binds all 8 hooks (every command resolves to an existing script).
- Root `CLAUDE.md` — platform conventions block appended.
- `.gitignore` — `.claude/worktrees/` added.
- `.claude/settings.local.json` — left untouched (your existing config).

## 🔧 Refinements made during setup

1. **Base branch → `platform`.** Worktree creation and PR target switched from `main` to your `platform` branch (keeps `main` clean until the platform is ready). Changed in `orchestration.md`, `evaluation_protocol.md`, `CLAUDE_CODE_PROMPT.md`.
2. **`post-edit-typecheck.sh` hardened** — no-ops gracefully when the project dir or the toolchain (ruff/mypy/tsc/node_modules) isn't present yet, so it can't block the very first scaffolding edits.
3. **`post-edit-no-hardcoded-hex.sh` scoped** — exemption tightened to the single canonical tokens file (`*/styles/tokens.css`) instead of any `*tokens*/*theme*` path.
4. **`forbid-dangerous.sh`** — removed `VACUUM INTO` from the block-list (it's the required SQLite backup primitive; was a false-positive) while keeping `rm -rf`, force-push, prune, prod-deploy, `DROP TABLE`.
5. **Fresh-checkout deps** — implementer now bootstraps a venv + editable install (and `npm ci`) on entering a worktree (worktrees don't inherit a venv/`node_modules`); `0.1-scaffold` creates the lockfiles first.
6. Doc drift fixed ("four hooks" → eight) and the master pre-flight now includes the required commit step.

## ⚠️ 3 commands you must run yourself (git writes + MCP can't be done from the assistant sandbox)

```bash
cd /path/to/DKMV

# 1. Commit the plan + setup to the platform branch (REQUIRED — worktrees only see committed files)
rm -f .git/index.lock 2>/dev/null            # clear a stale lock left by the assistant's sandbox
git add docs/design_docs/platform docs/implementation/platform \
        .claude/agents .claude/skills .claude/settings.json scripts/hooks CLAUDE.md .gitignore
git commit -m "chore(platform): implementation plan + Claude Code orchestration setup"

# 2. Install the GitHub MCP server (user-level; attaches on the NEXT claude session)
claude mcp add --transport http github https://api.githubcopilot.com/mcp/ \
  --header "Authorization: Bearer <YOUR_FINE_GRAINED_PAT>"
claude mcp list   # confirm "github" appears

# 3. Build the agent sandbox image (needed once runs execute — Phase 0.2+; can be done now or just-in-time)
docker build -t dkmv-sandbox:latest dkmv/images/
```

## ▶️ Then run it

```bash
claude --version          # record it (the feature claims in claude-code-research.md are version-gated)
claude                    # FRESH session so the GitHub MCP attaches
# paste the block between BEGIN PROMPT / END PROMPT from CLAUDE_CODE_PROMPT.md, then say: go
```

The orchestrator will post a status and wait for "go", then work Phase 0 → 5, opening one PR at a time against `platform` for you to review and merge.
