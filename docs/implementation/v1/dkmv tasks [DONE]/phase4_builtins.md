# Phase 4: Built-in Components

## Prerequisites

- Phase 1-3 complete (Task Model, Loader, TaskRunner, ComponentRunner, CLI all working)
- `dkmv run ./local-component --repo ... --var key=value` works end-to-end (with mocked containers)
- All quality gates passing

## Phase Goal

The four existing Python components (dev, qa, judge, docs) are converted to YAML task files, packaged as built-ins, and accessible via `dkmv run dev`. The existing `dkmv dev/qa/judge/docs` CLI commands are refactored into thin wrappers that call `ComponentRunner.run()` internally. Both old and new interfaces work.

## Phase Evaluation Criteria

- `dkmv run dev --repo ... --var prd_path=...` works end-to-end
- `dkmv run qa --repo ... --var prd_path=...` works
- `dkmv run judge --repo ... --var prd_path=...` works
- `dkmv run docs --repo ... --var create_pr=true` works
- `dkmv dev --repo ... --prd ...` still works (backward compat wrapper)
- All 5 built-in YAML files load and validate correctly
- Built-in YAMLs packaged in wheel (`uv build && uv run python -c "from importlib.resources import files; print(list(files('dkmv.builtins.dev').iterdir()))"`)
- `uv run pytest tests/unit/test_builtins.py -v` passes
- No regressions in existing tests

---

## Tasks

### T135: Create Builtins Package

**PRD Reference:** Section 6.5 ("Built-in task YAMLs live in dkmv/builtins/"), Section 6.7
**Depends on:** T115 (built-in resolution)
**Blocks:** T136, T137, T138, T139, T140
**User Stories:** US-09

#### Description

Create the `dkmv/builtins/` package directory structure with `__init__.py` and subdirectories for each component.

#### Acceptance Criteria

- [ ] `dkmv/builtins/__init__.py` exists
- [ ] `dkmv/builtins/dev/` directory exists
- [ ] `dkmv/builtins/qa/` directory exists
- [ ] `dkmv/builtins/judge/` directory exists
- [ ] `dkmv/builtins/docs/` directory exists
- [ ] Each subdirectory has `__init__.py` (for importlib.resources to work)
- [ ] Package importable: `from importlib.resources import files; files("dkmv.builtins")`

#### Files to Create/Modify

- `dkmv/builtins/__init__.py` — (create)
- `dkmv/builtins/dev/__init__.py` — (create)
- `dkmv/builtins/qa/__init__.py` — (create)
- `dkmv/builtins/judge/__init__.py` — (create)
- `dkmv/builtins/docs/__init__.py` — (create)

#### Implementation Notes

The `__init__.py` files can be empty — they're just needed for Python package discovery and `importlib.resources`. The actual task YAML files go in the subdirectories.

#### Evaluation Checklist

- [ ] Package structure created
- [ ] `importlib.resources.files("dkmv.builtins.dev")` works

---

### T136: Convert Dev Component to YAML

**PRD Reference:** Section 6.7 ("Dev Component — 2 tasks")
**Depends on:** T135
**Blocks:** T141, T143
**User Stories:** US-23
**Estimated scope:** 2 hours

#### Description

Convert the Python `DevComponent` into two YAML task files: planning and implementation. Reference the existing draft at `docs/core/dkmv_tasks/v1/components/dev/`.

#### Acceptance Criteria

- [ ] `dkmv/builtins/dev/01-plan.yaml` — planning task:
  - `commit: false, push: false` (planning only, no code changes)
  - `model: claude-sonnet-4-6` (or leave unset for operator choice)
  - `max_turns: 50, max_budget_usd: 0.50`
  - Input: PRD via `{{ prd_path }}` → `.dkmv/prd.md`
  - Input (optional): feedback via `{{ feedback_path }}` → `.dkmv/feedback.json`
  - Input (optional): design docs via `{{ design_docs_path }}` → `.dkmv/design_docs/`
  - Output: `.dkmv/plan.md` (required: true, save: true)
  - Instructions: do NOT write implementation code, strip eval criteria
  - Prompt: produce implementation plan
- [ ] `dkmv/builtins/dev/02-implement.yaml` — implementation task:
  - `commit: true, push: true`
  - `max_turns: 100, max_budget_usd: 5.00`
  - Input: PRD (same file, already on disk from task 01)
  - Output (optional): `.dkmv/changes.md`
  - Instructions: follow the plan, run tests, fix failures
  - Prompt: implement from plan, with commit message template
  - `commit_message: "feat({{ component }}): {{ feature_name }} [dkmv-dev]"`
- [ ] Both files validate via `TaskLoader.load()` with appropriate variables

#### Files to Create/Modify

- `dkmv/builtins/dev/01-plan.yaml` — (create)
- `dkmv/builtins/dev/02-implement.yaml` — (create)

#### Implementation Notes

Start from the existing drafts at `docs/core/dkmv_tasks/v1/components/dev/` (01-plan.yaml and 02-implement.yaml from the example_task.yaml patterns). Refine for production:
- Remove verbose documentation comments
- Ensure template variables match the CLI wrapper mapping (T141)
- Test that Jinja2 conditionals work (e.g., `{% if feedback_path %}`)

The PRD stripping behavior from `DevComponent._strip_eval_criteria()` is handled via prompt instruction: tell Claude to ignore the `## Evaluation Criteria` section. The full PRD is copied — no content transformation needed.

#### Evaluation Checklist

- [ ] Both files are valid YAML
- [ ] Both validate via `TaskLoader.load()` with sample variables
- [ ] Plan task has `commit: false`
- [ ] Implement task has `commit: true, push: true`
- [ ] Optional inputs use `optional: true`

---

### T137: Convert QA Component to YAML

**PRD Reference:** Section 6.7 ("QA Component — 1 task")
**Depends on:** T135
**Blocks:** T142, T143
**User Stories:** US-09

#### Description

Convert the Python `QAComponent` into a single YAML task file.

#### Acceptance Criteria

- [ ] `dkmv/builtins/qa/01-evaluate.yaml`:
  - Input: full PRD (including eval criteria) via `{{ prd_path }}`
  - Output: `.dkmv/qa_report.json` (required: true, save: true)
  - `commit: true, push: true`
  - `commit_message: "feat(qa): {{ feature_name }} [dkmv-qa]"`
  - Instructions: run tests, evaluate against PRD, produce JSON report
  - Prompt: comprehensive QA evaluation

#### Files to Create/Modify

- `dkmv/builtins/qa/01-evaluate.yaml` — (create)

#### Implementation Notes

Reference existing `dkmv/components/qa/prompt.md` for prompt content. The QA component gives Claude the FULL PRD including `## Evaluation Criteria` (unlike dev which strips it). The `qa_report.json` is declared as an output with `required: true`, so the runtime auto-force-adds it before commit (replaces `QAComponent._teardown_git()` override).

#### Evaluation Checklist

- [ ] File validates via `TaskLoader.load()`
- [ ] Full PRD as input (not stripped)
- [ ] Report output required and saved

---

### T138: Convert Judge Component to YAML

**PRD Reference:** Section 6.7 ("Judge Component — 1 task")
**Depends on:** T135
**Blocks:** T142, T143
**User Stories:** US-09

#### Description

Convert the Python `JudgeComponent` into a single YAML task file.

#### Acceptance Criteria

- [ ] `dkmv/builtins/judge/01-verdict.yaml`:
  - Input: full PRD via `{{ prd_path }}`
  - Output: `.dkmv/verdict.json` (required: true, save: true)
  - `commit: true, push: true`
  - `commit_message: "feat(judge): {{ feature_name }} [dkmv-judge]"`
  - Instructions: independent evaluation, strict but fair, valid JSON
  - Prompt: evaluate implementation against PRD, produce verdict

#### Files to Create/Modify

- `dkmv/builtins/judge/01-verdict.yaml` — (create)

#### Implementation Notes

Reference existing `dkmv/components/judge/prompt.md` and `docs/core/dkmv_tasks/v1/components/judge/01-verdict.yaml`. The Judge must be independent — instructions emphasize not being influenced by QA reports or developer reasoning.

#### Evaluation Checklist

- [ ] File validates via `TaskLoader.load()`
- [ ] Independence emphasized in instructions
- [ ] Verdict output required and saved

---

### T139: Convert Docs Component to YAML

**PRD Reference:** Section 6.7 ("Docs Component — 1 task")
**Depends on:** T135
**Blocks:** T142, T143
**User Stories:** US-09

#### Description

Convert the Python `DocsComponent` into a single YAML task file.

#### Acceptance Criteria

- [ ] `dkmv/builtins/docs/01-generate.yaml`:
  - Inputs: env vars for PR creation (`DKMV_CREATE_PR`, `DKMV_PR_BASE`) via `{{ create_pr }}` and `{{ pr_base }}`
  - Input (optional): style guide via `{{ style_guide_path }}`
  - Output (optional): `.dkmv/docs_manifest.json`
  - `commit: true, push: true`
  - Instructions: do NOT modify implementation code, follow existing style
  - Prompt: explore codebase, generate docs, optionally create PR

#### Files to Create/Modify

- `dkmv/builtins/docs/01-generate.yaml` — (create)

#### Implementation Notes

Reference existing `dkmv/components/docs/prompt.md` and `docs/core/dkmv_tasks/v1/components/docs/01-generate.yaml`. The docs component has no PRD input — it reads the codebase directly. PR creation is prompt-driven: the prompt tells Claude to run `gh pr create` if the `DKMV_CREATE_PR` env var is set.

#### Evaluation Checklist

- [ ] File validates via `TaskLoader.load()`
- [ ] No PRD input (docs reads code directly)
- [ ] PR creation is prompt-driven via env var

---

### T140: Update pyproject.toml for Built-in Packaging

**PRD Reference:** Section 6.5 ("must be included in the wheel via pyproject.toml configuration")
**Depends on:** T135
**Blocks:** T143
**User Stories:** N/A (infrastructure)

#### Description

Update `pyproject.toml` to include the built-in YAML files in the wheel distribution.

#### Acceptance Criteria

- [ ] Built-in YAML files included in wheel after `uv build`
- [ ] `importlib.resources.files("dkmv.builtins.dev")` finds YAML files after install
- [ ] Existing prompt.md force-include config still works

#### Files to Create/Modify

- `pyproject.toml` — (modify) Add built-in YAML packaging

#### Implementation Notes

The existing `pyproject.toml` uses hatchling force-include for prompt.md files. Add similar config for the builtins YAML files. With hatchling, there are two approaches:

1. **Force-include** (explicit):
```toml
[tool.hatch.build.targets.wheel.force-include]
"dkmv/builtins/dev/01-plan.yaml" = "dkmv/builtins/dev/01-plan.yaml"
```

2. **Package data** (automatic): Ensure `dkmv/builtins/` is a proper package (has `__init__.py`) and hatchling should include all files by default.

Test with: `uv build && unzip -l dist/*.whl | grep builtins`

#### Evaluation Checklist

- [ ] `uv build` succeeds
- [ ] YAML files in wheel
- [ ] `importlib.resources` finds them

---

### T141: Update Dev CLI Wrapper

**PRD Reference:** Section 6.6 ("Backward compatibility"), Section 9 ("Phase A: Coexistence")
**Depends on:** T136, T132
**Blocks:** T143
**User Stories:** US-13
**Estimated scope:** 1 hour

#### Description

Refactor the existing `dkmv dev` CLI command to call `ComponentRunner.run()` internally, translating its typed CLI options into template variables.

#### Acceptance Criteria

- [ ] `dkmv dev <repo> --prd auth.md` still works
- [ ] Internally calls `ComponentRunner.run()` with `variables={"prd_path": "auth.md"}`
- [ ] All existing flags continue to work:
  - `--prd PATH` → `prd_path=PATH`
  - `--feedback PATH` → `feedback_path=PATH`
  - `--design-docs PATH` → `design_docs_path=PATH`
  - `--branch`, `--feature-name`, `--model`, `--max-turns`, `--timeout`, `--max-budget-usd`, `--keep-alive`, `--verbose` pass through directly
- [ ] Help text unchanged (or minimally updated)
- [ ] After `ComponentRunner.run()` returns, display typed result output (cost summary, task statuses) using Rich formatting

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Refactor `dev` command

#### Implementation Notes

From PRD Section 6.6 wrapper mapping table:

```python
@app.command()
@async_command
async def dev(
    repo: ...,
    prd: ...,
    feedback: ... = None,
    design_docs: ... = None,
    branch: ... = None,
    feature_name: ... = None,
    model: ... = None,
    max_turns: ... = None,
    timeout: ... = None,
    max_budget_usd: ... = None,
    keep_alive: ... = False,
    verbose: ... = False,
) -> None:
    from dkmv.tasks.component import ComponentRunner
    from dkmv.tasks.discovery import resolve_component
    from dkmv.tasks.models import CLIOverrides

    config = load_config()
    variables = {"prd_path": str(prd)}
    if feedback:
        variables["feedback_path"] = str(feedback)
    if design_docs:
        variables["design_docs_path"] = str(design_docs)

    cli_overrides = CLIOverrides(
        model=model, max_turns=max_turns,
        timeout_minutes=timeout, max_budget_usd=max_budget_usd,
    )

    component_dir = resolve_component("dev")
    result = await ComponentRunner(...).run(
        component_dir=component_dir,
        repo=repo,
        branch=branch,
        feature_name=feature_name or Path(prd).stem,
        variables=variables,
        config=config,
        cli_overrides=cli_overrides,
        keep_alive=keep_alive,
        verbose=verbose,
    )
    # Display result (cost summary, task statuses) using Rich formatting
```

Keep the old function signature identical — only the implementation changes. The user-facing interface is the same.

#### Evaluation Checklist

- [ ] `dkmv dev --help` unchanged
- [ ] `dkmv dev <repo> --prd auth.md` works
- [ ] All flags pass through correctly
- [ ] Feature name derived from PRD filename if not provided

---

### T142: Update QA, Judge, Docs CLI Wrappers

**PRD Reference:** Section 6.6 ("Backward compatibility")
**Depends on:** T137-T139, T132
**Blocks:** T143
**User Stories:** US-13

#### Description

Refactor the `dkmv qa`, `dkmv judge`, and `dkmv docs` CLI commands to call `ComponentRunner.run()` internally, similar to the dev wrapper (T141).

#### Acceptance Criteria

- [ ] `dkmv qa <repo> --branch ... --prd ...` → `ComponentRunner.run("qa", variables={"prd_path": ...})`
- [ ] `dkmv judge <repo> --branch ... --prd ...` → `ComponentRunner.run("judge", variables={"prd_path": ...})`
- [ ] `dkmv docs <repo> --branch ...` → `ComponentRunner.run("docs", variables={})`
- [ ] `dkmv docs --create-pr` → `variables["create_pr"] = "true"`
- [ ] `dkmv docs --pr-base main` → `variables["pr_base"] = "main"`
- [ ] All existing flags continue to work
- [ ] After `ComponentRunner.run()` returns, display typed result output:
  - QA: show report summary (pass/fail counts) from `qa_report.json` output
  - Judge: show verdict (PASS/FAIL) with colored output from `verdict.json` output
  - Docs: show generated files summary from `docs_manifest.json` output (if available)

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Refactor qa, judge, docs commands

#### Implementation Notes

Same pattern as T141. Each wrapper translates its specific options into variables and constructs `CLIOverrides` from the execution-parameter flags:
- QA: `{"prd_path": str(prd)}`
- Judge: `{"prd_path": str(prd)}`
- Docs: `{"create_pr": "true", "pr_base": "main"}` (when flags set)

All wrappers construct `CLIOverrides(model=model, max_turns=max_turns, timeout_minutes=timeout, max_budget_usd=max_budget_usd)` and pass it to `ComponentRunner.run(cli_overrides=...)`.

#### Evaluation Checklist

- [ ] All three wrappers work
- [ ] Help text unchanged
- [ ] Flags pass through correctly

---

### T143: Write Built-in and Backward Compat Tests

**PRD Reference:** Section 8 Level 5 (~15 tests)
**Depends on:** T136-T142
**Blocks:** T144
**User Stories:** N/A

#### Description

Write tests validating all built-in YAML files load correctly and backward compatibility wrappers work.

#### Acceptance Criteria

- [ ] Test: all 5 built-in YAML files load via `TaskLoader.load()` with sample variables
- [ ] Test: `TaskLoader.load_component()` loads dev (2 tasks), qa (1), judge (1), docs (1)
- [ ] Test: dev tasks are in correct order (plan before implement)
- [ ] Test: `resolve_component("dev")` returns path with YAML files
- [ ] Test: `resolve_component("qa")`, `resolve_component("judge")`, `resolve_component("docs")` work
- [ ] Test: `dkmv dev --help` shows expected options
- [ ] Test: `dkmv qa --help` shows expected options
- [ ] Test: dev wrapper maps `--prd` to `prd_path` variable
- [ ] Test: docs wrapper maps `--create-pr` to `create_pr=true` variable
- [ ] Test: CLI wrapper invokes ComponentRunner with correct arguments

#### Files to Create/Modify

- `tests/unit/test_builtins.py` — (create)

#### Implementation Notes

For YAML validation tests, provide the minimum variables needed to resolve templates (e.g., `{"prd_path": "/tmp/test.md", "repo": "https://...", "feature_name": "test"}`). Mock `ComponentRunner` for wrapper tests.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_builtins.py -v` passes
- [ ] All built-ins validate
- [ ] All wrappers tested

---

### T144: Write E2E Integration Test

**PRD Reference:** Section 8 Level 6 (~2 tests)
**Depends on:** T143
**Blocks:** Nothing
**User Stories:** N/A

#### Description

Write E2E tests that exercise the full pipeline with a real Docker container (marked `@pytest.mark.e2e`).

#### Acceptance Criteria

- [ ] Test: `dkmv run dev` with real container + mocked Claude Code
- [ ] Verifies: container starts, inputs copied, outputs collected, git operations work
- [ ] Test: multi-task component (dev) runs both tasks in sequence
- [ ] Marked `@pytest.mark.e2e` (requires Docker, skipped in CI by default)

#### Files to Create/Modify

- `tests/integration/test_run_e2e.py` — (create)

#### Implementation Notes

Use the pattern from existing E2E tests. Create a minimal test repository, run the dev component with a trivial PRD, and verify the output artifacts exist.

#### Evaluation Checklist

- [ ] Tests pass with Docker available
- [ ] Tests skip gracefully without Docker

---

## Phase Completion Checklist

- [ ] All tasks T135-T144 completed
- [ ] `dkmv run dev` works with built-in YAML
- [ ] `dkmv dev --prd ...` backward compat works
- [ ] All 5 built-in YAMLs load and validate
- [ ] Built-ins packaged in wheel
- [ ] All tests passing
- [ ] No regressions in existing tests
- [ ] Lint clean: `uv run ruff check .`
- [ ] Format clean: `uv run ruff format --check .`
- [ ] Type check clean: `uv run mypy dkmv/`
- [ ] Progress updated in tasks.md and progress.md
