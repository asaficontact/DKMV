# Git Commit Safety Strategy

## Status

Accepted

## Context and Problem Statement

DKMV runs Claude Code inside Docker containers where it writes code, runs tests, and commits. The agent commits its own work during the task, but the framework also needs to ensure that:

1. Declared outputs (`.agent/` files) are always committed, even if the agent forgets
2. Code changes the agent missed are caught before pushing
3. Framework-managed directories (`.agent/`, `.claude/`) don't pollute the agent's commits with unrelated chore changes

How should DKMV manage git commits to balance completeness with cleanliness?

## Decision Drivers

- Agent-committed work should be the primary commit mechanism
- Declared outputs must always reach the remote branch
- Chore commits should be rare and contain only genuine missed changes
- `.agent/` files are inter-task communication data and should be committed naturally
- `.claude/` is Claude Code's internal state and must never be committed

## Decision Outcome

A three-layer git teardown strategy that runs after each task completes, combining force-adding declared outputs, a selective safety net with pathspec exclusions, and `.gitignore` rules.

### Git Teardown Flow (`TaskRunner._git_teardown`)

```
Task completes (Claude Code committed its own work)
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 1: Force-add declared outputs                      │
│                                                          │
│  for output in task.outputs:                              │
│    git add -f {output.path}                               │
│                                                          │
│  Purpose: Ensure .agent/ outputs are staged even if      │
│  gitignored or missed by the agent. The -f flag          │
│  overrides .gitignore rules.                              │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 2: Selective safety net                            │
│                                                          │
│  git add -A -- . ':!.agent/' ':!.claude/'                │
│                                                          │
│  Purpose: Catch code changes the agent forgot to         │
│  commit, while EXCLUDING workspace directories.          │
│  Uses git pathspec negation to prevent .agent/ and       │
│  .claude/ from being swept into chore commits.           │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 3: Conditional chore commit                        │
│                                                          │
│  git status --porcelain                                   │
│  if output:                                               │
│    git commit -m "chore: uncommitted changes from        │
│                   {task.name} [dkmv]"                     │
│                                                          │
│  Purpose: Only create a chore commit if there are        │
│  genuinely uncommitted changes after the safety net.     │
│  Tagged with [dkmv] for easy identification.             │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│  Push (if task.push = true)                               │
│                                                          │
│  git push origin HEAD                                     │
└──────────────────────────────────────────────────────────┘
```

### `.gitignore` Strategy

Set up by `ComponentRunner._setup_workspace()`:

| Directory | Gitignored? | Rationale |
|-----------|-------------|-----------|
| `.agent/` | **No** | Inter-task communication data. Agent commits files naturally. Users can inspect on GitHub. Declared outputs are force-added as a safety net. |
| `.claude/` | **Yes** | Claude Code's internal state (settings, session data). Framework writes CLAUDE.md here each task — must not pollute commits. |

The `.claude/` entry is appended to `.gitignore` with a trailing newline guard to prevent corrupting the last line:

```bash
grep -qxF '.claude/' .gitignore 2>/dev/null \
  || { [ -s .gitignore ] && [ -n "$(tail -c1 .gitignore)" ] \
       && echo >> .gitignore; echo '.claude/' >> .gitignore; }
```

### Why Pathspec Exclusions

Without exclusions, `git add -A` would stage every file in `.agent/` and `.claude/`, producing noisy chore commits containing framework artifacts alongside actual missed code changes. The git pathspec pattern (`':!.agent/'`) is the same approach used by SWE-agent for the same problem (see [SWE-agent issue #528](https://github.com/SWE-agent/SWE-agent/issues/528)).

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| Agent commits everything | Layers 1-2 stage nothing new; `git status` is clean; no chore commit |
| Agent forgets to commit code | Layer 2 catches it; chore commit created |
| Agent forgets to commit `.agent/` output | Layer 1 force-adds it; included in chore commit |
| `.claude/CLAUDE.md` modified by framework | Excluded by both `.gitignore` and Layer 2 pathspec |
| `commit: false` and `push: false` | `_git_teardown` returns immediately; no git operations |

## Consequences

- Good: Agent's own commits are the primary mechanism — framework only intervenes when needed
- Good: Chore commits are rare in practice (agent usually commits everything)
- Good: Pathspec exclusions prevent `.agent/` and `.claude/` from polluting chore commits
- Good: `[dkmv]` tag makes framework-generated commits easily identifiable
- Good: Force-add ensures declared outputs always reach the remote branch
- Bad: The `git add -A` safety net can commit files the agent intentionally left unstaged (rare)
- Neutral: The `.gitignore` append is idempotent — safe to run multiple times on the same branch
