# Git Branches as Inter-Component Communication

## Status

Accepted

## Context and Problem Statement

DKMV runs multiple specialized agents (Dev, QA, Judge, Docs) sequentially on the same codebase. These components need a way to share work products — Dev's code changes need to be visible to QA, QA's report needs to be visible to Judge, etc. How should components communicate and share state?

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
┌─────────────┐    git push     ┌─────────────┐
│   Dev Agent  │ ──────────────► │  Git Branch  │
│              │   feature/auth  │              │
│ Writes code, │                 │ Code changes │
│ commits to   │                 │ .dkmv/plan.md│
│ branch       │                 │              │
└─────────────┘                 └──────┬───────┘
                                       │ git clone
                                       ▼
                                ┌─────────────┐
                                │   QA Agent   │
                                │              │
                                │ Reads code,  │
                                │ runs tests,  │
                                │ writes report│
                                └──────┬───────┘
                                       │ git push
                                       ▼
                                ┌─────────────┐
                                │  Git Branch  │
                                │              │
                                │ + QA report  │
                                │ .dkmv/       │
                                │  qa_report.  │
                                │  json        │
                                └──────┬───────┘
                                       │ git clone
                                       ▼
                                ┌─────────────┐
                                │ Judge Agent  │
                                │              │
                                │ Reads code + │
                                │ QA report,   │
                                │ writes verdict│
                                └──────┬───────┘
                                       │ git push
                                       ▼
                                ┌─────────────┐
                                │  Git Branch  │
                                │              │
                                │ + verdict    │
                                │ .dkmv/       │
                                │  verdict.json│
                                └─────────────┘
```

### Communication Channels

Components communicate through well-known file paths in the `.dkmv/` directory on the branch:

| File | Written By | Read By | Purpose |
|------|-----------|---------|---------|
| `.dkmv/plan.md` | Dev | QA, Judge | Implementation plan |
| `.dkmv/prd.md` | BaseComponent | All | PRD (copied from host) |
| `.dkmv/qa_report.json` | QA | Judge | Test results and findings |
| `.dkmv/verdict.json` | Judge | User | Pass/fail verdict with score |
| `.dkmv/feedback.json` | User/QA | Dev (on re-run) | Feedback for iteration |

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
