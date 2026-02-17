# Phase 4: Utilities

## Prerequisites

- Phase 2 complete (RunManager with list_runs, get_run)
- SandboxManager with start/stop working
- At least one component producing runs for testing

## Phase Goal

Run management commands are operational: users can list, inspect, attach to, and stop runs from the CLI.

## Phase Evaluation Criteria

- `dkmv runs` shows formatted table of past runs
- `dkmv show <run-id>` displays detailed run information
- `dkmv attach <run-id>` connects to running container (with keep-alive)
- `dkmv stop <run-id>` stops and removes keep-alive containers
- `uv run pytest tests/unit/test_run_commands.py -v` passes

---

## Tasks

### T090: Implement dkmv runs

**PRD Reference:** Section 6/F11
**Depends on:** T043 (list_runs)
**Blocks:** T094
**User Stories:** US-20
**Estimated scope:** 1-2 hours

#### Description

Implement the `dkmv runs` command that displays a rich table of recent runs.

#### Acceptance Criteria

- [ ] Shows table columns: ID, COMPONENT, REPO, BRANCH, STATUS, COST, DURATION, WHEN
- [ ] Uses rich Table for formatted output
- [ ] Optional filters: `--component dev|qa|judge|docs`, `--limit N`, `--status pending|running|completed|failed|timed_out`
- [ ] Shows "No runs found" when empty
- [ ] Cost formatted as `$X.XX`
- [ ] Duration formatted as `Xm Ys`
- [ ] Timestamp formatted as relative time ("2h ago")

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Replace runs stub with implementation

#### Implementation Notes

Use `rich.table.Table` for output. Use RunManager.list_runs() for data. Format cost with `f"${cost:.2f}"`. For relative time, use `datetime` calculations or a small helper.

NOTE: The `--status` filter uses the `RunStatus` type alias values from `dkmv/core/models.py`:
`pending`, `running`, `completed`, `failed`, `timed_out`. These intentionally differ from the PRD's
`success|failure|error|running` — see T030 implementation notes for rationale.

#### Evaluation Checklist

- [ ] `dkmv runs` shows formatted table
- [ ] Filters work correctly
- [ ] Empty state handled gracefully
- [ ] No lint or type errors

---

### T091: Implement dkmv show

**PRD Reference:** Section 6/F11
**Depends on:** T043 (get_run)
**Blocks:** T094
**User Stories:** US-21
**Estimated scope:** 1 hour

#### Description

Implement the `dkmv show <run-id>` command that displays detailed information about a specific run.

#### Acceptance Criteria

- [ ] Shows: run ID, component, status, repo, branch, model, cost, duration, turns
- [ ] Shows: files changed (if available)
- [ ] Shows: log file path, stream file path
- [ ] Shows: session_id (if available)
- [ ] Shows: error message (if status is error)
- [ ] Helpful error if run-id not found

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Replace show stub with implementation

#### Implementation Notes

Use `rich.panel.Panel` or `rich.console.Console.print()` with formatted output. Use RunManager.get_run() for data.

#### Evaluation Checklist

- [ ] `dkmv show <valid-id>` displays details
- [ ] `dkmv show <invalid-id>` shows helpful error

---

### T092: Implement dkmv attach

**PRD Reference:** Section 6/F11
**Depends on:** T031 (SandboxManager)
**Blocks:** T094
**User Stories:** US-22, US-23
**Estimated scope:** 1 hour

#### Description

Implement the `dkmv attach <run-id>` command that execs into a running container.

#### Acceptance Criteria

- [ ] Looks up container name from run metadata
- [ ] Runs `docker exec -it <container> bash`
- [ ] Fails with clear message if container not running
- [ ] Fails with clear message if run used without `--keep-alive`

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Replace attach stub with implementation

#### Implementation Notes

Use `subprocess.run(["docker", "exec", "-it", container_name, "bash"])` or `os.execvp` for proper TTY passthrough. Check container status first with `docker inspect`.

#### Evaluation Checklist

- [ ] Attach works on running container
- [ ] Clear error when container not running

---

### T093: Implement dkmv stop

**PRD Reference:** Section 6/F11
**Depends on:** T035 (stop)
**Blocks:** T094
**User Stories:** US-24
**Estimated scope:** 30 min

#### Description

Implement the `dkmv stop <run-id>` command that stops and removes a keep-alive container.

#### Acceptance Criteria

- [ ] Looks up container from run metadata
- [ ] Stops and removes the container
- [ ] Updates run status if applicable
- [ ] Clear message on success: "Container stopped and removed"
- [ ] Clear message if container already stopped

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Replace stop stub with implementation

#### Implementation Notes

Use SandboxManager.stop() or fall back to `docker stop <container> && docker rm <container>`. Check container existence first.

#### Evaluation Checklist

- [ ] Container stopped and removed
- [ ] Idempotent (no error on already-stopped)

---

### T094: Write Run Management Command Tests

**PRD Reference:** Section 8/Task 4.1
**Depends on:** T090-T093
**Blocks:** T095
**User Stories:** N/A
**Estimated scope:** 2 hours

#### Description

Write unit tests for all run management commands.

#### Acceptance Criteria

- [ ] Test: `dkmv runs` output format
- [ ] Test: `dkmv runs` with filters
- [ ] Test: `dkmv runs` empty state
- [ ] Test: `dkmv show` with valid run
- [ ] Test: `dkmv show` with invalid run
- [ ] Test: `dkmv attach` when container running
- [ ] Test: `dkmv attach` when container not running
- [ ] Test: `dkmv stop` success and already-stopped cases

#### Files to Create/Modify

- `tests/unit/test_run_commands.py` — (create) Run management tests

#### Implementation Notes

Use Typer's `CliRunner` for testing CLI commands. Mock RunManager and Docker commands. Use `tmp_path` for run directories.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_run_commands.py -v` passes

---

### T095: Final Integration Verification

**PRD Reference:** Section 12 (Success Criteria)
**Depends on:** T094
**Blocks:** Nothing
**User Stories:** All
**Estimated scope:** 1-2 hours

#### Description

Run a final end-to-end verification against the v1 success criteria from PRD Section 12. Verify all major features work together.

#### Acceptance Criteria

- [ ] `dkmv build` works — builds Docker image
- [ ] `dkmv dev` produces working code (with real API key + Docker)
- [ ] `dkmv qa` produces a QA report
- [ ] `dkmv judge` produces a verdict
- [ ] `dkmv docs` generates docs (optionally creates PR)
- [ ] Feedback loop works: Judge → Dev iteration
- [ ] Cost tracking works: every run shows cost
- [ ] Components are modular: changing one prompt doesn't affect others
- [ ] Streaming works: real-time output visible
- [ ] `dkmv runs` and `dkmv show` work

#### Files to Create/Modify

None — verification task

#### Implementation Notes

This is a manual verification pass. Run through the primary user journey from PRD Section 5 with a real test repo. Document any issues found.

#### Evaluation Checklist

- [ ] All success criteria from PRD Section 12 met or documented
- [ ] Any remaining issues captured as GitHub issues

---

## Phase Completion Checklist

- [ ] All tasks T090-T095 completed
- [ ] `dkmv runs` shows formatted table
- [ ] `dkmv show <run-id>` displays details
- [ ] `dkmv attach` and `dkmv stop` work
- [ ] All tests passing: `uv run pytest tests/ -v -m "not e2e"`
- [ ] Lint clean: `uv run ruff check .`
- [ ] Type check clean: `uv run mypy dkmv/`
- [ ] Progress updated in tasks.md and progress.md
