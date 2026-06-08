# Claude Code Feature Reality (2026)

**Captured:** 2026-06-08

**Purpose:** Gate feature claims across the orchestration plan against the CURRENT Claude
Code surface area. The #1 failure mode of this methodology is inventing features that do not
exist. Every section below is either CONFIRMED against live docs or CORRECTED. Items the
researcher could not fully verify are explicitly flagged "**RE-CHECK**" — a human must confirm
those before any dependent doc relies on them.

**Pre-flight requirement:** record the exact `claude --version` at the start of every run and
pin it in `progress.md`. Several facts below are version-gated (notably the Task→Agent rename
landed in **v2.1.63**, and remote-MCP `add-json` HTTP behavior changed in **v2.1.1**). If the
installed version differs materially from the versions cited here, re-verify this whole file.

> Verification dates use the format "(verified 2026-06-07)" where confirmed against docs on
> that date. Sources are listed at the bottom; inline section refs point to them.

---

## Task tool parameters (verified)

**CORRECTION — the tool was renamed.** As of **v2.1.63** the `Task` tool is named **`Agent`**.
Existing `Task(...)` references in settings, `tools:` allowlists, and agent definitions still
work as **aliases**, so `Task` is not "wrong," but new docs and code should prefer `Agent`.
(verified 2026-06-07)

Core invocation parameters (the set the plan should assume):

- `subagent_type` — which sub-agent to dispatch (the `name` from agent frontmatter, or a
  built-in like `Explore`).
- `description` — short task description.
- `prompt` — the full instruction handed to the sub-agent.

**CORRECTION — there IS now a per-invocation `model` parameter.** The model-resolution order is
documented as: (1) `CLAUDE_CODE_SUBAGENT_MODEL` env var, (2) **the per-invocation `model`
parameter**, (3) the sub-agent definition's `model` frontmatter, (4) the main conversation's
model. So the old assumption "there is NO `model` on the call — model only lives in frontmatter"
is **outdated**: frontmatter is the default, but a single dispatch can override it with a `model`
parameter. (verified 2026-06-07)

- There is **no** `isolation` or `tools` parameter *on the Agent call itself*. `isolation` and
  tool restrictions live in the **sub-agent frontmatter** (see next section). Worktree isolation
  for a one-off dispatch is expressed as `isolation: "worktree"` passed when spawning — treat
  this as a frontmatter-equivalent on the spawn, not a free-form Task arg. **RE-CHECK** the exact
  spawn-time arg name if a doc depends on programmatically setting isolation per-call.
- **Caveat:** the docs describe *behavior*, not a published raw JSON schema for the tool. The
  three core param names (`subagent_type`/`description`/`prompt`) match the live tool schema in
  this environment; if a downstream doc quotes the literal schema, **RE-CHECK** against the
  running `claude --version`.

---

## Sub-agent frontmatter

File-based sub-agents live in `.claude/agents/<name>.md` (project) or `~/.claude/agents/`
(user). Only `name` and `description` are **required**. (verified 2026-06-07)

Full supported field set (per the "Supported frontmatter fields" table):

| Field | Notes |
| :-- | :-- |
| `name` | **Required.** Used as `subagent_type` / `agent_type`. |
| `description` | **Required.** Tells Claude when to delegate. |
| `tools` | Allowlist of tool names (e.g. `Read, Grep, Glob`). Omitting it inherits the parent pool. |
| `disallowedTools` | Denylist; applied against the remaining pool. A tool in both is removed. |
| `model` | Model alias (`sonnet`, `opus`, `haiku`, `inherit`) or full id. Default for the agent. |
| `permissionMode` | Permission mode for the sub-agent (e.g. `plan`, `acceptEdits`). |
| `mcpServers` | Restrict/declare MCP servers for the sub-agent. |
| `hooks` | Inline hook definitions scoped to the sub-agent. |
| `maxTurns` | Cap on agent turns. |
| `skills` | Preload specific skills into the sub-agent. |
| `isolation` | **REAL field.** `isolation: worktree` gives the sub-agent its own git worktree. |
| `color` | UI/display color. |

**CORRECTIONS to the prior assumptions:**

- `isolation` is **REAL** (not nonexistent). Used for worktree isolation. (verified 2026-06-07)
- `context` is **NOT** a sub-agent frontmatter field — `context: fork` is a **Skill** field
  (see Skill section). Do not put `context:` in an agent file. (verified 2026-06-07)
- `disable-model-invocation` is **NOT** a sub-agent field — it is a **Skill** field. (verified
  2026-06-07)
- The old assumed minimal set `{name, description, model, tools}` is a correct *subset* but
  incomplete; the real set is the table above.

Built-in tools that are present by default and that you restrict via `tools`/`disallowedTools`
include `Agent`, `AskUserQuestion`, `EnterPlanMode`, `ExitPlanMode`, `ScheduleWakeup`,
`WaitForMcpServers`. If `Agent` is omitted from a sub-agent's `tools` allowlist, that sub-agent
**cannot spawn further sub-agents**. (verified 2026-06-07)

---

## Skill frontmatter

Skills live in `.claude/skills/<name>/SKILL.md` (and user/plugin equivalents). `.claude/commands/*.md`
files still work and are merged into the same `/name` mechanism. All frontmatter fields are
optional; only `description` is recommended. (verified 2026-06-07)

Confirmed fields:

- `name` — skill name / slash-command name.
- `description` — when Claude should use it (loaded into context; keep it tight).
- **`allowed-tools`** — **EXACT key is hyphenated `allowed-tools`** (NOT `allowed_tools`, NOT
  `allowedTools`). Grants the listed tools without per-use approval while the skill is active,
  e.g. `allowed-tools: Bash(git add *) Bash(git commit *)`. (verified 2026-06-07)
- `disable-model-invocation: true` — only the human can invoke (model won't auto-trigger).
  Use for side-effecting workflows like `/deploy`, `/commit`. (verified 2026-06-07)
- `context: fork` — run the skill in a forked/sub-agent context. (verified 2026-06-07)
- `user-invocable` — controls menu visibility only (not Skill-tool access). (verified 2026-06-07)

Skill bodies load lazily (only when used), so long reference material is cheap until invoked.

---

## Hook input format

Confirmed as assumed, with extra detail. (verified 2026-06-07)

- **Transport:** command hooks receive a single JSON object on **stdin**; HTTP hooks receive the
  same JSON as the POST body. Parse with `jq`, e.g. `jq -r '.tool_input.command'`.
- **Common input fields:** `session_id`, `transcript_path`, `cwd`, `permission_mode`,
  `hook_event_name`, plus event-specific fields. For tool events the event-specific fields are
  `tool_name` and `tool_input`. When run under `--agent`/inside a sub-agent, `agent_id` and
  `agent_type` are also present.
- **`tool_use_id`:** present in tool-event payloads but is **not** listed in the common-fields
  table; treat it as available on `PostToolUse`-class events. **RE-CHECK** the exact field name
  if a hook script depends on it. (could not confirm in the common-fields table)
- **Exit codes:** `0` = success (stdout parsed for JSON output fields only on exit 0; for most
  events stdout is debug-only, except `UserPromptSubmit`/`UserPromptExpansion`/`SessionStart`
  where stdout becomes context). `2` = **blocking error** — stdout ignored, **stderr is fed back
  to Claude** as the error message; effect depends on event. **Any other non-zero code is a
  NON-blocking error** for most events (execution continues) — so policy-enforcing hooks MUST use
  `exit 2`, not `exit 1`. (One exception: `WorktreeCreate` aborts on any non-zero code.)
  (verified 2026-06-07)

**Lifecycle events (all confirmed real):** `PreToolUse` (can block), `PostToolUse` (cannot
block; stderr shown to Claude), `Stop` (exit 2 prevents stopping), `SubagentStop` (exit 2
prevents the sub-agent stopping). The current surface is larger than the four assumed — also
present: `PostToolUseFailure`, `PostToolBatch`, `PermissionRequest`, `PermissionDenied`,
`UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`, `TeammateIdle`, `TaskCreated`,
`TaskCompleted`, `ConfigChange`, `StopFailure`, `WorktreeCreate`, `WorktreeRemove`,
`SubagentStart`. Note: for sub-agents, a `Stop` hook is automatically converted to `SubagentStop`.
(verified 2026-06-07)

**settings.json binding shape** (verified 2026-06-07) — events map to arrays of matcher/hook
groups; tool events match on `tool_name`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "./scripts/block-rm.sh" }
        ]
      }
    ]
  }
}
```

`type: "command"` hooks talk via stdin/exit-code/stdout; `type: "http"` hooks POST the JSON and
reply via HTTP body. Matcher values for tool events are tool names (`Bash`, `Edit|Write`,
`mcp__.*`). MCP tools appear as normal tools in tool events and match the same way.

---

## Worktree pattern

Confirmed. (verified 2026-06-07)

Manual git worktree workflow (what the plan should use for external orchestration):

```bash
git worktree add ../project-feature-a -b feature-a      # new branch
git worktree add ../project-bugfix bugfix-123           # existing branch
git worktree list
git worktree remove ../project-feature-a
```

Claude Code-native options also exist and may be referenced but are not required:

- `claude --worktree <name>` / `-w` — starts Claude in an isolated worktree under
  `.claude/worktrees/<name>/` on branch `worktree-<name>`. Requires accepting the workspace
  trust dialog (`claude` once in the dir) first. PR worktrees via `claude --worktree "#1234"`.
- Sub-agent worktree isolation via `isolation: worktree` frontmatter (see Sub-agent section).
- Auto-cleanup: sub-agent/background worktrees are swept after `cleanupPeriodDays` if clean;
  `--worktree` sessions are never auto-swept. Non-interactive (`-p`) `--worktree` runs are NOT
  auto-cleaned — remove with `git worktree remove`.
- `WorktreeCreate`/`WorktreeRemove` hooks override default git behavior (for SVN/Perforce/etc.).

Reminder for the plan: each new worktree is a fresh checkout — dependencies/venv/`.env` are NOT
present. Use `.worktreeinclude` (gitignore syntax, copies only gitignored matches) or a setup
step. (verified 2026-06-07)

---

## MCP install pattern

Confirmed with current syntax. (verified 2026-06-07)

- **stdio (local command):** `claude mcp add [options] <name> -- <command> [args...]`. Everything
  after `--` is the server command. Env vars via `--env KEY=value`. The original assumption
  `claude mcp add <name> -- <cmd>` holds (newer docs prefer `--transport stdio` explicitly).
- **Remote HTTP/SSE:** `claude mcp add --transport http <name> <url> [--header "..."]` (or
  `--transport sse`). For Claude Code ≥ **v2.1.1**, `claude mcp add-json <name> '{...}'` supports
  full HTTP server JSON.
- **Scope:** `--scope local` (default, current project only), `--scope project` (shared via
  `.mcp.json`), `--scope user` (all projects). User config is written to the user's config file.
- **Attach timing:** `claude mcp add` writes the config entry; the server is loaded when a
  session starts (and managed in-session via `/mcp`). The prior assumption "attaches only on the
  NEXT session start" is consistent with config-file behavior, but the docs phrase it as
  configure-then-use rather than an explicit "next session" guarantee — **RE-CHECK** the exact
  reload semantics (whether `/mcp` can hot-attach mid-session) before a doc hard-depends on it.

**GitHub MCP — CORRECTION on the recommended install.** The currently recommended path is the
**remote hosted HTTP server**, not a locally-run npm/Docker package:

```bash
claude mcp add --transport http github https://api.githubcopilot.com/mcp/ \
  --header "Authorization: Bearer YOUR_GITHUB_PAT"
```

(verified 2026-06-07, Claude Code MCP docs + GitHub's official `github-mcp-server` install
guide.) The Docker stdio variant still works and is documented by GitHub:

```bash
claude mcp add github -e GITHUB_PERSONAL_ACCESS_TOKEN=YOUR_PAT -- \
  docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN ghcr.io/github/github-mcp-server
```

So: prefer the hosted HTTP endpoint `https://api.githubcopilot.com/mcp/`; the package image is
`ghcr.io/github/github-mcp-server` if a self-hosted stdio server is needed. There is **no**
`npx @github/mcp` style package to assume — **RE-CHECK** if a doc cites an npm package name.

---

## Built-in skills / commands that EXIST

(verified 2026-06-07 against the commands/skills docs and this environment)

- Built-in commands: `/help`, `/compact`, `/mcp`, `/model`, `/agents` (and the broader command
  reference at the source link).
- Bundled skills (invocable as slash commands): `/debug`, `/code-review`. Also available in this
  environment: `/init`, `/review`, `/security-review`.
- The `Agent` tool (formerly `Task`) for dispatching sub-agents; built-in sub-agent type
  `Explore` for read-only exploration.

## Built-in skills / commands that DO NOT exist (avoid claiming)

- **No** `isolation`, `context`, or `tools` parameter *on the Agent/Task call* as free-form args
  (isolation/tools are frontmatter; `model` is the only documented per-call override).
- **No** `context` or `disable-model-invocation` field in **sub-agent** frontmatter (those are
  **Skill** fields — do not cross them).
- **No** `allowed_tools` / `allowedTools` skill key — it is hyphenated `allowed-tools`.
- **No** assumption that `exit 1` blocks a tool — only `exit 2` blocks (except `WorktreeCreate`).
- **No** npm `@github/mcp`-style package for the GitHub MCP — use the hosted HTTP endpoint or
  `ghcr.io/github/github-mcp-server`.
- Do not assume a literal published JSON schema for the `Agent` tool in the docs — behavior is
  documented, not the raw schema. **RE-CHECK** at pin time.

---

## Sources

- Sub-agents (frontmatter, Task→Agent rename, model resolution, tool restrictions):
  https://docs.claude.com/en/docs/claude-code/sub-agents → https://code.claude.com/docs/en/sub-agents
- Hooks (input format, exit codes, events, settings shape):
  https://docs.claude.com/en/docs/claude-code/hooks → https://code.claude.com/docs/en/hooks
- Skills (SKILL.md frontmatter, `allowed-tools`, `disable-model-invocation`, `context`):
  https://docs.claude.com/en/docs/claude-code/skills → https://code.claude.com/docs/en/skills
- MCP (install syntax, scopes, GitHub HTTP endpoint):
  https://docs.claude.com/en/docs/claude-code/mcp → https://code.claude.com/docs/en/mcp
- Worktrees (`--worktree`, manual git workflow, sub-agent isolation, cleanup):
  https://code.claude.com/docs/en/worktrees
- GitHub official MCP server install guide:
  https://github.com/github/github-mcp-server/blob/main/docs/installation-guides/install-claude.md
- Commands reference (built-in commands + bundled skills):
  https://code.claude.com/docs/en/commands
