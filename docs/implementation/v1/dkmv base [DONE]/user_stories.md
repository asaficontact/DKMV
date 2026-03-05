# DKMV v1 User Stories

## Summary

26 user stories across 6 categories, extracted from PRD Section 4.

## Traceability Matrix

| US ID | Title | Feature | Task(s) | Status |
|-------|-------|---------|---------|--------|
| US-01 | Install CLI | F1 | T010-T015 | [ ] |
| US-02 | Build sandbox image | F2 | T023-T026 | [ ] |
| US-03 | Configure credentials | F1 | T019-T022 | [ ] |
| US-04 | Clear error messages | F1, F2 | T021, T024 | [ ] |
| US-05 | Dev implements PRD | F7 | T060-T072 | [ ] |
| US-06 | Real-time streaming | F5, F7 | T046-T049, T063 | [ ] |
| US-07 | Dev self-iteration | F7 | T063 | [ ] |
| US-08 | Continue on existing branch | F7 | T070 | [ ] |
| US-09 | Feedback from Judge | F7 | T067 | [ ] |
| US-10 | Model selection | F7 | T069 | [ ] |
| US-11 | Max-turns limit | F7 | T069 | [ ] |
| US-12 | QA validates branch | F8 | T073-T077 | [ ] |
| US-13 | QA runs tests + evaluates | F8 | T075 | [ ] |
| US-14 | QA report saved | F8 | T075-T076 | [ ] |
| US-15 | Judge evaluates pass/fail | F9 | T078-T082 | [ ] |
| US-16 | Structured Judge output | F9 | T080 | [ ] |
| US-17 | Judge independence | F9 | T080 | [ ] |
| US-18 | Docs generation | F10 | T083-T086 | [ ] |
| US-19 | Auto-create PR | F10 | T085 | [ ] |
| US-20 | List runs | F11 | T090 | [ ] |
| US-21 | Inspect run details | F11 | T091 | [ ] |
| US-22 | Attach to container | F3, F11 | T034, T092 | [ ] |
| US-23 | Keep container alive | F3, F11 | T035, T092 | [ ] |
| US-24 | Stop keep-alive container | F3, F11 | T035, T093 | [ ] |
| US-25 | Cost tracking | F4 | T042, T044 | [ ] |
| US-26 | Design docs for Dev | F7 | T066 | [ ] |

---

## Stories by Category

### Setup & Configuration (US-01 through US-04)

#### US-01: Install CLI

> As a developer, I want to install the DKMV CLI with a single command so I can start using it immediately

**Acceptance Criteria:**
- [ ] `uv sync` makes `dkmv` available
- [ ] `uv run dkmv --help` shows all commands

**Feature:** F1 | **Tasks:** T010-T015 | **Priority:** Must-have

---

#### US-02: Build Sandbox Image

> As a developer, I want to build the sandbox Docker image so components have an environment to run in

**Acceptance Criteria:**
- [ ] `dkmv build` builds the `dkmv-sandbox:latest` image
- [ ] Image includes git, gh, node, python, Claude Code

**Feature:** F2 | **Tasks:** T023-T026 | **Priority:** Must-have

---

#### US-03: Configure Credentials

> As a developer, I want to configure my Anthropic API key and GitHub credentials once so every run uses them

**Acceptance Criteria:**
- [ ] Env vars `ANTHROPIC_API_KEY`, `GITHUB_TOKEN` or `.env` file in project root
- [ ] Validated at startup

**Feature:** F1 | **Tasks:** T019-T022 | **Priority:** Must-have

---

#### US-04: Clear Error Messages

> As a developer, I want clear error messages when prerequisites are missing

**Acceptance Criteria:**
- [ ] `dkmv build` fails gracefully if Docker isn't installed
- [ ] `dkmv dev` fails if image isn't built
- [ ] API key missing shows specific message

**Feature:** F1, F2 | **Tasks:** T021, T024 | **Priority:** Must-have

---

### Dev Component (US-05 through US-11, US-26)

#### US-05: Dev Implements PRD

> As a developer, I want to pass a PRD to the dev component and have it implement the feature on a new git branch

**Acceptance Criteria:**
- [ ] `dkmv dev --prd login.md --repo git@github.com:user/app.git` works
- [ ] Clones repo, creates `feature/<name>-dev` branch
- [ ] Implements PRD, commits, pushes

**Feature:** F7 | **Tasks:** T060-T072 | **Priority:** Must-have

---

#### US-06: Real-time Streaming

> As a developer, I want to see real-time streaming output of what the agent is doing

**Acceptance Criteria:**
- [ ] Terminal shows Claude's reasoning, file edits, and command output as they happen
- [ ] stream-json parsing renders formatted output

**Feature:** F5, F7 | **Tasks:** T046-T049, T063 | **Priority:** Must-have

---

#### US-07: Dev Self-iteration

> As a developer, I want the dev agent to iterate on its own work — run tests, fix failures, retry

**Acceptance Criteria:**
- [ ] Claude Code's built-in agent loop handles test-fix cycles
- [ ] Prompt instructs agent to run tests and fix failures

**Feature:** F7 | **Tasks:** T063 | **Priority:** Must-have

---

#### US-08: Continue on Existing Branch

> As a developer, I want to continue development on an existing branch (iteration after Judge feedback)

**Acceptance Criteria:**
- [ ] `dkmv dev --prd login.md --repo ... --branch feature/login-dev` checks out existing branch
- [ ] Does not create a new branch

**Feature:** F7 | **Tasks:** T070 | **Priority:** Must-have

---

#### US-09: Feedback from Judge

> As a developer, I want to provide feedback from a previous Judge run to guide the dev agent

**Acceptance Criteria:**
- [ ] `--feedback verdict.json` injects Judge feedback into prompt
- [ ] Feedback is synthesized (not raw verdict)

**Feature:** F7 | **Tasks:** T067 | **Priority:** Must-have

---

#### US-10: Model Selection

> As a developer, I want to control which Claude model the agent uses

**Acceptance Criteria:**
- [ ] `--model claude-sonnet-4-20250514` flag works
- [ ] Defaults to configured model

**Feature:** F7 | **Tasks:** T069 | **Priority:** Should-have

---

#### US-11: Max-turns Limit

> As a developer, I want to set a max-turns limit to control cost

**Acceptance Criteria:**
- [ ] `--max-turns 50` flag works
- [ ] Defaults to sensible limit from config

**Feature:** F7 | **Tasks:** T069 | **Priority:** Should-have

---

#### US-26: Design Documents

> As a developer, I want to provide supplementary design documents so the Dev agent has richer context beyond the PRD

**Acceptance Criteria:**
- [ ] `--design-docs PATH` accepts a directory or glob
- [ ] Files copied to `.dkmv/design_docs/` as read-only context

**Feature:** F7 | **Tasks:** T066 | **Priority:** Should-have

---

### QA Component (US-12 through US-14)

#### US-12: QA Validates Branch

> As a developer, I want to run QA against a branch to validate it meets the PRD requirements

**Acceptance Criteria:**
- [ ] `dkmv qa --branch feature/login-dev --repo ... --prd login.md` works
- [ ] Clones repo, checks out branch, runs comprehensive QA, produces report

**Feature:** F8 | **Tasks:** T073-T077 | **Priority:** Must-have

---

#### US-13: QA Runs Tests & Evaluates

> As a developer, I want the QA agent to run existing tests AND evaluate code quality against the PRD

**Acceptance Criteria:**
- [ ] QA prompt instructs agent to: run test suite, check regressions, evaluate PRD coverage, review code quality
- [ ] Evaluation criteria section included in QA prompt

**Feature:** F8 | **Tasks:** T075 | **Priority:** Must-have

---

#### US-14: QA Report Saved

> As a developer, I want the QA report saved both to git and locally

**Acceptance Criteria:**
- [ ] QA report committed to branch as `.dkmv/qa_report.json`
- [ ] Also saved in `outputs/runs/<run-id>/`

**Feature:** F8 | **Tasks:** T075-T076 | **Priority:** Must-have

---

### Judge Component (US-15 through US-17)

#### US-15: Judge Evaluates Pass/Fail

> As a developer, I want an independent Judge to evaluate whether the implementation passes

**Acceptance Criteria:**
- [ ] `dkmv judge --branch ... --repo ... --prd ...` works
- [ ] Reviews code + QA report, produces pass/fail verdict with reasoning

**Feature:** F9 | **Tasks:** T078-T082 | **Priority:** Must-have

---

#### US-16: Structured Judge Output

> As a developer, I want structured Judge output that I can feed back to Dev

**Acceptance Criteria:**
- [ ] Verdict JSON includes: pass/fail, reasoning, issues array (file, line, description, severity), suggestions
- [ ] Can be passed via `dkmv dev --feedback`

**Feature:** F9 | **Tasks:** T080 | **Priority:** Must-have

---

#### US-17: Judge Independence

> As a developer, I want the Judge to be strict and independent

**Acceptance Criteria:**
- [ ] Judge has no access to Dev's reasoning or internal process
- [ ] Evaluates only code, tests, and QA report

**Feature:** F9 | **Tasks:** T080 | **Priority:** Must-have

---

### Docs Component (US-18 through US-19)

#### US-18: Documentation Generation

> As a developer, I want the Docs agent to generate documentation for the implemented feature

**Acceptance Criteria:**
- [ ] `dkmv docs --branch ... --repo ...` generates/updates docs
- [ ] Commits documentation to branch

**Feature:** F10 | **Tasks:** T083-T086 | **Priority:** Should-have

---

#### US-19: Auto-create PR

> As a developer, I want the option to auto-create a PR

**Acceptance Criteria:**
- [ ] `--create-pr` flag opens a PR from feature branch to main
- [ ] PR includes description and summary

**Feature:** F10 | **Tasks:** T085 | **Priority:** Should-have

---

### Run Management & Observability (US-20 through US-25)

#### US-20: List Runs

> As a developer, I want to list all my previous runs

**Acceptance Criteria:**
- [ ] `dkmv runs` shows table: run-id, component, repo, branch, status, duration, cost, timestamp

**Feature:** F11 | **Tasks:** T090 | **Priority:** Should-have

---

#### US-21: Inspect Run Details

> As a developer, I want to inspect a specific run's details

**Acceptance Criteria:**
- [ ] `dkmv show <run-id>` shows full details: config, cost, duration, exit status, branch, log path

**Feature:** F11 | **Tasks:** T091 | **Priority:** Should-have

---

#### US-22: Attach to Container

> As a developer, I want to attach to a running container to see what's happening

**Acceptance Criteria:**
- [ ] `dkmv attach <run-id>` execs into running container with bash
- [ ] Requires `--keep-alive` on original run

**Feature:** F3, F11 | **Tasks:** T034, T092 | **Priority:** Nice-to-have

---

#### US-23: Keep Container Alive

> As a developer, I want to keep a container alive after a run for debugging

**Acceptance Criteria:**
- [ ] `--keep-alive` flag prevents container teardown

**Feature:** F3, F11 | **Tasks:** T035, T092 | **Priority:** Nice-to-have

---

#### US-24: Stop Keep-alive Container

> As a developer, I want to stop a keep-alive container when I'm done

**Acceptance Criteria:**
- [ ] `dkmv stop <run-id>` stops and removes the container

**Feature:** F3, F11 | **Tasks:** T035, T093 | **Priority:** Nice-to-have

---

#### US-25: Cost Tracking

> As a developer, I want to know how much each run cost

**Acceptance Criteria:**
- [ ] Every run's result.json includes `total_cost_usd`
- [ ] Extracted from Claude Code's stream-json final message

**Feature:** F4 | **Tasks:** T042, T044 | **Priority:** Must-have
