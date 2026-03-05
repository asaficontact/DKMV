# Multi-Agent Adapter Architecture — Implementation Guide

## What We're Implementing

Add Codex CLI as a second agent backend to DKMV via an adapter pattern: `AgentAdapter` Protocol, `ClaudeCodeAdapter` (refactor), `CodexCLIAdapter` (new), 7-level agent resolution cascade, and mixed-agent component support.

- **PRD:** `.agent/prd.md` (read-only — do not modify)
- **Implementation docs:** `docs/implementation/codex-adapter/`

## Document Map

- `tasks.md` — Master task list. Start here for the current phase.
- `features.md` — Feature registry (F1-F10) with dependencies.
- `user_stories.md` — User stories (US-01 through US-21) with acceptance criteria.
- `phase1_adapter_foundation.md` — Phase 1: Protocol + ClaudeCodeAdapter extraction (T010-T022).
- `phase2_codex_agent_selection.md` — Phase 2: CodexCLIAdapter + agent resolution (T030-T050).
- `phase3_docker_init_integration.md` — Phase 3: Docker + init + mixed-agent (T060-T075).
- `phase4_polish_verification.md` — Phase 4: Polish + verification (T090-T098).
- `progress.md` — Session log. Update after every session.

## Relevant ADRs

- ADR-0002: Claude Code Only for v1 — superseded by this work (multi-agent adapter)
- ADR-0007: Config via environment variables only — unchanged; new fields (CODEX_API_KEY, DKMV_AGENT) follow the same env var pattern
- ADR-0009: Project-scoped configuration — additive changes only (codex_api_key_source, defaults.agent)
- ADR-0012: YAML Manifest Component System — additive agent field to ComponentManifest and ManifestTaskRef

## Implementation Process

Work through phases sequentially. For each phase:

### 1. Read the Phase Document

Open `phaseN_*.md`. Read Prerequisites, Phase Goal, and Phase Evaluation Criteria before touching any code.

### 2. Implement Tasks in Order

Work through each task (T-IDs) sequentially. For each task:
- Read Description, Acceptance Criteria, Files to Create/Modify, and Implementation Notes
- **Verify implementation notes against actual code** — trust the code, not the doc
- Implement the task
- Check off Acceptance Criteria in the phase doc
- Check off the task in `tasks.md`

### 3. Verify the Phase

After all tasks complete:
- Run every command in Phase Evaluation Criteria
- All must pass. Fix issues before proceeding.

### 4. Review Pass

Second pass:
- Re-read phase doc, verify nothing missed
- Run full test suite to catch regressions
- Check linting and type checking

### 5. Update Progress

Add session entry to `progress.md` with tasks completed, blockers, discoveries, coverage, quality.

### 6. Proceed to Next Phase

Only when all tasks checked off, evaluation criteria pass, quality gates green.

## Quality Gates

Every phase must pass:

- `uv run ruff check .` — clean (zero warnings)
- `uv run ruff format --check .` — clean
- `uv run mypy dkmv/` — passes
- `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all tests pass, coverage >= 80%
- Phase 4 additionally: `uv run pytest tests/unit/test_adapters/ --cov dkmv/adapters/ --cov-fail-under=90` — adapter coverage >= 90%

## Conventions

- Conventional Commits: `<type>[scope]: <description>` (types: feat, fix, test, docs, refactor)
- Scopes: `adapter`, `config`, `cli`, `sandbox`, `init`, `project`, `registry`, `rename`
- Test files mirror source: `dkmv/adapters/claude.py` → `tests/unit/test_adapters/test_claude.py`
- Use `tmp_path` for file I/O, `monkeypatch.setenv()` for env vars, `monkeypatch.chdir()` for CWD
- Python 3.12+, `str | None` not `Optional[str]`, `list[str]` not `List[str]`

## Existing Core Interfaces

### DKMVConfig (`dkmv/config.py`)
```python
class DKMVConfig(BaseSettings):
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    github_token: str = Field(default="", validation_alias="GITHUB_TOKEN")
    default_model: str = Field(default="claude-sonnet-4-6", validation_alias="DKMV_MODEL")
    default_max_turns: int = Field(default=100, validation_alias="DKMV_MAX_TURNS")
    image_name: str = Field(default="dkmv-sandbox:latest", validation_alias="DKMV_IMAGE")
    output_dir: Path = Field(default=Path("./outputs"), validation_alias="DKMV_OUTPUT_DIR")
    timeout_minutes: int = Field(default=30, validation_alias="DKMV_TIMEOUT")
    memory_limit: str = Field(default="8g", validation_alias="DKMV_MEMORY")
    max_budget_usd: float | None = Field(default=None, validation_alias="DKMV_MAX_BUDGET_USD")
```

### SandboxManager (`dkmv/core/sandbox.py`)
```python
class SandboxManager:
    async def stream_claude(self, session, prompt, model, max_turns, timeout_minutes, ...) -> AsyncIterator[dict]:
        # Phase 1: becomes thin wrapper around stream_agent()
```

### ComponentRunner (`dkmv/tasks/component.py`)
```python
class ComponentRunner:
    async def run(self, component_dir, repo, branch, feature_name, variables,
                  config, cli_overrides, keep_alive, verbose) -> ComponentResult:
```

## New Files Created by This Work

```
dkmv/
  adapters/
    __init__.py    # Adapter registry, get_adapter(), infer_agent_from_model(), validate_agent_model()
    base.py        # AgentAdapter Protocol, StreamResult dataclass
    claude.py      # ClaudeCodeAdapter — extracted from sandbox.py, stream.py, component.py
    codex.py       # CodexCLIAdapter — new Codex CLI support
tests/
  unit/
    test_adapters/
      __init__.py
      test_base.py        # Registry + inference + validation tests
      test_claude.py      # Claude adapter tests + regression tests
      test_codex.py       # Codex adapter tests
      test_resolution.py  # 7-level agent resolution cascade tests
      test_edge_cases.py  # Edge case tests
    test_dockerfile.py        # Dockerfile content verification
    test_cli_build.py         # Build command --codex-version tests
    test_cli_agent.py         # CLI --agent flag tests
    test_component_multiagent.py  # Mixed-agent component tests
```

## DO NOT CHANGE

The following are stable and must not be modified except as specified in phase docs:

- `dkmv/core/models.py` — Shared types
- `dkmv/tasks/models.py` — Task models (Phase 2 adds `agent` field only)
- `dkmv/tasks/loader.py` — TaskLoader
- `dkmv/components/base.py` — BaseComponent
- Existing test files — do NOT modify existing tests (add new test files only)
- `.agent/prd.md` — PRD (read-only)
