# Judge Deletion and QA Evaluate-Fix Loop

## Status

Accepted

## Context and Problem Statement

DKMV originally had two separate quality assurance components:

- **QA** — ran tests and reviewed code quality
- **Judge** — provided "independent evaluation" as a verdict after QA

In practice, the judge component was redundant: its "independent evaluation" overlapped entirely with QA. The judge added cost and time without providing meaningfully different insights, because both components reviewed the same code against the same requirements.

Additionally, QA was a single-task component — it evaluated but couldn't fix issues. Users had to manually iterate between QA runs and code fixes.

## Decision Drivers

- Eliminate redundant evaluation (judge duplicates QA's work)
- Enable automated fix cycles (evaluate → fix → re-evaluate)
- Fresh sessions for evaluation prevent bias (agent shouldn't evaluate its own fixes)
- Users need control over the fix decision (fix, ship as-is, or abort)
- Must integrate with the existing pause mechanism (ADR-0013)

## Decision Outcome

Delete the judge component entirely and rebuild QA as a 3-task evaluate-fix loop with interactive pausing.

### New QA Flow

```
┌──────────────────────────────────────────────────────────┐
│  dkmv qa --impl-docs ./docs/implementation/auth/         │
│          --branch feature/auth-dev                        │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│  Task 1: evaluate (01-evaluate.yaml)                      │
│  - Read-only: commit=false, push=false                    │
│  - Run full test suite                                    │
│  - Review against implementation docs                     │
│  - Produce .agent/qa_evaluation.json + .agent/qa_evaluation.md │
│  - pause_after: true                                      │
└──────────────────────────┬───────────────────────────────┘
                           │ _qa_pause_callback
                           ▼
┌──────────────────────────────────────────────────────────┐
│  Interactive Pause                                        │
│                                                          │
│  QA Evaluation: FAIL                                      │
│  Tests: 120 total, 115 passed, 5 failed                  │
│  Issues: 2 critical, 3 high                               │
│                                                          │
│  What would you like to do?                               │
│    1. Fix issues and re-evaluate (Recommended)            │
│    2. Ship as-is (skip fixes)          → skip_remaining   │
│    3. Abort                            → typer.Exit(1)    │
│                                                          │
│  User decision → .agent/user_decisions.json               │
└──────────────────────────┬───────────────────────────────┘
                           │ (if "fix")
                           ▼
┌──────────────────────────────────────────────────────────┐
│  Task 2: fix (02-fix.yaml)                                │
│  - Reads .agent/user_decisions.json + qa_evaluation.json  │
│  - Fixes issues by severity (critical first)              │
│  - Re-runs test suite                                     │
│  - commit=true, push=true                                 │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│  Task 3: re-evaluate (03-re-evaluate.yaml)                │
│  - Fresh session — evaluates without knowledge of fixes   │
│  - Produces final .agent/qa_report.json + qa_report.md    │
│  - commit=false, push=false                               │
└──────────────────────────────────────────────────────────┘
```

### Key Design Decisions

**1. Fresh sessions for evaluation**

Each task runs as a separate Claude Code invocation with its own session. The re-evaluate task (task 3) has no memory of the fix task (task 2), preventing the "I just fixed it, so it must be fine" bias. The agent evaluates the current state of the code independently.

**2. CLI hardcodes the menu, not the agent**

The QA pause callback (`_qa_pause_callback`) in the CLI reads the structured `qa_evaluation.json` from the pause context and presents a fixed 3-choice menu. This is different from the plan component's `_rich_pause_callback`, which renders agent-generated questions. Hardcoding the menu ensures consistent UX and prevents the agent from influencing the user's decision.

**3. `--impl-docs` replaces `--prd`**

QA now takes `--impl-docs` (path to implementation docs directory) instead of `--prd`. This matches the dev component's interface — both receive the same implementation docs produced by the plan component. The implementation docs contain the requirements, acceptance criteria, and conventions needed for evaluation.

**4. `--auto` skips pauses**

When `--auto` is passed, `on_pause=None` and the component runs all three tasks without stopping. This enables fully automated CI pipelines.

### What Was Deleted

| Item | Type |
|------|------|
| `dkmv/builtins/judge/` | Entire directory (component.yaml, 01-verdict.yaml) |
| `dkmv judge` CLI command | ~90 lines |
| `"judge"` in `BUILTIN_COMPONENTS` | Set entry in `discovery.py` |
| `"judge"` in `_BUILTIN_DESCRIPTIONS` | Dict entry in `registry.py` |
| Judge tests | All test functions and assertions referencing judge |
| Judge force-includes | `pyproject.toml` entries |

### QA CLI Interface

```bash
# Interactive (pauses after evaluation)
dkmv qa --impl-docs ./docs/implementation/auth/ --branch feature/auth-dev

# Automated (no pauses)
dkmv qa --impl-docs ./docs/implementation/auth/ --branch feature/auth-dev --auto

# With overrides
dkmv qa --impl-docs ./docs --branch main --model claude-sonnet-4-6 --max-budget-usd 5.00
```

Required flags: `--impl-docs`, `--branch`
Optional: `--repo` (from project config), `--feature-name`, `--model`, `--max-turns`, `--max-budget-usd`, `--timeout`, `--keep-alive`, `--auto`, `--verbose`

## Consequences

- Good: Eliminates redundant judge component — one evaluation path instead of two
- Good: Evaluate-fix-re-evaluate loop automates the manual iteration cycle
- Good: Fresh sessions for re-evaluation prevent self-evaluation bias
- Good: CLI-hardcoded menu provides consistent, predictable UX
- Good: `skip_remaining` cleanly short-circuits when user chooses "ship as-is"
- Good: `--auto` enables CI/CD integration without interactive pauses
- Bad: Only one fix iteration — if the fix introduces new issues, the re-evaluate report will flag them but won't trigger another fix cycle. Users must re-run `dkmv qa` manually.
- Neutral: The evaluate and re-evaluate tasks use the same JSON schema but write to different files (`qa_evaluation.json` vs `qa_report.json`), enabling comparison.
