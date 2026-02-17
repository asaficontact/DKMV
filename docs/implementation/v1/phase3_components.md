# Phase 3: Components

## Prerequisites

- Phase 2 complete (core framework operational)
- BaseComponent lifecycle working with mock component
- SandboxManager, RunManager, StreamParser all tested

## Phase Goal

All four components (Dev, QA, Judge, Docs) are implemented, registered, and invocable via CLI. The Dev component works end-to-end against a real test repo. Prompt templates are snapshot-tested.

## Phase Evaluation Criteria

- `dkmv dev --prd test.md --repo <url>` works E2E (with real Docker + API key)
- All 4 components registered: `get_component("dev")`, `get_component("qa")`, etc.
- All CLI commands functional: `dkmv dev --help`, `dkmv qa --help`, `dkmv judge --help`, `dkmv docs --help`
- Prompt snapshot tests pass: `uv run pytest tests/unit/test_prompts.py -v`
- `uv run pytest tests/unit/ -v` all pass

---

## Tasks

### T060: Create Dev Component Subpackage Structure

**PRD Reference:** Section 3.1, Section 6/F7
**Depends on:** T050
**Blocks:** T061, T062, T063
**User Stories:** US-05
**Estimated scope:** 15 min

#### Description

Create the `dkmv/components/dev/` subpackage directory with all necessary files.

#### Acceptance Criteria

- [ ] `dkmv/components/dev/__init__.py` exists (exports DevComponent, DevConfig, DevResult)
- [ ] `dkmv/components/dev/component.py` exists (stub)
- [ ] `dkmv/components/dev/models.py` exists (stub)
- [ ] `dkmv/components/dev/prompt.md` exists (stub)

#### Files to Create/Modify

- `dkmv/components/dev/__init__.py` — (create) Exports
- `dkmv/components/dev/component.py` — (create) Stub
- `dkmv/components/dev/models.py` — (create) Stub
- `dkmv/components/dev/prompt.md` — (create) Stub

#### Implementation Notes

The `__init__.py` should import and re-export: `from .component import DevComponent`, `from .models import DevConfig, DevResult`.

#### Evaluation Checklist

- [ ] All files exist
- [ ] `from dkmv.components.dev import DevComponent` works

---

### T061: Create Dev Models

**PRD Reference:** Section 6/F4 (DevConfig, DevResult)
**Depends on:** T030, T060
**Blocks:** T063
**User Stories:** US-05
**Estimated scope:** 30 min

#### Description

Create DevConfig and DevResult Pydantic models specific to the Dev component.

#### Acceptance Criteria

- [ ] `DevConfig(BaseComponentConfig)` with: prd_path, feedback_path, design_docs_path
- [ ] `DevResult(BaseResult)` with: component="dev", files_changed, tests_passed, tests_failed
- [ ] Both models validate correctly

#### Files to Create/Modify

- `dkmv/components/dev/models.py` — (modify) Add model definitions

#### Implementation Notes

Use exact model fields from PRD Section 6/F4. `prd_path: Path` is required, others optional.

#### Evaluation Checklist

- [ ] Models instantiate with valid data
- [ ] JSON round-trip works
- [ ] Type check passes

---

### T062: Create Dev Prompt Template

**PRD Reference:** Section 6/F7
**Depends on:** T060
**Blocks:** T065, T087
**User Stories:** US-05, US-07
**Estimated scope:** 30 min

#### Description

Create the prompt template for the Dev component, based on PRD Section 6/F7.

#### Acceptance Criteria

- [ ] Template includes: task description, explore & plan phase, implement phase, constraints
- [ ] Uses `{design_docs_section}` placeholder
- [ ] Uses `{feedback_section}` placeholder
- [ ] Instructs agent to produce `.dkmv/plan.md` before coding

#### Files to Create/Modify

- `dkmv/components/dev/prompt.md` — (modify) Full prompt template

#### Implementation Notes

Use the exact template from PRD Section 6/F7 as a starting point. The template should have clear placeholders for variable sections.

#### Evaluation Checklist

- [ ] Template reads clearly as agent instructions
- [ ] All placeholders present

---

### T063: Create DevComponent Class

**PRD Reference:** Section 6/F7
**Depends on:** T051, T061, T062
**Blocks:** T064, T065, T066, T067, T068, T070
**User Stories:** US-05, US-06, US-07
**Estimated scope:** 2 hours

#### Description

Create the DevComponent class extending `BaseComponent[DevConfig, DevResult]`. Implement the abstract methods.

#### Acceptance Criteria

- [ ] `DevComponent(BaseComponent[DevConfig, DevResult])` class
- [ ] `name` property returns `"dev"`
- [ ] `build_prompt()` implemented (basic version, refined in T065-T068)
- [ ] `parse_result()` extracts files changed, test counts from stream output
- [ ] `setup_workspace()` handles Dev-specific setup: copies PRD to `.dkmv/prd.md` (with eval criteria stripped), calls `super().setup_workspace()` for base setup

#### Files to Create/Modify

- `dkmv/components/dev/component.py` — (modify) Full implementation

#### Implementation Notes

The DevComponent overrides `setup_workspace()` to handle PRD copying (with eval criteria stripped), feedback injection, and design docs. `build_prompt()` loads the template and fills in placeholders.

#### Evaluation Checklist

- [ ] Component instantiable
- [ ] All abstract methods implemented
- [ ] Type check passes

---

### T064: Register Dev Component

**PRD Reference:** Section 6/F6 (registry)
**Depends on:** T063
**Blocks:** T069
**User Stories:** US-05
**Estimated scope:** 5 min

#### Description

Add the `@register_component("dev")` decorator to DevComponent.

#### Acceptance Criteria

- [ ] `get_component("dev")` returns DevComponent class
- [ ] `"dev"` appears in `list_components()`

#### Files to Create/Modify

- `dkmv/components/dev/component.py` — (modify) Add decorator

#### Implementation Notes

Import `register_component` from `dkmv.components` and apply as class decorator. Ensure the import chain works (dev/__init__.py imports component.py which imports from parent package).

#### Evaluation Checklist

- [ ] Registry lookup works

---

### T065: Implement build_prompt() with Eval Criteria Stripping

**PRD Reference:** Section 6/F7, Section 3.3
**Depends on:** T063, T053
**Blocks:** Nothing
**User Stories:** US-05
**Estimated scope:** 1 hour

#### Description

Implement the Dev component's `build_prompt()` to load the template and inject PRD content with the `## Evaluation Criteria` section stripped. Dev builds to requirements, not evaluation criteria.

#### Acceptance Criteria

- [ ] Loads template via `_load_prompt_template()`
- [ ] Reads PRD file content
- [ ] Strips `## Evaluation Criteria` section (and everything after it in that section)
- [ ] Injects remaining PRD content into prompt
- [ ] Handles PRDs without evaluation criteria section (no-op)

#### Files to Create/Modify

- `dkmv/components/dev/component.py` — (modify) Implement build_prompt()

#### Implementation Notes

Strip by finding `## Evaluation Criteria` header and removing everything from that line to the next `## ` header or end of file. Use regex or simple string splitting.

#### Evaluation Checklist

- [ ] PRD with eval criteria: section stripped
- [ ] PRD without eval criteria: unchanged
- [ ] Prompt is well-formed

---

### T066: Implement Design Docs Handling

**PRD Reference:** Section 6/F7, US-26
**Depends on:** T063
**Blocks:** Nothing
**User Stories:** US-26
**Estimated scope:** 1 hour

#### Description

Implement `--design-docs` flag handling: copy design documents to `.dkmv/design_docs/` inside the container workspace and inject reference section into prompt.

#### Acceptance Criteria

- [ ] `--design-docs PATH` accepts directory path
- [ ] All files from directory copied to `.dkmv/design_docs/` in workspace
- [ ] `{design_docs_section}` in prompt replaced with reference text
- [ ] When no design docs: placeholder replaced with empty string

#### Files to Create/Modify

- `dkmv/components/dev/component.py` — (modify) Add design docs handling

#### Implementation Notes

Use `sandbox.write_file()` or `sandbox.execute("cp ...")` to copy files. The design docs section from PRD:
```markdown
## Design Documents
Read design documents at `.dkmv/design_docs/` for architectural guidance.
These are reference material — do not modify them.
```

#### Evaluation Checklist

- [ ] Files copied to workspace
- [ ] Prompt section injected correctly
- [ ] No error when no design docs provided

---

### T067: Implement Feedback Injection

**PRD Reference:** Section 6/F7, Section 6/F6 (Feedback Synthesis)
**Depends on:** T055, T063
**Blocks:** Nothing
**User Stories:** US-09
**Estimated scope:** 1 hour

#### Description

Implement `--feedback` flag handling: load synthesized feedback JSON, inject into Dev prompt.

#### Acceptance Criteria

- [ ] `--feedback PATH` reads the feedback JSON file
- [ ] Feedback synthesized from raw verdict (if raw verdict provided)
- [ ] Synthesized feedback injected into `{feedback_section}` placeholder
- [ ] When no feedback: placeholder replaced with empty string

#### Files to Create/Modify

- `dkmv/components/dev/component.py` — (modify) Add feedback handling

#### Implementation Notes

The feedback is a synthesized brief from the BaseComponent's feedback synthesis (T055). Copy to `.dkmv/feedback.json` in workspace. Add a section to the prompt:
```markdown
## Previous Feedback
Review the feedback from the previous evaluation at `.dkmv/feedback.json`.
Address all action items, prioritizing by severity (critical first).
```

#### Evaluation Checklist

- [ ] Feedback loaded and injected
- [ ] Prompt includes feedback reference
- [ ] No error when no feedback

---

### T068: Implement Plan-First Approach

**PRD Reference:** Section 6/F7
**Depends on:** T063
**Blocks:** Nothing
**User Stories:** US-05
**Estimated scope:** 30 min

#### Description

Ensure the Dev prompt instructs the agent to produce `.dkmv/plan.md` before writing implementation code. Capture the plan as a run artifact.

#### Acceptance Criteria

- [ ] Prompt instructs: "Produce a plan at `.dkmv/plan.md` before writing code"
- [ ] Plan file captured as run artifact after execution
- [ ] Plan file content saved to run directory

#### Files to Create/Modify

- `dkmv/components/dev/component.py` — (modify) Add plan artifact capture

#### Implementation Notes

After Claude Code completes, read `.dkmv/plan.md` from the container (if it exists) and save it to the run directory. The prompt already includes this instruction (T062).

#### Evaluation Checklist

- [ ] Plan captured when present
- [ ] No error when plan not created

---

### T069: Register dkmv dev CLI Command

**PRD Reference:** Section 6/F7
**Depends on:** T064
**Blocks:** T071
**User Stories:** US-05, US-10, US-11
**Estimated scope:** 1-2 hours

#### Description

Replace the stub `dkmv dev` command with the full implementation, wiring all CLI flags to DevConfig and DevComponent.

#### Acceptance Criteria

- [ ] `dkmv dev --help` shows all options
- [ ] Required flags: `--prd PATH`, `--repo TEXT`
- [ ] Optional flags: `--branch`, `--feedback`, `--design-docs`, `--feature-name`, `--model`, `--max-turns`, `--max-budget-usd`, `--timeout`, `--keep-alive`, `--verbose`
- [ ] Command creates DevConfig, instantiates DevComponent, calls run()
- [ ] Uses `@async_command` decorator for async support

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Replace dev stub with full implementation

#### Implementation Notes

Wire Typer options to DevConfig fields. Use `@app.command()` + `@async_command` stack. Create DKMVConfig, SandboxManager, RunManager, StreamParser internally.

#### Evaluation Checklist

- [ ] `dkmv dev --help` shows all options
- [ ] `dkmv dev --prd test.md --repo test-url` attempts to run (may fail without Docker/API key)
- [ ] Type check passes

---

### T070: Implement Branch Logic

**PRD Reference:** Section 6/F7
**Depends on:** T063
**Blocks:** Nothing
**User Stories:** US-08
**Estimated scope:** 30 min

#### Description

Implement the logic for creating a fresh branch vs checking out an existing branch in workspace setup.

#### Acceptance Criteria

- [ ] No `--branch`: creates `feature/<feature-name>-dev` (feature name from `--feature-name` or PRD filename)
- [ ] `--branch <name>`: checks out existing branch
- [ ] Feature name derived from PRD filename if not provided (e.g., `login.md` → `login`)

#### Files to Create/Modify

- `dkmv/components/dev/component.py` — (modify) Add branch logic to setup_workspace

#### Implementation Notes

Use `Path(prd_path).stem` for deriving feature name from PRD filename. Branch creation: `git checkout -b feature/<name>-dev`. Existing branch: `git checkout <branch>`.

#### Evaluation Checklist

- [ ] New branch created correctly
- [ ] Existing branch checked out correctly
- [ ] Feature name derivation works

---

### T071: Write Dev Component Unit Tests

**PRD Reference:** Section 8/Task 3.1
**Depends on:** T060-T070
**Blocks:** T072
**User Stories:** N/A
**Estimated scope:** 2 hours

#### Description

Write unit tests for the Dev component: model validation, prompt building, eval criteria stripping, design docs, feedback injection, branch logic.

#### Acceptance Criteria

- [ ] Test: DevConfig validation
- [ ] Test: DevResult serialization
- [ ] Test: build_prompt() with PRD only
- [ ] Test: build_prompt() strips evaluation criteria
- [ ] Test: build_prompt() with feedback
- [ ] Test: build_prompt() with design docs
- [ ] Test: branch name derivation
- [ ] All tests pass: `uv run pytest tests/unit/test_dev.py -v`

#### Files to Create/Modify

- `tests/unit/test_dev.py` — (create) Dev component unit tests

#### Implementation Notes

Mock the sandbox and file system. Focus on prompt building logic since that's the component-specific code. Use sample PRDs with and without evaluation criteria sections.

#### Evaluation Checklist

- [ ] All tests pass
- [ ] Good coverage of prompt building logic

---

### T072: Dev Component E2E Test

**PRD Reference:** Section 8/Task 3.1, Section 9.5.1
**Depends on:** T071
**Blocks:** Nothing
**User Stories:** US-05
**Estimated scope:** 2-3 hours

#### Description

Write and run an end-to-end test: run Dev against a small test repo with a trivial PRD, verify code is produced and committed.

#### Acceptance Criteria

- [ ] Test creates a minimal GitHub repo (or uses a pre-existing test repo)
- [ ] PRD: "Add a `greet(name: str) -> str` function that returns 'Hello, {name}!'"
- [ ] `dkmv dev` produces code on a branch
- [ ] Branch has at least one commit
- [ ] Test marked with `@pytest.mark.e2e`

#### Files to Create/Modify

- `tests/e2e/test_dev_pipeline.py` — (create) E2E test

#### Implementation Notes

Use `claude-haiku-4-5-20251001` (cheapest model) with `max_turns=10` to minimize cost. Use skip decorators: `skip_no_docker`, `skip_no_api_key`. This test is expensive — run manually or in nightly CI only.

#### Evaluation Checklist

- [ ] Test passes with Docker + API key
- [ ] Properly skipped when prerequisites missing
- [ ] Cost is reasonable (< $0.10)

---

### T073: Create QA Component Subpackage

**PRD Reference:** Section 3.1, Section 6/F8
**Depends on:** T050
**Blocks:** T074
**User Stories:** US-12
**Estimated scope:** 15 min

#### Description

Create the `dkmv/components/qa/` subpackage with all files.

#### Acceptance Criteria

- [ ] `dkmv/components/qa/__init__.py` — exports QAComponent, QAConfig, QAResult
- [ ] `dkmv/components/qa/component.py` — stub
- [ ] `dkmv/components/qa/models.py` — stub
- [ ] `dkmv/components/qa/prompt.md` — stub

#### Files to Create/Modify

- `dkmv/components/qa/__init__.py` — (create)
- `dkmv/components/qa/component.py` — (create)
- `dkmv/components/qa/models.py` — (create)
- `dkmv/components/qa/prompt.md` — (create)

#### Evaluation Checklist

- [ ] All files exist
- [ ] Package importable

---

### T074: Create QA Models, Component, and Prompt

**PRD Reference:** Section 6/F4 (QAConfig, QAResult), Section 6/F8
**Depends on:** T051, T073
**Blocks:** T075, T087
**User Stories:** US-12, US-13, US-14
**Estimated scope:** 2 hours

#### Description

Implement QAConfig, QAResult, QAComponent, and the QA prompt template.

#### Acceptance Criteria

- [ ] `QAConfig(BaseComponentConfig)` with: prd_path
- [ ] `QAResult(BaseResult)` with: component="qa", tests_total, tests_passed, tests_failed, warnings, qa_report_path
- [ ] `QAComponent(BaseComponent[QAConfig, QAResult])` with name="qa"
- [ ] Registered via `@register_component("qa")`
- [ ] Prompt instructs: run tests, check regressions, evaluate PRD coverage, review code quality, produce `.dkmv/qa_report.json`

#### Files to Create/Modify

- `dkmv/components/qa/models.py` — (modify) Model definitions
- `dkmv/components/qa/component.py` — (modify) QAComponent implementation
- `dkmv/components/qa/prompt.md` — (modify) QA prompt template

#### Implementation Notes

QA gets the **full PRD** including `## Evaluation Criteria` (unlike Dev which gets it stripped). QA's `setup_workspace()` copies the full PRD to `.dkmv/prd.md` (calls `super().setup_workspace()` for base setup). QA explicitly `git add -f .dkmv/qa_report.json` before commit (QA artifacts are committed, not gitignored).

#### Evaluation Checklist

- [ ] Component registered: `get_component("qa")`
- [ ] Models validate correctly
- [ ] Prompt covers all QA responsibilities
- [ ] `setup_workspace()` copies full PRD (including eval criteria) to `.dkmv/prd.md`

---

### T075: Implement QA with Full PRD

**PRD Reference:** Section 6/F8
**Depends on:** T074
**Blocks:** T076
**User Stories:** US-13, US-14
**Estimated scope:** 1 hour

#### Description

Implement the QA-specific workspace setup and prompt building: full PRD (including eval criteria), QA report committed to branch.

#### Acceptance Criteria

- [ ] PRD copied to workspace **with** eval criteria section
- [ ] QA report explicitly git-added and committed
- [ ] `parse_result()` reads `.dkmv/qa_report.json` from container

#### Files to Create/Modify

- `dkmv/components/qa/component.py` — (modify) Implement QA-specific logic

#### Implementation Notes

Override `setup_workspace()` to copy full PRD (no stripping). Override teardown to explicitly `git add -f .dkmv/qa_report.json` before the shared commit (force-add bypasses .gitignore).

#### Evaluation Checklist

- [ ] Full PRD in workspace
- [ ] QA report committed to branch

---

### T076: Register dkmv qa CLI Command

**PRD Reference:** Section 6/F8
**Depends on:** T075
**Blocks:** T077
**User Stories:** US-12
**Estimated scope:** 1 hour

#### Description

Replace the stub `dkmv qa` command with the full implementation.

#### Acceptance Criteria

- [ ] `dkmv qa --help` shows all options
- [ ] Required flags: `--branch`, `--repo`, `--prd`
- [ ] Optional flags: `--model`, `--max-turns`, `--max-budget-usd`, `--timeout`, `--keep-alive`, `--verbose`
- [ ] Command creates QAConfig, runs QAComponent
- [ ] Uses `@async_command` decorator for async support

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Replace qa stub

#### Evaluation Checklist

- [ ] `dkmv qa --help` works
- [ ] Command wired correctly

---

### T077: Write QA Component Unit Tests

**PRD Reference:** Section 8/Task 3.2
**Depends on:** T073-T076
**Blocks:** Nothing
**User Stories:** N/A
**Estimated scope:** 1-2 hours

#### Description

Write unit tests for QA component: model validation, prompt building (full PRD with eval criteria), result parsing.

#### Acceptance Criteria

- [ ] Test: QAConfig validation
- [ ] Test: build_prompt() includes eval criteria
- [ ] Test: QA report parsing
- [ ] All tests pass

#### Files to Create/Modify

- `tests/unit/test_qa.py` — (create) QA component unit tests

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_qa.py -v` passes

---

### T078: Create Judge Component Subpackage

**PRD Reference:** Section 3.1, Section 6/F9
**Depends on:** T050
**Blocks:** T079
**User Stories:** US-15
**Estimated scope:** 15 min

#### Description

Create the `dkmv/components/judge/` subpackage with all files.

#### Acceptance Criteria

- [ ] All files exist: `__init__.py`, `component.py`, `models.py`, `prompt.md`

#### Files to Create/Modify

- `dkmv/components/judge/__init__.py` — (create)
- `dkmv/components/judge/component.py` — (create)
- `dkmv/components/judge/models.py` — (create)
- `dkmv/components/judge/prompt.md` — (create)

#### Evaluation Checklist

- [ ] Package importable

---

### T079: Create Judge Models, Component, and Prompt

**PRD Reference:** Section 6/F4 (JudgeConfig, JudgeResult), Section 6/F9
**Depends on:** T051, T078
**Blocks:** T080, T087
**User Stories:** US-15, US-16, US-17
**Estimated scope:** 2 hours

#### Description

Implement JudgeConfig, JudgeResult, JudgeComponent, and the Judge prompt template.

#### Acceptance Criteria

- [ ] `JudgeConfig(BaseComponentConfig)` with: prd_path
- [ ] `JudgeResult(BaseResult)` with: component="judge", verdict, reasoning, issues, suggestions
- [ ] `JudgeComponent(BaseComponent[JudgeConfig, JudgeResult])` with name="judge"
- [ ] Registered via `@register_component("judge")`
- [ ] Prompt emphasizes: independence, strict evaluation, structured verdict output
- [ ] Verdict JSON schema from PRD Section 6/F9

#### Files to Create/Modify

- `dkmv/components/judge/models.py` — (modify) Model definitions
- `dkmv/components/judge/component.py` — (modify) JudgeComponent
- `dkmv/components/judge/prompt.md` — (modify) Judge prompt template

#### Implementation Notes

Judge gets the **full PRD** including eval criteria. Judge's `setup_workspace()` copies the full PRD to `.dkmv/prd.md` (calls `super().setup_workspace()` for base setup). Judge CANNOT see Dev's reasoning — only code, tests, and QA report. Verdict JSON includes: verdict, confidence, reasoning, prd_requirements, issues, suggestions.

#### Evaluation Checklist

- [ ] Component registered
- [ ] Verdict model validates correctly
- [ ] `setup_workspace()` copies full PRD (including eval criteria) to `.dkmv/prd.md`

---

### T080: Implement Judge with Full PRD

**PRD Reference:** Section 6/F9
**Depends on:** T079
**Blocks:** T081
**User Stories:** US-16, US-17
**Estimated scope:** 1 hour

#### Description

Implement Judge-specific workspace setup: full PRD, verdict JSON committed to branch.

#### Acceptance Criteria

- [ ] PRD copied with eval criteria
- [ ] Verdict explicitly git-added and committed: `git add -f .dkmv/verdict.json`
- [ ] `parse_result()` reads verdict JSON

#### Files to Create/Modify

- `dkmv/components/judge/component.py` — (modify) Judge-specific logic

#### Evaluation Checklist

- [ ] Full PRD in workspace
- [ ] Verdict committed to branch

---

### T081: Register dkmv judge CLI Command and Implement Verdict Display

**PRD Reference:** Section 6/F9
**Depends on:** T080
**Blocks:** T082
**User Stories:** US-15, US-16, US-17
**Estimated scope:** 1-2 hours

#### Description

Replace the stub `dkmv judge` command with the full implementation, wiring all CLI flags to JudgeConfig and JudgeComponent. Also implement colored PASS/FAIL verdict display.

#### Acceptance Criteria

- [ ] `dkmv judge --help` shows all options
- [ ] Required flags: `--branch`, `--repo`, `--prd`
- [ ] Optional flags: `--model`, `--max-turns`, `--max-budget-usd`, `--timeout`, `--keep-alive`, `--verbose`
- [ ] Command creates JudgeConfig, instantiates JudgeComponent, calls run()
- [ ] Uses `@async_command` decorator for async support
- [ ] PASS verdict: displayed in green with summary
- [ ] FAIL verdict: displayed in red with issue summary
- [ ] Shows verdict reasoning and key issues

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) Replace judge stub with full implementation + verdict display
- `dkmv/components/judge/component.py` — (modify) Add verdict display helper

#### Implementation Notes

Wire Typer options to JudgeConfig fields. Use `@app.command()` + `@async_command` stack. After `run()` completes, display the verdict using `rich.console.Console` with `style="bold green"` for PASS and `style="bold red"` for FAIL. Show reasoning summary and key issues.

Pattern matches T069 (dev CLI) and T076 (qa CLI) with additional verdict display logic.

#### Evaluation Checklist

- [ ] `dkmv judge --help` shows all options
- [ ] `dkmv judge --branch x --repo y --prd z` attempts to run
- [ ] Verdict clearly visible in terminal with correct coloring
- [ ] Type check passes

---

### T082: Write Judge Component Unit Tests

**PRD Reference:** Section 8/Task 3.3
**Depends on:** T078-T081
**Blocks:** Nothing
**User Stories:** N/A
**Estimated scope:** 1-2 hours

#### Description

Write unit tests for Judge component: model validation, prompt building, verdict parsing, display.

#### Acceptance Criteria

- [ ] Test: JudgeConfig validation
- [ ] Test: build_prompt() includes eval criteria
- [ ] Test: verdict parsing (pass and fail cases)
- [ ] Test: verdict display output
- [ ] Test: feedback file compatible with Dev --feedback

#### Files to Create/Modify

- `tests/unit/test_judge.py` — (create) Judge component unit tests

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_judge.py -v` passes

---

### T083: Create Docs Component Subpackage

**PRD Reference:** Section 3.1, Section 6/F10
**Depends on:** T050
**Blocks:** T084
**User Stories:** US-18
**Estimated scope:** 15 min

#### Description

Create the `dkmv/components/docs/` subpackage with all files.

#### Acceptance Criteria

- [ ] All files exist: `__init__.py`, `component.py`, `models.py`, `prompt.md`

#### Files to Create/Modify

- `dkmv/components/docs/__init__.py` — (create)
- `dkmv/components/docs/component.py` — (create)
- `dkmv/components/docs/models.py` — (create)
- `dkmv/components/docs/prompt.md` — (create)

#### Evaluation Checklist

- [ ] Package importable

---

### T084: Create Docs Models, Component, Prompt, and Register CLI Command

**PRD Reference:** Section 6/F4 (DocsConfig, DocsResult), Section 6/F10
**Depends on:** T051, T083
**Blocks:** T085, T087
**User Stories:** US-18, US-19
**Estimated scope:** 2-3 hours

#### Description

Implement DocsConfig, DocsResult, DocsComponent, and the Docs prompt template. Register the `dkmv docs` CLI command with all flags. NOTE: DocsConfig does NOT have `prd_path` — the Docs component generates docs from code, no PRD needed.

#### Acceptance Criteria

- [ ] `DocsConfig(BaseComponentConfig)` with: create_pr, pr_base (NO prd_path)
- [ ] `DocsResult(BaseResult)` with: component="docs", docs_generated, pr_url
- [ ] `DocsComponent(BaseComponent[DocsConfig, DocsResult])` with name="docs"
- [ ] Registered via `@register_component("docs")`
- [ ] Prompt instructs: read code, generate/update docs, update README
- [ ] `dkmv docs --help` shows all options
- [ ] Required flags: `--branch`, `--repo`
- [ ] Optional flags: `--create-pr`, `--pr-base`, `--model`, `--max-turns`, `--max-budget-usd`, `--timeout`, `--keep-alive`, `--verbose`
- [ ] Command creates DocsConfig, instantiates DocsComponent, calls run()
- [ ] Uses `@async_command` decorator for async support

#### Files to Create/Modify

- `dkmv/components/docs/models.py` — (modify) Model definitions
- `dkmv/components/docs/component.py` — (modify) DocsComponent
- `dkmv/components/docs/prompt.md` — (modify) Docs prompt template
- `dkmv/cli.py` — (modify) Replace docs stub with full implementation

#### Implementation Notes

Wire Typer options to DocsConfig fields. Pattern matches T069 (dev CLI), T076 (qa CLI), T081 (judge CLI). Unlike other components, Docs has NO `--prd` flag. The `--create-pr` flag is boolean (default False). `--pr-base` defaults to "main".

#### Evaluation Checklist

- [ ] Component registered: `get_component("docs")`
- [ ] Models validate correctly
- [ ] `dkmv docs --help` shows all options (no --prd flag)
- [ ] `dkmv docs --branch x --repo y` attempts to run
- [ ] Type check passes

---

### T085: Implement PR Creation

**PRD Reference:** Section 6/F10
**Depends on:** T084
**Blocks:** T086
**User Stories:** US-19
**Estimated scope:** 1 hour

#### Description

Implement PR creation via `gh pr create` inside the container when `--create-pr` flag is set.

#### Acceptance Criteria

- [ ] `--create-pr` flag triggers `gh pr create` command
- [ ] PR created from feature branch to `--pr-base` (default: main)
- [ ] PR includes title and auto-generated body
- [ ] PR URL captured in DocsResult
- [ ] No PR created when flag not set

#### Files to Create/Modify

- `dkmv/components/docs/component.py` — (modify) Add PR creation logic

#### Implementation Notes

Execute via `sandbox.execute()`: `gh pr create --base main --head <branch> --title "..." --body "..."`. Parse the PR URL from stdout.

#### Evaluation Checklist

- [ ] PR creation command correct
- [ ] URL captured correctly

---

### T086: Write Docs Component Unit Tests

**PRD Reference:** Section 8/Task 3.4
**Depends on:** T083-T085
**Blocks:** Nothing
**User Stories:** N/A
**Estimated scope:** 1 hour

#### Description

Write unit tests for Docs component: model validation, prompt building, PR creation logic.

#### Acceptance Criteria

- [ ] Test: DocsConfig validation
- [ ] Test: build_prompt()
- [ ] Test: PR creation command construction
- [ ] Test: PR URL parsing

#### Files to Create/Modify

- `tests/unit/test_docs.py` — (create) Docs component unit tests

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_docs.py -v` passes

---

### T087: Write Prompt Snapshot Tests

**PRD Reference:** Section 8/Task 3.5, Section 9.5.1
**Depends on:** T062, T074, T079, T084
**Blocks:** T088
**User Stories:** N/A
**Estimated scope:** 1-2 hours

#### Description

Write syrupy snapshot tests that verify the rendered prompt templates match expected output.

#### Acceptance Criteria

- [ ] Snapshot test for Dev prompt template
- [ ] Snapshot test for QA prompt template
- [ ] Snapshot test for Judge prompt template
- [ ] Snapshot test for Docs prompt template
- [ ] All snapshots pass: `uv run pytest tests/unit/test_prompts.py -v`

#### Files to Create/Modify

- `tests/unit/test_prompts.py` — (create) Prompt snapshot tests

#### Implementation Notes

Use syrupy's `snapshot` fixture. Generate prompts with sample configs and compare against stored snapshots. Snapshots are stored in `tests/unit/__snapshots__/`.

#### Evaluation Checklist

- [ ] All snapshot tests pass
- [ ] Snapshots stored in git

---

### T088: Test Prompt Building with Different Configs

**PRD Reference:** Section 8/Task 3.5
**Depends on:** T087
**Blocks:** Nothing
**User Stories:** N/A
**Estimated scope:** 1 hour

#### Description

Test prompt building with different configuration combinations to ensure all code paths work correctly.

#### Acceptance Criteria

- [ ] Test: Dev prompt — PRD only (no feedback, no design docs)
- [ ] Test: Dev prompt — PRD + feedback
- [ ] Test: Dev prompt — PRD + design docs
- [ ] Test: Dev prompt — PRD + feedback + design docs
- [ ] Test: QA/Judge prompt — with eval criteria
- [ ] Test: Docs prompt — with and without create-pr

#### Files to Create/Modify

- `tests/unit/test_prompts.py` — (modify) Add config variation tests

#### Evaluation Checklist

- [ ] All config combinations produce valid prompts
- [ ] No placeholder artifacts in rendered prompts

---

## Phase Completion Checklist

- [ ] All tasks T060-T088 completed
- [ ] `dkmv dev --prd test.md --repo <url>` works E2E
- [ ] All 4 components registered and invocable
- [ ] All prompt snapshots pass
- [ ] All unit tests passing: `uv run pytest tests/unit/ -v`
- [ ] Lint clean: `uv run ruff check .`
- [ ] Type check clean: `uv run mypy dkmv/`
- [ ] Progress updated in tasks.md and progress.md
