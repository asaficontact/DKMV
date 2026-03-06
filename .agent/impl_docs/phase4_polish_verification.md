# Phase 4: Polish & Verification

## Prerequisites

- Phases 1-3 complete: all tasks T010-T075 done, all quality gates green
- Both adapters (Claude, Codex) fully functional
- Agent resolution cascade working at all 7 levels
- Docker image installs both agents
- Init discovers Codex credentials
- Mixed-agent components pass all credentials

## Phase Goal

Error messages are agent-aware, model-agent mismatches produce clear actionable errors, capability gaps are logged informatively, and the full system passes comprehensive regression testing with >= 80% coverage (>= 90% on new adapter code).

## Phase Evaluation Criteria

- `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all pass, coverage >= 80%
- `uv run ruff check .` — clean
- `uv run ruff format --check .` — clean
- `uv run mypy dkmv/` — passes
- `uv run pytest tests/unit/test_adapters/ -v --cov dkmv/adapters/ --cov-fail-under=90` — adapter coverage >= 90%
- Error messages do not contain hardcoded "Claude Code" when referring to the active agent
- Model-agent mismatch produces clear error naming both agent and model
- All 21 user stories have at least one passing test

---

## Tasks

### T090: Update Error Messages to Be Agent-Aware

**PRD Reference:** Section 4 (CP-9: Error messages and logging)
**Depends on:** Phase 3 complete
**Blocks:** T093
**User Stories:** N/A (infrastructure)
**Estimated scope:** 1.5 hours

#### Description

Scan codebase for hardcoded "Claude Code" references in error messages, log lines, and user-facing strings. Replace with agent-aware alternatives that use the adapter name or generic "agent" terminology.

#### Acceptance Criteria

- [ ] Error messages that reference the active agent use `adapter.name` or generic "agent" instead of "Claude Code"
- [ ] Log messages in TaskRunner/ComponentRunner are parameterized
- [ ] `stream_claude()` method name is NOT renamed (backwards compat), but error messages within are generic
- [ ] Comments and docstrings referencing "Claude Code" are updated where they should be agent-agnostic

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) update error messages
- `dkmv/tasks/component.py` — (modify) update error messages
- `dkmv/core/sandbox.py` — (modify) update error messages in stream_agent()

#### Implementation Notes

Search for "Claude" in error messages and log lines:
```bash
grep -rn "Claude" dkmv/ --include="*.py" | grep -v "claude_" | grep -v "ClaudeCode" | grep -v "CLAUDE.md"
```

Replace patterns like:
- `"Failed to launch Claude Code"` → `f"Failed to launch {adapter.name} agent"`
- `"Claude Code stream"` → `f"{adapter.name} stream"`
- `"Waiting for Claude Code"` → `f"Waiting for agent"`

**Do NOT rename:**
- `stream_claude()` method (backwards compat)
- `ClaudeCodeAdapter` class name
- `CLAUDE.md` file references
- Import names

#### Evaluation Checklist

- [ ] `grep -rn '"Claude Code"' dkmv/tasks/ dkmv/core/` shows no hardcoded agent name in error messages
- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass

---

### T091: Add Clear Model-Agent Mismatch Error Messaging

**PRD Reference:** Section 14 (R8), US-11
**Depends on:** T042 (Phase 2)
**Blocks:** T093
**User Stories:** US-11
**Estimated scope:** 1 hour

#### Description

Wire the `validate_agent_model()` function into the task execution flow so mismatches are caught before container startup. Ensure error messages are clear and actionable.

#### Acceptance Criteria

- [ ] Mismatch detected before `stream_agent()` is called
- [ ] Error message includes: agent name, incompatible model, list of compatible patterns
- [ ] Auto-substitution logs an info message with old model → new model
- [ ] Error is raised as a user-visible exception (not swallowed)

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) add validation call before streaming

#### Implementation Notes

In `TaskRunner.run()`, after resolving agent and model, call validation:

```python
from dkmv.adapters import validate_agent_model

# After resolving agent_name and model:
resolved_model = task.model or cli_overrides.model or config.default_model
try:
    resolved_model = validate_agent_model(
        agent_name,
        resolved_model,
        agent_explicit=(task.agent is not None or cli_overrides.agent is not None),
        model_explicit=(task.model is not None or cli_overrides.model is not None),
    )
except ValueError as e:
    # Surface as task failure with clear message
    return TaskResult(
        task_name=task.name,
        status="failed",
        error_message=str(e),
    )
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/tasks/runner.py` passes

---

### T092: Add Info Logging for Capability Gaps

**PRD Reference:** Section 13 (Feature Parity Strategy)
**Depends on:** Phase 3 complete
**Blocks:** T093
**User Stories:** N/A (infrastructure)
**Estimated scope:** 45 min

#### Description

When a task uses an agent that doesn't support certain features (max_turns, budget), log an info message rather than silently ignoring.

#### Acceptance Criteria

- [ ] When `max_turns` is set but `adapter.supports_max_turns()` is `False`, log info: "Agent '{name}' does not support --max-turns; using timeout as safety limit"
- [ ] When `max_budget_usd` is set but `adapter.supports_budget()` is `False`, log info: "Agent '{name}' does not support --max-budget-usd"
- [ ] Info messages logged once per task, not per event
- [ ] No warning or error — just informational

#### Files to Create/Modify

- `dkmv/tasks/runner.py` — (modify) add capability gap logging

#### Implementation Notes

In `TaskRunner.run()` or `_stream_agent()`, after creating the adapter:

```python
import logging
logger = logging.getLogger(__name__)

if task.max_turns and not adapter.supports_max_turns():
    logger.info(
        "Agent '%s' does not support --max-turns; using timeout as safety limit",
        adapter.name,
    )
if (task.max_budget_usd or cli_overrides.max_budget_usd) and not adapter.supports_budget():
    logger.info(
        "Agent '%s' does not support --max-budget-usd; cost will show as $0.00",
        adapter.name,
    )
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/tasks/runner.py` passes

---

### T093: Edge Case Testing

**PRD Reference:** Section 14 (Risks), Section 16
**Depends on:** T090, T091, T092
**Blocks:** T097
**User Stories:** N/A (infrastructure)
**Estimated scope:** 1.5 hours

#### Description

Write tests covering edge cases: unknown agent names, missing credentials at runtime, empty agent fields, and error handling paths.

#### Acceptance Criteria

- [ ] Test: unknown agent name in task YAML → clear error
- [ ] Test: Codex task with no CODEX_API_KEY → adapter returns empty auth env vars
- [ ] Test: agent field set to empty string → treated as None (falls through cascade)
- [ ] Test: model inference returns None for unknown model → no inference applied
- [ ] Test: resume with codex adapter uses correct command format
- [ ] Test: multiple turns accumulated correctly across codex session

#### Files to Create/Modify

- `tests/unit/test_adapters/test_edge_cases.py` — (create) edge case tests

#### Implementation Notes

```python
import pytest
from dkmv.adapters import get_adapter, validate_agent_model

def test_unknown_agent_raises():
    with pytest.raises(ValueError, match="Unknown agent"):
        get_adapter("gpt-agent")

def test_codex_empty_api_key():
    """Codex adapter with no API key returns empty auth env vars."""
    from unittest.mock import MagicMock
    adapter = get_adapter("codex")
    config = MagicMock()
    config.codex_api_key = ""
    assert adapter.get_auth_env_vars(config) == {}

def test_validate_agent_model_compatible():
    result = validate_agent_model("claude", "claude-sonnet-4-6")
    assert result == "claude-sonnet-4-6"  # Unchanged

def test_validate_agent_model_auto_substitute():
    result = validate_agent_model("codex", "claude-sonnet-4-6",
                                  agent_explicit=True, model_explicit=False)
    assert result == "gpt-5.3-codex"
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_adapters/test_edge_cases.py -v` — all pass

---

### T094: Update dkmv components Display to Show Agent Info

**PRD Reference:** F10 (CLI Integration)
**Depends on:** Phase 3 complete
**Blocks:** T097
**User Stories:** US-20
**Estimated scope:** 30 min

#### Description

Update the `dkmv components` CLI output to show the configured default agent alongside other component information.

#### Acceptance Criteria

- [ ] `dkmv components` output includes agent information when a manifest specifies agent
- [ ] Output is backward-compatible (no change when no agent is specified)

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) update components display

#### Implementation Notes

In the `components` command, when showing component details, include agent info if the manifest has an `agent` field:

```python
if manifest.agent:
    console.print(f"  Agent: {manifest.agent}")
```

Keep it simple — only show agent when explicitly configured.

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass

---

### T095: Update CLAUDE.md with Adapter Conventions

**PRD Reference:** Section 8 (Changes by File)
**Depends on:** Phase 3 complete
**Blocks:** T097
**User Stories:** N/A (documentation)
**Estimated scope:** 30 min

#### Description

Update the project `CLAUDE.md` to document the new adapter architecture, new files, and conventions for future development.

#### Acceptance Criteria

- [ ] `CLAUDE.md` references `dkmv/adapters/` package
- [ ] Conventions section includes `adapter` as a valid commit scope
- [ ] New file list includes adapter files
- [ ] DO NOT CHANGE section updated if needed

#### Files to Create/Modify

- `CLAUDE.md` — (modify) add adapter section

#### Implementation Notes

Add to the "New Files Created" section:
```
dkmv/
  adapters/
    __init__.py    # Adapter registry, get_adapter(), infer_agent_from_model()
    base.py        # AgentAdapter Protocol, StreamResult dataclass
    claude.py      # ClaudeCodeAdapter
    codex.py       # CodexCLIAdapter
tests/
  unit/
    test_adapters/
      test_base.py    # Registry + validation tests
      test_claude.py  # Claude adapter tests
      test_codex.py   # Codex adapter tests
```

#### Evaluation Checklist

- [ ] `CLAUDE.md` mentions adapters
- [ ] Commit scope `adapter` is documented

---

### T096: Coverage Verification for New Adapter Code

**PRD Reference:** Section 16.3 (Coverage Target)
**Depends on:** T093
**Blocks:** T097
**User Stories:** N/A (quality)
**Estimated scope:** 1 hour

#### Description

Verify that new adapter code has >= 90% test coverage. Add tests for any gaps found.

#### Acceptance Criteria

- [ ] `dkmv/adapters/base.py` coverage >= 90%
- [ ] `dkmv/adapters/claude.py` coverage >= 90%
- [ ] `dkmv/adapters/codex.py` coverage >= 90%
- [ ] `dkmv/adapters/__init__.py` coverage >= 90%
- [ ] Overall project coverage >= 80%

#### Files to Create/Modify

- Various test files — (modify) fill coverage gaps if found

#### Implementation Notes

Run coverage with source filter:
```bash
uv run pytest tests/unit/test_adapters/ -v --cov dkmv/adapters/ --cov-report term-missing
```

Review the "Missing" column and add tests for any uncovered lines. Common gaps:
- Error branches in parse_event()
- Edge cases in build_command()
- Auth fallback paths

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_adapters/ -v --cov dkmv/adapters/ --cov-fail-under=90` passes

---

### T097: Final Regression Test Pass

**PRD Reference:** Section 18 (Overall Success Criteria)
**Depends on:** T090, T091, T092, T093, T094, T095, T096
**Blocks:** T098
**User Stories:** All
**Estimated scope:** 30 min

#### Description

Run the complete test suite, all quality gates, and verify all success criteria.

#### Acceptance Criteria

- [ ] `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all pass, coverage >= 80%
- [ ] `uv run ruff check .` — clean
- [ ] `uv run ruff format --check .` — clean
- [ ] `uv run mypy dkmv/` — passes
- [ ] Adapter coverage >= 90%: `uv run pytest tests/unit/test_adapters/ --cov dkmv/adapters/ --cov-fail-under=90`
- [ ] Both adapters functional: `python -c "from dkmv.adapters import get_adapter; [print(get_adapter(n).name) for n in ('claude', 'codex')]"`

#### Files to Create/Modify

- None — verification only

#### Implementation Notes

Full quality gate + feature verification:
```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy dkmv/
uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short
uv run pytest tests/unit/test_adapters/ -v --cov dkmv/adapters/ --cov-fail-under=90
python -c "from dkmv.adapters import get_adapter; [print(get_adapter(n).name) for n in ('claude', 'codex')]"
python -c "from dkmv.adapters import infer_agent_from_model; print(infer_agent_from_model('gpt-5.3-codex'))"
```

#### Evaluation Checklist

- [ ] All commands above succeed
- [ ] Zero test failures
- [ ] Zero lint warnings

---

### T098: Quality Gates Verification

**PRD Reference:** Section 18
**Depends on:** T097
**Blocks:** Nothing
**User Stories:** All
**Estimated scope:** 15 min

#### Description

Final sign-off: verify all quality gates pass, all evaluation criteria met, no regressions.

#### Acceptance Criteria

- [ ] All quality gates green
- [ ] All 4 phase evaluation criteria verified
- [ ] All 10 features have corresponding tests
- [ ] All 21 user stories traceable to at least one test

#### Files to Create/Modify

- None — verification only

#### Implementation Notes

Cross-reference the user stories traceability matrix against test files to verify coverage:
- US-01 through US-04: test_adapters/test_base.py, test_claude.py
- US-05 through US-07: test_adapters/test_codex.py
- US-08 through US-09: test_adapters/test_resolution.py
- US-10 through US-11: test_adapters/test_base.py (inference/validation)
- US-12 through US-13: test_dockerfile.py, test_cli_build.py
- US-14 through US-15: test_init.py, test_config.py
- US-16 through US-17: test_component_multiagent.py
- US-18 through US-19: test_codex.py (event normalization)
- US-20 through US-21: test_cli_agent.py

#### Evaluation Checklist

- [ ] All quality gates pass
- [ ] Project is ready for review
