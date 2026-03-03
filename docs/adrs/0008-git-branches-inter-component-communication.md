# Git Branches as Inter-Component Communication

## Status

Accepted — Updated to reflect current component set and `.agent/` directory (see ADR-0010, ADR-0014)

## Context and Problem Statement

DKMV runs multiple specialized agents (Plan, Dev, QA, Docs) sequentially on the same codebase. These components need a way to share work products — Plan's implementation docs need to be visible to Dev, Dev's code changes need to be visible to QA, etc. How should components communicate and share state?

## Decision Drivers

- Components must be fully isolated (no shared memory, no shared filesystem)
- Work products must be durable, inspectable, and auditable
- The communication mechanism must work across different machines (local dev, CI, cloud)
- Users must be able to inspect intermediate results between component runs
- The mechanism should be simple and use standard developer tools

## Considered Options

- Git branches — components share state via a single feature branch
- Shared filesystem (mounted Docker volumes) — components read/write to a shared directory
- Database or message queue — components publish/consume events
- API-based handoff — components call each other's HTTP endpoints

## Decision Outcome

Chosen option: "Git branches", because they provide durable, portable, inspectable state sharing that uses standard developer tooling (git, GitHub) and requires zero additional infrastructure.

### How It Works

```
User writes PRD
       │
       ▼
┌──────────────┐   git push    ┌──────────────┐
│  Plan Agent   │ ────────────►│  Git Branch   │
│               │  feature/    │               │
│ Analyzes PRD, │  auth-plan   │ Implementation│
│ creates impl  │              │ docs, ADRs,   │
│ docs, phases  │              │ .agent/       │
└──────────────┘              │ analysis.json │
                               └──────┬────────┘
                                      │ git clone
                                      ▼
                               ┌──────────────┐
                               │  Dev Agent    │
                               │               │
                               │ Reads impl    │
                               │ docs, writes  │
                               │ code, tests   │
                               └──────┬────────┘
                                      │ git push
                                      ▼
                               ┌──────────────┐
                               │  Git Branch   │
                               │               │
                               │ + code changes│
                               │ + test suite  │
                               └──────┬────────┘
                                      │ git clone
                                      ▼
                               ┌──────────────┐
                               │  QA Agent     │
                               │               │
                               │ Evaluate →    │
                               │ Fix → Re-eval │
                               │ (see ADR-0014)│
                               └──────┬────────┘
                                      │ git push
                                      ▼
                               ┌──────────────┐
                               │  Git Branch   │
                               │               │
                               │ + fixes       │
                               │ + QA reports  │
                               └──────────────┘
```

### Communication Channels

Components communicate through two mechanisms:

1. **Code and docs on the branch** — implementation docs, source code, tests, ADRs
2. **Structured outputs in `.agent/`** — JSON artifacts that track task progress and inter-task data

| File | Written By | Read By | Purpose |
|------|-----------|---------|---------|
| `.agent/analysis.json` | Plan (analyze) | Plan (downstream tasks) | PRD analysis with features, risks, constraints |
| `.agent/prd.md` | DKMV (injected input) | Plan agent | PRD copied from host |
| `.agent/impl_docs/` | DKMV (injected input) | Dev, QA agents | Implementation docs copied from host |
| `.agent/qa_evaluation.json` | QA (evaluate) | QA (fix task) | Structured evaluation with issues list |
| `.agent/qa_report.json` | QA (re-evaluate) | User | Final QA report after fixes |
| `.agent/user_decisions.json` | DKMV (pause system) | Next task in sequence | User's interactive choices |
| `docs/implementation/<name>/` | Plan (assembly) | Dev, QA | Implementation docs committed to repo |
| `docs/adrs/` | Plan (analyze) | Dev | Architecture Decision Records |

### Branch Naming Convention

Each component auto-derives a branch name when `--branch` is not explicitly provided:

| Component | Default Branch | Example |
|-----------|---------------|---------|
| `plan` | `feature/{prd_stem}-plan` | `feature/user-auth-plan` |
| `dev` | `feature/{impl_docs_dir}-dev` | `feature/user-auth-dev` |
| `qa` | Required (`--branch` mandatory) | — |
| `docs` | Required (`--branch` mandatory) | — |

### Consequences

- Good: Git branches are durable — work products survive container destruction.
- Good: Users can inspect intermediate results on GitHub between component runs.
- Good: Standard tooling — `git log`, `git diff`, GitHub PR UI all work naturally.
- Good: No additional infrastructure required (no database, no message queue).
- Good: Components are truly isolated — each gets a fresh `git clone` of the branch.
- Good: Portable across environments (local, CI, cloud) without configuration changes.
- Bad: Requires network access to push/pull from remote repositories.
- Bad: Large binary artifacts are inefficient in git (not a concern for v1's JSON/text artifacts).
- Neutral: Merge conflicts are possible if multiple components run simultaneously on the same branch (not a v1 concern — components run sequentially).
