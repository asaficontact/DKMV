# DKMV End-to-End Test Guide: To-Do App

This guide walks you through testing every DKMV component end-to-end using a simple to-do app PRD. Each step includes the exact command to run, what to verify, and what to look for if something goes wrong.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Setup](#2-setup)
3. [The To-Do App PRD](#3-the-to-do-app-prd)
4. [Phase 1: Build the Docker Image](#4-phase-1-build-the-docker-image)
5. [Phase 2: Run Dev Agent](#5-phase-2-run-dev-agent)
6. [Phase 3: Run QA Agent](#6-phase-3-run-qa-agent)
7. [Phase 4: Run Judge Agent](#7-phase-4-run-judge-agent)
8. [Phase 5: Run Docs Agent](#8-phase-5-run-docs-agent)
9. [Phase 6: Run Management Commands](#9-phase-6-run-management-commands)
10. [Phase 7: Feedback Loop (Optional)](#10-phase-7-feedback-loop-optional)
11. [Verification Checklist](#11-verification-checklist)
12. [Troubleshooting](#12-troubleshooting)
13. [Cost Estimates](#13-cost-estimates)

---

## 1. Prerequisites

Before starting, confirm you have:

| Requirement | Check Command | Expected |
|-------------|---------------|----------|
| Python 3.12+ | `python3 --version` | 3.12.x or higher |
| uv installed | `uv --version` | 0.4+ |
| Docker running | `docker info` | No errors |
| Anthropic API key | `echo $ANTHROPIC_API_KEY` | Starts with `sk-ant-` |
| GitHub token | `echo $GITHUB_TOKEN` | Starts with `ghp_` or `github_pat_` |
| GitHub CLI | `gh auth status` | Logged in |
| Git configured | `git config user.name` | Your name |

**GitHub token scopes needed:** `repo` (full access to private/public repos).

---

## 2. Setup

### 2.1 Install DKMV

```bash
cd /Users/tawab/Projects/DKMV
uv sync
uv run dkmv --help   # Verify CLI works
```

### 2.2 Configure Environment

Create or update your `.env` file in the DKMV project root:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-your-key-here
GITHUB_TOKEN=ghp_your-token-here

# Recommended for testing (lower cost, faster)
DKMV_MODEL=claude-sonnet-4-20250514
DKMV_MAX_TURNS=50
DKMV_TIMEOUT=15
DKMV_MEMORY=8g
```

### 2.3 Create a Test Repository on GitHub

You need a real GitHub repository for DKMV to clone into containers. Create a minimal Python project:

```bash
# Create a new directory outside DKMV
mkdir ~/Projects/todo-app-test
cd ~/Projects/todo-app-test

# Initialize git
git init
```

Create `pyproject.toml`:
```toml
[project]
name = "todo-app"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Create the directory structure:
```bash
mkdir -p src/todo tests
touch src/__init__.py
touch src/todo/__init__.py
touch tests/__init__.py
```

Create a placeholder `src/todo/app.py`:
```python
"""To-Do App — placeholder for DKMV Dev agent to implement."""
```

Create a placeholder test `tests/test_placeholder.py`:
```python
def test_placeholder():
    """Placeholder test — DKMV Dev agent will add real tests."""
    assert True
```

Push to GitHub:
```bash
git add -A
git commit -m "chore: initial project scaffold"
gh repo create todo-app-test --public --source=. --push
```

**Save the repo URL** — you'll use it in every command:
```
https://github.com/<your-username>/todo-app-test
```

### 2.4 Create the PRD File

Create `todo_prd.md` in the DKMV project root (full PRD content in [Section 3](#3-the-to-do-app-prd) below):

```bash
# The PRD is provided in the next section — copy it to this file
touch /Users/tawab/Projects/DKMV/todo_prd.md
```

---

## 3. The To-Do App PRD

Copy this into `/Users/tawab/Projects/DKMV/todo_prd.md`:

```markdown
# To-Do App — Feature PRD

## Summary

Build a simple command-line to-do application in Python. The app should allow users
to add, list, complete, and delete tasks. Tasks are stored in a local JSON file.

## Requirements

### Core Functionality

1. **Add a task**: Users can add a new task with a title and optional description.
   - Each task gets a unique auto-incrementing integer ID.
   - New tasks default to "pending" status.
   - Tasks are immediately persisted to `todos.json`.

2. **List tasks**: Users can list all tasks or filter by status.
   - Default shows all tasks in a readable format.
   - Support `--status pending` and `--status done` filters.
   - Show task ID, title, status, and creation date.
   - Show a message when no tasks exist.

3. **Complete a task**: Users can mark a task as done by its ID.
   - Accept task ID as argument.
   - Print confirmation message.
   - Error gracefully if task ID does not exist.

4. **Delete a task**: Users can delete a task by its ID.
   - Accept task ID as argument.
   - Print confirmation message.
   - Error gracefully if task ID does not exist.

### Data Model

- Tasks are stored as JSON in `todos.json` in the current directory.
- Each task has: `id` (int), `title` (str), `description` (str), `status` ("pending" | "done"), `created_at` (ISO 8601 datetime string).
- The JSON file contains a list of task objects.

### Interface

- The app is a Python module runnable via `python -m todo`.
- Commands: `add`, `list`, `complete`, `delete`.
- Usage examples:
  ```
  python -m todo add "Buy groceries" --description "Milk, eggs, bread"
  python -m todo list
  python -m todo list --status pending
  python -m todo complete 1
  python -m todo delete 2
  ```

### Code Quality

- All code in `src/todo/` package.
- Type hints on all functions.
- No external dependencies (stdlib only for the app itself).
- pytest for testing.

## Evaluation Criteria

> **Note:** This section is hidden from the Dev agent and only visible to QA and Judge.

1. All four commands work correctly: add, list, complete, delete.
2. Tasks persist across invocations (stored in todos.json).
3. Error handling works for invalid task IDs.
4. Status filtering works on the list command.
5. At least 5 unit tests exist and all pass.
6. Code uses type hints on all function signatures.
7. The app is runnable via `python -m todo`.
8. JSON file format matches the data model specification.
```

---

## 4. Phase 1: Build the Docker Image

### Command

```bash
uv run dkmv build
```

### What to Verify

| Check | How | Expected |
|-------|-----|----------|
| Build succeeds | Command exits without error | "Image dkmv-sandbox:latest built successfully." |
| Image exists | `docker images \| grep dkmv-sandbox` | Shows `dkmv-sandbox latest` |
| Image works | `docker run --rm dkmv-sandbox:latest echo "OK"` | Prints "OK" |
| Claude installed | `docker run --rm dkmv-sandbox:latest claude --version` | Prints version number |
| SWE-ReX installed | `docker run --rm dkmv-sandbox:latest swerex-remote --help` | Shows help text |
| User correct | `docker run --rm dkmv-sandbox:latest whoami` | Prints "dkmv" |
| gh installed | `docker run --rm dkmv-sandbox:latest gh --version` | Prints version |

### If Something Goes Wrong

- **"Docker is not installed"** — Start Docker Desktop or the Docker daemon.
- **Build hangs at npm install** — Check network connectivity. Try `--no-cache`.
- **Out of disk space** — `docker system prune` to clean up old images.

---

## 5. Phase 2: Run Dev Agent

The Dev agent reads the PRD, implements the to-do app, writes tests, and pushes code to a feature branch.

### Command

```bash
uv run dkmv dev \
  https://github.com/<your-username>/todo-app-test \
  --prd ./todo_prd.md \
  --branch feature/todo-app \
  --feature-name "todo-app" \
  --timeout 15 \
  --max-turns 50 \
  --keep-alive
```

**Important flags:**
- `--keep-alive` — Keeps the container running after completion so you can inspect it.
- `--timeout 15` — 15-minute timeout (sufficient for this small task).
- `--max-turns 50` — Limit agent turns to control cost.

### What to Watch During Execution

The CLI will stream Claude Code's output in real-time. You should see:
1. Container starting
2. Git clone of your repo
3. Claude reading the PRD
4. Claude creating a plan at `.agent/plan.md`
5. Claude implementing the to-do app code
6. Claude writing tests
7. Claude running tests
8. Git commit and push
9. Run completion with cost summary

### What to Verify After Completion

**1. Check the run status:**
```bash
uv run dkmv runs
```
Expected: A table showing your run with status `completed`.

**2. Check run details:**
```bash
uv run dkmv show <run-id>
```
Look for:
- Status: `completed`
- Cost: Should be under $1 for this small task
- Turns: How many turns Claude used

**3. Inspect the container (since you used --keep-alive):**
```bash
uv run dkmv attach <run-id>
```

Once inside the container:
```bash
cd /home/dkmv/workspace

# Check what Claude built
ls src/todo/
# Expected: __init__.py, app.py (or similar), __main__.py

# Check if tests exist
ls tests/
# Expected: test_*.py files

# Run the tests inside the container
cd /home/dkmv/workspace && python -m pytest tests/ -v
# Expected: All tests pass

# Try the app
python -m todo add "Buy groceries"
python -m todo list
python -m todo complete 1
python -m todo list --status done
python -m todo delete 1

# Check the plan Claude created
cat .agent/plan.md

# Check the PRD that was injected (should NOT have Evaluation Criteria)
cat .agent/prd.md
# Verify: "Evaluation Criteria" section is NOT present

# Exit the container
exit
```

**4. Check the GitHub branch:**
```bash
cd ~/Projects/todo-app-test
git fetch origin
git log origin/feature/todo-app --oneline
# Expected: Commit(s) with message like "feat(dev): todo-app [dkmv-dev]"

git diff main..origin/feature/todo-app --stat
# Expected: New files in src/todo/ and tests/
```

**5. Check local run artifacts:**
```bash
ls outputs/runs/<run-id>/
# Expected: config.json, prompt.md, stream.jsonl, result.json, container.txt
```

Read the result:
```bash
cat outputs/runs/<run-id>/result.json | python -m json.tool
```
Look for: `"status": "completed"`, `"files_changed"`, `"tests_passed"`

**6. Stop the container when done inspecting:**
```bash
uv run dkmv stop <run-id>
```

### Success Criteria for Dev Phase

- [ ] Run completed without errors
- [ ] Code pushed to `feature/todo-app` branch
- [ ] `src/todo/` contains implementation files
- [ ] `tests/` contains test files
- [ ] Tests pass inside the container
- [ ] The to-do app commands work (`add`, `list`, `complete`, `delete`)
- [ ] `.agent/plan.md` was created (plan-first approach)
- [ ] Evaluation Criteria was stripped from the PRD visible to Claude
- [ ] Local artifacts saved in `outputs/runs/<run-id>/`

---

## 6. Phase 3: Run QA Agent

The QA agent clones the same branch, reads the **full PRD** (including Evaluation Criteria), runs tests, and produces a QA report.

### Command

```bash
uv run dkmv qa \
  https://github.com/<your-username>/todo-app-test \
  --branch feature/todo-app \
  --prd ./todo_prd.md \
  --timeout 15 \
  --max-turns 50 \
  --keep-alive
```

### What to Watch During Execution

You should see:
1. Container starting (fresh container — not the Dev one)
2. Git clone of the repo + checkout of `feature/todo-app`
3. Claude reading the full PRD (including Evaluation Criteria this time)
4. Claude exploring the code that Dev wrote
5. Claude running the test suite
6. Claude evaluating each requirement and eval criterion
7. Claude writing `.agent/qa_report.json`
8. Git commit and push of the report

### What to Verify After Completion

**1. Check run status:**
```bash
uv run dkmv runs
```
Expected: Two runs now — dev (completed) and qa (completed).

**2. Inspect the container:**
```bash
uv run dkmv attach <run-id>
```

Inside the container:
```bash
cd /home/dkmv/workspace

# Check the QA report
cat .agent/qa_report.json | python3 -m json.tool
```

**QA report should contain:**
- `tests_total` — Total number of tests found
- `tests_passed` — Number passing
- `tests_failed` — Number failing
- `requirements` — Array of requirement evaluations with `status: "pass"|"fail"|"partial"`
- `eval_criteria` — Array of eval criteria evaluations
- `code_quality` — Code quality assessment
- `summary` — Overall assessment text

```bash
# Check the PRD that QA received (should INCLUDE Evaluation Criteria)
cat .agent/prd.md
# Verify: "Evaluation Criteria" section IS present

exit
```

**3. Check the QA report was pushed to the branch:**
```bash
cd ~/Projects/todo-app-test
git fetch origin
git log origin/feature/todo-app --oneline -5
# Expected: New commit like "feat(qa): todo-app [dkmv-qa]"
```

**4. Check local artifacts:**
```bash
cat outputs/runs/<qa-run-id>/result.json | python -m json.tool
```
Look for: `"tests_total"`, `"tests_passed"`, `"tests_failed"`, `"warnings"`

**5. Stop the container:**
```bash
uv run dkmv stop <run-id>
```

### Success Criteria for QA Phase

- [ ] Run completed without errors
- [ ] QA report committed and pushed to `feature/todo-app` branch
- [ ] `.agent/qa_report.json` exists on the branch
- [ ] QA received the full PRD (including Evaluation Criteria)
- [ ] Report contains test results (total, passed, failed)
- [ ] Report evaluates each requirement
- [ ] Report evaluates each evaluation criterion
- [ ] QA ran in a fresh container (completely independent of Dev)

---

## 7. Phase 4: Run Judge Agent

The Judge agent independently evaluates the implementation quality and produces a pass/fail verdict with a confidence score.

### Command

```bash
uv run dkmv judge \
  https://github.com/<your-username>/todo-app-test \
  --branch feature/todo-app \
  --prd ./todo_prd.md \
  --timeout 15 \
  --max-turns 50 \
  --keep-alive
```

### What to Watch During Execution

You should see:
1. Container starting (yet another fresh container)
2. Git clone + checkout of `feature/todo-app`
3. Claude reading full PRD (including Evaluation Criteria)
4. Claude independently reviewing the implementation
5. Claude running tests
6. Claude evaluating each PRD requirement
7. Claude producing verdict at `.agent/verdict.json`
8. **Verdict display**: The CLI prints `VERDICT: PASS` or `VERDICT: FAIL` with score and reasoning

### What to Verify After Completion

**1. Check the verdict display:**
The CLI should have printed something like:
```
VERDICT: PASS
Reasoning: All requirements are implemented correctly...
Score: 88/100
Confidence: 92%
```
Or:
```
VERDICT: FAIL
Reasoning: Missing error handling for...
Score: 55/100
Confidence: 85%
  [HIGH] Missing validation for empty task title
  [MEDIUM] No error message for invalid status filter
```

**2. Inspect the container:**
```bash
uv run dkmv attach <run-id>
```

Inside the container:
```bash
cd /home/dkmv/workspace

# Check the verdict
cat .agent/verdict.json | python3 -m json.tool
```

**Verdict should contain:**
- `verdict` — `"pass"` or `"fail"`
- `confidence` — 0.0 to 1.0
- `reasoning` — Detailed explanation
- `prd_requirements` — Array with status per requirement (`"implemented"`, `"missing"`, `"partial"`)
- `issues` — Array of issues found (severity, description, file, line, suggestion)
- `suggestions` — Improvement recommendations
- `score` — 0-100 overall quality score

```bash
exit
```

**3. Check verdict pushed to branch:**
```bash
cd ~/Projects/todo-app-test
git fetch origin
git log origin/feature/todo-app --oneline -5
# Expected: New commit like "feat(judge): todo-app [dkmv-judge]"
```

**4. Check local artifacts:**
```bash
cat outputs/runs/<judge-run-id>/result.json | python -m json.tool
```
Look for: `"verdict"`, `"confidence"`, `"score"`, `"issues"`, `"prd_requirements"`

**5. Stop the container:**
```bash
uv run dkmv stop <run-id>
```

### Success Criteria for Judge Phase

- [ ] Run completed without errors
- [ ] Verdict displayed in CLI (PASS or FAIL with score)
- [ ] `.agent/verdict.json` committed and pushed to branch
- [ ] Verdict includes confidence score (0.0-1.0)
- [ ] Verdict includes score (0-100)
- [ ] Each PRD requirement has an implementation status
- [ ] Issues list has severity levels (critical/high/medium/low)
- [ ] Judge ran independently (fresh container, own assessment)

---

## 8. Phase 5: Run Docs Agent

The Docs agent generates documentation for the to-do app and optionally creates a PR.

### Command

```bash
uv run dkmv docs \
  https://github.com/<your-username>/todo-app-test \
  --branch feature/todo-app \
  --create-pr \
  --pr-base main \
  --timeout 15 \
  --max-turns 30 \
  --keep-alive
```

**Important flags:**
- `--create-pr` — Tells the agent to create a GitHub PR after generating docs.
- `--pr-base main` — The PR targets `main` as the base branch.

### What to Watch During Execution

You should see:
1. Container starting (fresh container)
2. Git clone + checkout of `feature/todo-app`
3. Claude exploring the codebase
4. Claude generating/updating README.md and other docs
5. Git commit and push
6. PR creation via `gh pr create`
7. PR URL printed to console

### What to Verify After Completion

**1. Check the PR URL:**
The CLI should print something like:
```
PR created: https://github.com/<your-username>/todo-app-test/pull/1
```

**2. Inspect the container:**
```bash
uv run dkmv attach <run-id>
```

Inside the container:
```bash
cd /home/dkmv/workspace

# Check what docs were created/updated
git diff HEAD~1 --stat
# Expected: README.md and possibly other doc files

# Read the generated README
cat README.md

exit
```

**3. Check the PR on GitHub:**
Open the PR URL in your browser. Verify:
- PR title contains "docs" or "documentation"
- PR body describes the documentation changes
- PR targets `main` branch
- Changed files include documentation updates

**4. Check local artifacts:**
```bash
cat outputs/runs/<docs-run-id>/result.json | python -m json.tool
```
Look for: `"docs_generated"` (list of files), `"pr_url"` (GitHub PR URL)

**5. Stop the container:**
```bash
uv run dkmv stop <run-id>
```

### Success Criteria for Docs Phase

- [ ] Run completed without errors
- [ ] Documentation files created/updated on the branch
- [ ] PR created on GitHub (if `--create-pr` used)
- [ ] PR URL printed in CLI output
- [ ] PR targets the correct base branch (`main`)
- [ ] Generated docs are accurate to the implementation

---

## 9. Phase 6: Run Management Commands

Test all the utility commands to verify they work correctly.

### 9.1 List Runs

```bash
# List all runs
uv run dkmv runs

# Filter by component
uv run dkmv runs --component dev
uv run dkmv runs --component qa

# Filter by status
uv run dkmv runs --status completed

# Limit results
uv run dkmv runs --limit 2
```

**Verify:** Table shows all 4 runs (dev, qa, judge, docs) with correct statuses, costs, and durations.

### 9.2 Show Run Details

```bash
# Pick any run ID from the list
uv run dkmv show <run-id>
```

**Verify:** Shows run ID, component, status, repo, branch, model, cost, duration, turns, session ID, events count.

### 9.3 Attach to Container (if any still running)

If you still have a `--keep-alive` container:
```bash
uv run dkmv attach <run-id>
```

**Verify:** Drops you into a bash shell inside the container.

### 9.4 Stop a Container

```bash
uv run dkmv stop <run-id>
```

**Verify:** Prints "Container stopped and removed."

### 9.5 Stop an Already-Stopped Container

```bash
uv run dkmv stop <run-id>
```

**Verify:** Prints "already removed" (idempotent, no error).

### 9.6 Show/Attach with Invalid Run ID

```bash
uv run dkmv show nonexistent-id
uv run dkmv attach nonexistent-id
uv run dkmv stop nonexistent-id
```

**Verify:** All print "not found" with exit code 1.

---

## 10. Phase 7: Feedback Loop (Optional)

If the Judge gave a `FAIL` verdict, you can feed the issues back to Dev for iteration.

### 10.1 Extract Feedback from Judge Verdict

The Judge's verdict is at `.agent/verdict.json` on the branch. You can use it directly as feedback:

```bash
# Pull the verdict from the branch
cd ~/Projects/todo-app-test
git fetch origin
git checkout origin/feature/todo-app -- .agent/verdict.json
cp .agent/verdict.json /Users/tawab/Projects/DKMV/todo_feedback.json
git checkout -- .   # Clean up
cd /Users/tawab/Projects/DKMV
```

### 10.2 Re-run Dev with Feedback

```bash
uv run dkmv dev \
  https://github.com/<your-username>/todo-app-test \
  --prd ./todo_prd.md \
  --branch feature/todo-app \
  --feature-name "todo-app" \
  --feedback ./todo_feedback.json \
  --timeout 15 \
  --max-turns 50
```

**What happens:**
1. Dev clones the **existing** `feature/todo-app` branch (with all previous code)
2. The feedback JSON is written to `.agent/feedback.json` inside the container
3. The prompt includes: "Review the feedback from a previous review cycle at `.agent/feedback.json` and address all issues raised."
4. Claude reads the issues from the Judge and fixes them
5. New commit pushed to the same branch

### 10.3 Re-run QA and Judge

After Dev fixes the issues, run QA and Judge again:

```bash
# QA re-evaluation
uv run dkmv qa \
  https://github.com/<your-username>/todo-app-test \
  --branch feature/todo-app \
  --prd ./todo_prd.md \
  --timeout 15

# Judge re-evaluation
uv run dkmv judge \
  https://github.com/<your-username>/todo-app-test \
  --branch feature/todo-app \
  --prd ./todo_prd.md \
  --timeout 15
```

**Verify:** The Judge should now give a higher score or a `PASS` verdict.

---

## 11. Verification Checklist

### End-to-End Flow

```
                    ┌───────────────────────┐
                    │  1. dkmv build        │
                    │  Docker image created  │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  2. dkmv dev          │
                    │  Code implemented      │
                    │  Tests written          │
                    │  Pushed to branch       │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  3. dkmv qa           │
                    │  Tests run             │
                    │  Requirements checked   │
                    │  QA report pushed       │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  4. dkmv judge        │
                    │  Independent review    │
                    │  Verdict + score       │
                    │  Verdict pushed         │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  5. dkmv docs         │
                    │  Docs generated        │
                    │  PR created            │
                    └───────────────────────┘
```

### Master Checklist

**Infrastructure:**
- [ ] Docker image builds successfully
- [ ] Container starts and runs basic commands
- [ ] Claude Code is installed and working in container
- [ ] SWE-ReX server starts in container

**Dev Agent:**
- [ ] Clones repo and creates/checks out branch
- [ ] Strips Evaluation Criteria from PRD
- [ ] Creates `.agent/plan.md` before implementing
- [ ] Implements all 4 commands (add, list, complete, delete)
- [ ] Writes unit tests
- [ ] Tests pass
- [ ] Commits with `[dkmv-dev]` suffix
- [ ] Pushes to `feature/todo-app` branch

**QA Agent:**
- [ ] Clones repo with Dev's code (fresh container)
- [ ] Receives full PRD (including Evaluation Criteria)
- [ ] Runs tests and reports results
- [ ] Evaluates each requirement
- [ ] Evaluates each evaluation criterion
- [ ] Produces `.agent/qa_report.json`
- [ ] Commits report to branch

**Judge Agent:**
- [ ] Clones repo with Dev's code (fresh container)
- [ ] Forms independent assessment
- [ ] Produces pass/fail verdict
- [ ] Includes confidence and score
- [ ] Evaluates each PRD requirement
- [ ] Lists issues with severity
- [ ] Produces `.agent/verdict.json`
- [ ] CLI displays verdict summary

**Docs Agent:**
- [ ] Clones repo (fresh container)
- [ ] Generates useful documentation
- [ ] Creates PR on GitHub (when `--create-pr` used)
- [ ] PR URL displayed in output

**Run Management:**
- [ ] `dkmv runs` lists all runs
- [ ] `dkmv runs --component dev` filters correctly
- [ ] `dkmv runs --status completed` filters correctly
- [ ] `dkmv show <id>` displays run details
- [ ] `dkmv attach <id>` opens shell in container
- [ ] `dkmv stop <id>` removes container
- [ ] Invalid run IDs produce helpful errors

**Component Isolation:**
- [ ] Each component runs in its own container
- [ ] Components share state ONLY via the git branch
- [ ] No container has access to another container's filesystem
- [ ] Each container is destroyed after use (unless --keep-alive)

---

## 12. Troubleshooting

### Container fails to start

```
Error: Failed to launch Claude Code: no PID returned
```

**Cause:** SWE-ReX couldn't start the container or create a session.
**Fix:** Check Docker is running. Check `docker logs` on the container. Try `docker run --rm dkmv-sandbox:latest echo "test"`.

### Git clone fails

```
git clone failed (exit 128): ...
```

**Cause:** Authentication issue or repo doesn't exist.
**Fix:** Verify `GITHUB_TOKEN` is set and has `repo` scope. Verify the repo URL is correct. Try `gh repo view <url>` to confirm access.

### Claude Code times out

```
Component timed out
```

**Cause:** Timeout too short for the task.
**Fix:** Increase `--timeout` (try 30 or 45 minutes). Check if Claude was stuck in a loop (inspect `stream.jsonl`).

### Tests fail inside container

If tests fail during the Dev agent run, that's expected behavior — Claude should iterate and fix them. If tests still fail at the end:

**Inspect:** Use `--keep-alive` and `dkmv attach` to enter the container and debug manually.

### QA/Judge report not created

If `.agent/qa_report.json` or `.agent/verdict.json` is missing:

**Cause:** Claude may not have followed the prompt instructions to create the artifact.
**Inspect:** Check `stream.jsonl` for what Claude actually did. Check if the file exists under a different name.

### PR creation fails

```
Warning: gh pr create failed
```

**Cause:** `GITHUB_TOKEN` missing or insufficient permissions, or PR already exists.
**Fix:** Verify `gh auth status` works. Check if a PR already exists for this branch.

### Run shows "failed" status

```bash
uv run dkmv show <run-id>
# Status: failed
# Error: <message>
```

**Fix:** Read the error message. Check `outputs/runs/<run-id>/stream.jsonl` for the full Claude output. Use `--keep-alive` on the next attempt to inspect the container state.

### High costs

**Mitigation:** Use `--max-turns 30` and `--max-budget-usd 2.0` to cap costs. Use `claude-sonnet-4-20250514` (default) instead of opus models for testing.

---

## 13. Cost Estimates

Estimated costs for the to-do app PRD using `claude-sonnet-4-20250514`:

| Component | Estimated Turns | Estimated Cost |
|-----------|----------------|----------------|
| Dev | 15-30 | $0.50-$2.00 |
| QA | 10-20 | $0.30-$1.00 |
| Judge | 10-20 | $0.30-$1.00 |
| Docs | 5-15 | $0.20-$0.50 |
| **Total** | **40-85** | **$1.30-$4.50** |

**Cost control flags:**
- `--max-budget-usd 2.0` — Hard cap per invocation
- `--max-turns 30` — Limits iteration cycles
- `--timeout 15` — Prevents runaway runs

**To minimize cost during testing:**
- Start with Dev only. Verify it works before running QA/Judge/Docs.
- Use `--max-turns 30` for initial tests.
- Use `--max-budget-usd 2.0` as a safety net.
