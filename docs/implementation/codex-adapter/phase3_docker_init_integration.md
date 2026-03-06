# Phase 3: Docker & Init Integration

## Prerequisites

- Phase 2 complete: all tasks T030-T050 done, all quality gates green
- `CodexCLIAdapter` fully implemented and registered
- Agent resolution cascade (7 levels) working
- `--agent` flag on all CLI run commands
- `DKMVConfig.codex_api_key` and `DKMVConfig.default_agent` fields exist
- `CredentialSources.codex_api_key_source` and `ProjectDefaults.agent` fields exist

## Phase Goal

Codex CLI is installed in the Docker image, `dkmv init` discovers Codex credentials, `dkmv build` accepts `--codex-version`, and mixed-agent components pass all required credentials into the container.

## Phase Evaluation Criteria

- `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all pass, coverage >= 80%
- `uv run ruff check .` — clean
- `uv run ruff format --check .` — clean
- `uv run mypy dkmv/` — passes
- `grep -q "CODEX_VERSION" dkmv/images/Dockerfile` — Codex version ARG exists
- `grep -q "@openai/codex" dkmv/images/Dockerfile` — Codex install line exists
- `grep -q "codex_api_key_source" dkmv/init.py` — Codex credential discovery exists
- `grep -q "codex.version" dkmv/cli.py || grep -q "codex_version" dkmv/cli.py` — --codex-version flag exists
- `uv run pytest tests/unit/test_init.py -v` — init tests pass (including new Codex credential tests)
- `uv run pytest tests/unit/test_adapters/ -v` — all adapter tests pass

---

## Tasks

### T060: Update Dockerfile — Install Codex CLI

**PRD Reference:** Section 11.1 (Multi-Agent Image)
**Depends on:** Phase 2 complete
**Blocks:** T061
**User Stories:** US-12
**Estimated scope:** 45 min

#### Description

Update `dkmv/images/Dockerfile` to install Codex CLI alongside Claude Code with version pinning via a build arg.

#### Acceptance Criteria

- [ ] `ARG CODEX_VERSION=0.110.0` build arg added
- [ ] `npm install -g @openai/codex@${CODEX_VERSION}` installs Codex
- [ ] Codex install happens AFTER Claude Code install (same npm layer or separate)
- [ ] All existing Claude Code config unchanged: `IS_SANDBOX`, `CLAUDE_CODE_DISABLE_NONINTERACTIVE_CHECK`, `NODE_OPTIONS`, `.claude.json`
- [ ] Existing `ARG CLAUDE_CODE_VERSION` unchanged

#### Files to Create/Modify

- `dkmv/images/Dockerfile` — (modify) add Codex CLI installation

#### Implementation Notes

Add after the existing Claude Code install line:

```dockerfile
# Existing (unchanged)
ARG CLAUDE_CODE_VERSION=2.1.47
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# NEW — Install Codex CLI
ARG CODEX_VERSION=0.110.0
RUN npm install -g @openai/codex@${CODEX_VERSION}
```

The install should happen as root (before `USER dkmv`), same as Claude Code. Check the current Dockerfile structure to ensure the install is in the right layer.

**Do NOT change** any of these existing lines:
- `ENV IS_SANDBOX=1`
- `ENV CLAUDE_CODE_DISABLE_NONINTERACTIVE_CHECK=1`
- `ENV NODE_OPTIONS="--max-old-space-size=4096"`
- `RUN echo '{"hasCompletedOnboarding":true}' > /home/dkmv/.claude.json`
- `RUN pipx install swe-rex`

#### Evaluation Checklist

- [ ] `grep -q "CODEX_VERSION" dkmv/images/Dockerfile`
- [ ] `grep -q "@openai/codex" dkmv/images/Dockerfile`

---

### T061: Add Codex Config File in Dockerfile

**PRD Reference:** Section 11.3 (Codex Configuration), Appendix D
**Depends on:** T060
**Blocks:** T070
**User Stories:** US-12
**Estimated scope:** 30 min

#### Description

Pre-create `~/.codex/config.toml` in the Dockerfile for headless Docker usage.

#### Acceptance Criteria

- [ ] `~/.codex/config.toml` is created with sandbox and network settings
- [ ] Directory `~/.codex/` has correct ownership (`dkmv:dkmv`)
- [ ] Config is created AFTER the `USER dkmv` line or ownership is set explicitly

#### Files to Create/Modify

- `dkmv/images/Dockerfile` — (modify) add Codex config setup

#### Implementation Notes

Add after the Codex install, but ensure correct user ownership. If the Codex install happens as root, do the config setup later as the `dkmv` user, or set `chown`:

```dockerfile
# Pre-configure Codex for headless Docker usage
RUN mkdir -p /home/dkmv/.codex \
    && printf '[sandbox_workspace_write]\nnetwork_access = true\n' \
       > /home/dkmv/.codex/config.toml \
    && chown -R dkmv:dkmv /home/dkmv/.codex
```

Use the config format from Appendix D. The `model` setting is intentionally omitted from config — it's set at runtime via `-m` flag.

#### Evaluation Checklist

- [ ] `grep -q "config.toml" dkmv/images/Dockerfile`
- [ ] `grep -q ".codex" dkmv/images/Dockerfile`

---

### T062: Add --codex-version Flag to dkmv build Command

**PRD Reference:** Section 11.4 (Build Command Updates)
**Depends on:** T060
**Blocks:** T071
**User Stories:** US-13
**Estimated scope:** 30 min

#### Description

Add `--codex-version` option to the `dkmv build` CLI command. Pass as `--build-arg CODEX_VERSION=<value>` to `docker build`.

#### Acceptance Criteria

- [ ] `dkmv build --codex-version 0.110.0` passes the version to Docker build arg
- [ ] `dkmv build` without `--codex-version` defaults to `"latest"`
- [ ] Existing `--claude-version` flag unchanged
- [ ] `dkmv build --help` shows `--codex-version` option

#### Files to Create/Modify

- `dkmv/cli.py` — (modify) add --codex-version to build command

#### Implementation Notes

```python
@app.command()
def build(
    no_cache: bool = False,
    claude_version: str = "latest",
    codex_version: Annotated[
        str, typer.Option("--codex-version", help="Codex CLI version to install.")
    ] = "latest",
) -> None:
    cmd = [
        "docker", "build", "-t", config.image_name,
        "--build-arg", f"CLAUDE_CODE_VERSION={claude_version}",
        "--build-arg", f"CODEX_VERSION={codex_version}",
    ]
    # ... rest unchanged
```

#### Evaluation Checklist

- [ ] `dkmv build --help 2>&1 | grep -q codex-version`
- [ ] `uv run mypy dkmv/cli.py` passes

---

### T063: Add discover_codex_key() to init.py

**PRD Reference:** Section 9.4 (Init Flow Changes)
**Depends on:** Phase 2 complete
**Blocks:** T064, T065
**User Stories:** US-14
**Estimated scope:** 45 min

#### Description

Add `discover_codex_key()` function to `dkmv/init.py` that checks for Codex API credentials in environment variables and `.env` file.

#### Acceptance Criteria

- [ ] `discover_codex_key()` checks `CODEX_API_KEY` env var first
- [ ] Falls back to `OPENAI_API_KEY` env var
- [ ] Falls back to `CODEX_API_KEY` / `OPENAI_API_KEY` in `.env` file
- [ ] Returns `(source: str, found: bool)` tuple
- [ ] Source values: `"env"`, `"env:OPENAI_API_KEY"`, `".env"`, `".env:OPENAI_API_KEY"`, `"none"`

#### Files to Create/Modify

- `dkmv/init.py` — (modify) add discover_codex_key() function

#### Implementation Notes

Follow the same pattern as existing `discover_anthropic_key()` and `discover_github_token()`:

```python
def discover_codex_key(project_root: Path) -> tuple[str, bool]:
    """Discover Codex API key from env or .env file.

    Returns (source, found) where source is one of:
    "env", "env:OPENAI_API_KEY", ".env", ".env:OPENAI_API_KEY", "none"
    """
    # 1. Check CODEX_API_KEY env var
    if os.environ.get("CODEX_API_KEY"):
        return ("env", True)

    # 2. Check OPENAI_API_KEY env var (fallback)
    if os.environ.get("OPENAI_API_KEY"):
        return ("env:OPENAI_API_KEY", True)

    # 3. Check .env file
    env_path = project_root / ".env"
    if env_path.exists():
        content = env_path.read_text()
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("CODEX_API_KEY=") and line.split("=", 1)[1].strip():
                return (".env", True)
            if line.startswith("OPENAI_API_KEY=") and line.split("=", 1)[1].strip():
                return (".env:OPENAI_API_KEY", True)

    return ("none", False)
```

#### Evaluation Checklist

- [ ] `uv run mypy dkmv/init.py` passes
- [ ] `uv run ruff check dkmv/init.py` clean

---

### T064: Extend Init Credential Step — Multi-Agent Auth Options

**PRD Reference:** Section 9.4 (Init Flow Changes)
**Depends on:** T063
**Blocks:** T065
**User Stories:** US-14
**Estimated scope:** 1.5 hours

#### Description

Update the `run_init()` credential step (step 2/4) to offer multi-agent auth method choices when running interactively.

#### Acceptance Criteria

- [ ] Interactive prompt offers: (1) Claude — API Key, (2) Claude — OAuth, (3) Codex — API Key, (4) Both Claude + Codex
- [ ] When "Both" selected, both Claude and Codex credentials are discovered
- [ ] `codex_api_key_source` stored in `CredentialSources`
- [ ] `auth_method` continues to indicate Claude auth method (api_key or oauth)
- [ ] When Codex-only selected, Claude credential fields default appropriately
- [ ] Rich console output shows discovered Codex credential source

#### Files to Create/Modify

- `dkmv/init.py` — (modify) extend credential step in run_init()

#### Implementation Notes

Study the current credential step in `run_init()`. It currently prompts between `api_key` and `oauth` for Claude. Extend with Codex options:

```python
# Current: Choose between api_key and oauth
# New: Extended choices
choices = [
    "1. Claude Code — API Key (ANTHROPIC_API_KEY)",
    "2. Claude Code — OAuth (subscription)",
    "3. Codex CLI — API Key (CODEX_API_KEY / OPENAI_API_KEY)",
    "4. Both Claude Code + Codex CLI",
]
```

When "Codex-only" (choice 3) is selected:
- Call `discover_codex_key()` to find credentials
- Set `auth_method = "api_key"` (default, since no Claude OAuth)
- Set `codex_api_key_source` from discovery result

When "Both" (choice 4) is selected:
- Run existing Claude credential discovery
- Run Codex credential discovery
- Store both sources

The `auth_method` field in `CredentialSources` always refers to Claude auth. Codex auth is tracked separately via `codex_api_key_source`.

#### Evaluation Checklist

- [ ] `uv run mypy dkmv/init.py` passes
- [ ] `uv run ruff check dkmv/init.py` clean

---

### T065: Update Init --yes Mode for Codex Auto-Detection

**PRD Reference:** Section 9.4 (Non-interactive mode)
**Depends on:** T063, T064
**Blocks:** T072
**User Stories:** US-15
**Estimated scope:** 45 min

#### Description

Update the `--yes` (non-interactive) path in `run_init()` to auto-detect Codex credentials alongside Claude credentials.

#### Acceptance Criteria

- [ ] `dkmv init --yes` checks `CODEX_API_KEY` and `OPENAI_API_KEY` without prompting
- [ ] If both Claude and Codex credentials found, both are stored
- [ ] If only Claude credentials found, `codex_api_key_source = "none"`
- [ ] If only Codex credentials found, Claude fields at defaults, `codex_api_key_source` set
- [ ] Console output indicates which credentials were found

#### Files to Create/Modify

- `dkmv/init.py` — (modify) update --yes path

#### Implementation Notes

In the `if yes:` branch of the credential step:

```python
if yes:
    # Existing: auto-detect Claude credentials
    anthropic_source, anthropic_found = discover_anthropic_key(project_root)
    oauth_source, oauth_found = discover_oauth_token(project_root)
    # ... existing logic to choose auth_method ...

    # NEW: auto-detect Codex credentials
    codex_source, codex_found = discover_codex_key(project_root)
    codex_api_key_source = codex_source if codex_found else "none"

    credentials = CredentialSources(
        auth_method=auth_method,
        anthropic_api_key_source=anthropic_source,
        oauth_token_source=oauth_source,
        github_token_source=github_source,
        codex_api_key_source=codex_api_key_source,
    )
```

#### Evaluation Checklist

- [ ] `uv run mypy dkmv/init.py` passes
- [ ] `uv run ruff check dkmv/init.py` clean

---

### T066: Update load_config() for OPENAI_API_KEY Fallback

**PRD Reference:** Section 9.5 (Credential Validation)
**Depends on:** T037
**Blocks:** T073
**User Stories:** US-15
**Estimated scope:** 45 min

#### Description

Update `load_config()` in `config.py` to check `OPENAI_API_KEY` as fallback when `codex_api_key` is empty. Also apply `project_config.defaults.agent` to config.

#### Acceptance Criteria

- [ ] If `config.codex_api_key` is empty, `OPENAI_API_KEY` env var is checked as fallback
- [ ] If `OPENAI_API_KEY` found, `config.codex_api_key` is set to its value
- [ ] If project config has `defaults.agent`, it's applied to `config.default_agent` (only if still at default)
- [ ] Existing Claude credential validation unchanged

#### Files to Create/Modify

- `dkmv/config.py` — (modify) update load_config()

#### Implementation Notes

Add after the existing project config defaults application in `load_config()`:

```python
# OPENAI_API_KEY fallback for Codex
if not config.codex_api_key:
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        config.codex_api_key = openai_key

# Project config agent default
if project_config and project_config.defaults.agent is not None:
    if config.default_agent == "claude":  # Only override if at built-in default
        config.default_agent = project_config.defaults.agent
```

**Important:** The `OPENAI_API_KEY` fallback happens in `load_config()`, not in `DKMVConfig.__init__`. This is because pydantic-settings only reads `CODEX_API_KEY` (the `validation_alias`). The fallback is business logic, not config field mapping.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_config.py -v` — passes (add new tests in T073)
- [ ] `uv run mypy dkmv/config.py` passes

---

### T067: Implement agents_needed Scanning in ComponentRunner

**PRD Reference:** Section 5 (Adapter Lifecycle — agents_needed scanning)
**Depends on:** T039
**Blocks:** T068, T069
**User Stories:** US-16
**Estimated scope:** 1 hour

#### Description

Before the task loop in `ComponentRunner.run()`, scan all task refs to determine the set of agents needed for the component. This set is passed to `_build_sandbox_config()` so all required credentials are included.

#### Acceptance Criteria

- [ ] `agents_needed` set computed from: task YAML agent, task_ref agent, manifest agent, CLI agent, config default
- [ ] If any task uses `agent: codex`, `"codex"` is in agents_needed
- [ ] If no agent specified anywhere, agents_needed contains the default agent
- [ ] agents_needed passed to `_build_sandbox_config()`

#### Files to Create/Modify

- `dkmv/tasks/component.py` — (modify) add agents_needed scanning before task loop

#### Implementation Notes

Add before the task loop, after loading the manifest:

```python
# Determine which agents are needed for this component
agents_needed: set[str] = set()

# Check manifest-level agent
if manifest and manifest.agent:
    agents_needed.add(manifest.agent)

# Check each task ref
for ref in expanded_refs:
    if hasattr(ref, 'agent') and ref.agent:
        agents_needed.add(ref.agent)

# Check task YAML files (if accessible at this point)
# Note: Task YAML agent fields may not be known until task is loaded.
# For now, scan what's available from manifest/task_refs.

# CLI override
if cli_overrides.agent:
    agents_needed.add(cli_overrides.agent)

# Always include default agent
default_agent = cli_overrides.agent or config.default_agent
agents_needed.add(default_agent)

# Pass to _build_sandbox_config
sandbox_config, temp_creds_file = self._build_sandbox_config(
    config, timeout_minutes, agents_needed
)
```

The limitation: task YAML `agent` fields aren't known until tasks are loaded inside the loop. For practical purposes, manifest-level and task_ref-level scanning covers the common mixed-agent case. The worst case of a task YAML specifying `agent: codex` when no task_ref or manifest does means credentials might be missing — but this is an edge case that can be documented.

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/tasks/component.py` passes

---

### T068: Update _build_sandbox_config() for Multi-Agent Credentials

**PRD Reference:** Section 5 (Credential Scanning), Section 14 (R7)
**Depends on:** T067
**Blocks:** T074
**User Stories:** US-16
**Estimated scope:** 1.5 hours

#### Description

Update `_build_sandbox_config()` to accept `agents_needed` and pass credentials for ALL agents into the container environment.

#### Acceptance Criteria

- [ ] `_build_sandbox_config()` accepts `agents_needed: set[str]` parameter
- [ ] When `"claude"` in agents_needed, Claude credentials are included
- [ ] When `"codex"` in agents_needed, Codex credentials are included (`CODEX_API_KEY`)
- [ ] Docker args include mounts for all agents that need them (Claude OAuth)
- [ ] Both `ANTHROPIC_API_KEY` and `CODEX_API_KEY` can coexist in container env
- [ ] GitHub token always included (agent-agnostic)
- [ ] Existing behavior unchanged when only `"claude"` is needed

#### Files to Create/Modify

- `dkmv/tasks/component.py` — (modify) update _build_sandbox_config()

#### Implementation Notes

```python
def _build_sandbox_config(
    self, config: DKMVConfig, timeout_minutes: int,
    agents_needed: set[str] | None = None,
) -> tuple[SandboxConfig, Path | None]:
    if agents_needed is None:
        agents_needed = {"claude"}

    env_vars: dict[str, str] = {}
    docker_args: list[str] = []
    temp_creds_file: Path | None = None

    # Collect credentials for all needed agents
    for agent_name in agents_needed:
        from dkmv.adapters import get_adapter
        adapter = get_adapter(agent_name)
        env_vars.update(adapter.get_auth_env_vars(config))
        extra_args, creds_file = adapter.get_docker_args(config)
        docker_args.extend(extra_args)
        if creds_file is not None:
            temp_creds_file = creds_file

    # GitHub token (always, agent-agnostic)
    if config.github_token:
        env_vars["GITHUB_TOKEN"] = config.github_token

    # ... rest of sandbox config creation unchanged
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/tasks/component.py` passes

---

### T069: Update Workspace .gitignore for Multi-Agent

**PRD Reference:** Section 4 (CP-8), Section 14 (R10)
**Depends on:** T067
**Blocks:** T074
**User Stories:** US-16
**Estimated scope:** 45 min

#### Description

Update the workspace `.gitignore` setup to include entries from ALL agents used in the component, not just Claude.

#### Acceptance Criteria

- [ ] `.gitignore` includes `.claude/` when Claude tasks are present
- [ ] `.gitignore` includes `.codex/` when Codex tasks are present
- [ ] Mixed-agent components get both `.claude/` and `.codex/` entries
- [ ] Duplicate entries are not added

#### Files to Create/Modify

- `dkmv/tasks/component.py` — (modify) update gitignore setup

#### Implementation Notes

In the workspace setup section where `.gitignore` entries are added, collect entries from all agents:

```python
# Collect gitignore entries from all agents
gitignore_entries: list[str] = []
for agent_name in agents_needed:
    adapter = get_adapter(agent_name)
    gitignore_entries.extend(adapter.gitignore_entries)

# Add each entry to .gitignore if not already present
for entry in gitignore_entries:
    gitignore_cmds.append(
        f"(grep -qxF '{entry}' .gitignore 2>/dev/null"
        f" || echo '{entry}' >> .gitignore)"
    )
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/ -v --tb=short -x` — all pass
- [ ] `uv run mypy dkmv/tasks/component.py` passes

---

### T070: Write Dockerfile Verification Tests

**PRD Reference:** Section 16, F6
**Depends on:** T060, T061
**Blocks:** T075
**User Stories:** US-12
**Estimated scope:** 30 min

#### Description

Write tests that verify the Dockerfile contains the expected Codex configuration.

#### Acceptance Criteria

- [ ] Test: Dockerfile contains `ARG CODEX_VERSION`
- [ ] Test: Dockerfile contains `@openai/codex@${CODEX_VERSION}`
- [ ] Test: Dockerfile contains `config.toml` setup
- [ ] Test: Existing Claude config unchanged (IS_SANDBOX, onboarding, etc.)

#### Files to Create/Modify

- `tests/unit/test_dockerfile.py` — (create) Dockerfile content verification tests

#### Implementation Notes

```python
from pathlib import Path

DOCKERFILE = Path(__file__).parent.parent.parent / "dkmv" / "images" / "Dockerfile"

def test_dockerfile_has_codex_version_arg():
    content = DOCKERFILE.read_text()
    assert "ARG CODEX_VERSION" in content

def test_dockerfile_installs_codex():
    content = DOCKERFILE.read_text()
    assert "@openai/codex@${CODEX_VERSION}" in content

def test_dockerfile_has_codex_config():
    content = DOCKERFILE.read_text()
    assert "config.toml" in content

def test_dockerfile_preserves_claude_config():
    content = DOCKERFILE.read_text()
    assert "IS_SANDBOX=1" in content
    assert "CLAUDE_CODE_DISABLE_NONINTERACTIVE_CHECK=1" in content
    assert "hasCompletedOnboarding" in content
    assert "@anthropic-ai/claude-code" in content
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_dockerfile.py -v` — all pass

---

### T071: Write Build Command --codex-version Tests

**PRD Reference:** Section 16, US-13
**Depends on:** T062
**Blocks:** T075
**User Stories:** US-13
**Estimated scope:** 30 min

#### Description

Write tests verifying the `--codex-version` flag on `dkmv build`.

#### Acceptance Criteria

- [ ] Test: `dkmv build --help` shows `--codex-version` option
- [ ] Test: `--claude-version` still present
- [ ] Test: both version flags appear in help text

#### Files to Create/Modify

- `tests/unit/test_cli_build.py` — (create) build command tests

#### Implementation Notes

```python
from typer.testing import CliRunner
from dkmv.cli import app

runner = CliRunner()

def test_build_has_codex_version_flag():
    result = runner.invoke(app, ["build", "--help"])
    assert "--codex-version" in result.output

def test_build_has_claude_version_flag():
    result = runner.invoke(app, ["build", "--help"])
    assert "--claude-version" in result.output
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_cli_build.py -v` — all pass

---

### T072: Write Init Codex Credential Discovery Tests

**PRD Reference:** Section 16.2, US-14, US-15
**Depends on:** T063, T064, T065
**Blocks:** T075
**User Stories:** US-14, US-15
**Estimated scope:** 1.5 hours

#### Description

Write tests for Codex credential discovery in `dkmv init`.

#### Acceptance Criteria

- [ ] Test: `discover_codex_key()` finds `CODEX_API_KEY` env var
- [ ] Test: `discover_codex_key()` falls back to `OPENAI_API_KEY` env var
- [ ] Test: `discover_codex_key()` finds key in `.env` file
- [ ] Test: `discover_codex_key()` returns `("none", False)` when no key found
- [ ] Test: `--yes` mode auto-detects Codex credentials
- [ ] Test: `--yes` mode sets `codex_api_key_source` correctly
- [ ] Test: both Claude and Codex credentials discovered together

#### Files to Create/Modify

- `tests/unit/test_init.py` — (modify) add Codex credential tests

#### Implementation Notes

```python
def test_discover_codex_key_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_API_KEY", "sk-test")
    source, found = discover_codex_key(tmp_path)
    assert source == "env"
    assert found is True

def test_discover_codex_key_openai_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    source, found = discover_codex_key(tmp_path)
    assert source == "env:OPENAI_API_KEY"
    assert found is True

def test_discover_codex_key_none(monkeypatch, tmp_path):
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    source, found = discover_codex_key(tmp_path)
    assert source == "none"
    assert found is False
```

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_init.py -v` — all pass (including new tests)

---

### T073: Write load_config() OPENAI_API_KEY Fallback Tests

**PRD Reference:** Section 9.5, US-15
**Depends on:** T066
**Blocks:** T075
**User Stories:** US-15
**Estimated scope:** 45 min

#### Description

Write tests for the `OPENAI_API_KEY` fallback logic in `load_config()`.

#### Acceptance Criteria

- [ ] Test: `CODEX_API_KEY` set → config.codex_api_key has value
- [ ] Test: only `OPENAI_API_KEY` set → config.codex_api_key has OPENAI_API_KEY value
- [ ] Test: neither set → config.codex_api_key is empty
- [ ] Test: project defaults.agent applied to config.default_agent
- [ ] Test: DKMV_AGENT env var overrides project defaults.agent

#### Files to Create/Modify

- `tests/unit/test_config.py` — (modify) add Codex credential fallback tests

#### Implementation Notes

```python
def test_codex_api_key_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_API_KEY", "sk-codex")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    config = load_config()
    assert config.codex_api_key == "sk-codex"

def test_codex_api_key_openai_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    config = load_config()
    assert config.codex_api_key == "sk-openai"
```

Use `monkeypatch.chdir(tmp_path)` and create a `.dkmv/config.json` for project defaults tests.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_config.py -v` — all pass

---

### T074: Write Mixed-Agent Component Tests

**PRD Reference:** Section 14 (R7), US-16, US-17
**Depends on:** T067, T068, T069
**Blocks:** T075
**User Stories:** US-16, US-17
**Estimated scope:** 1.5 hours

#### Description

Write tests for mixed-agent component scenarios: agents_needed scanning, multi-agent credential passing, and per-task adapter instantiation.

#### Acceptance Criteria

- [ ] Test: agents_needed includes both `claude` and `codex` when manifest tasks use both
- [ ] Test: _build_sandbox_config() env vars include both `ANTHROPIC_API_KEY` and `CODEX_API_KEY`
- [ ] Test: gitignore includes both `.claude/` and `.codex/`
- [ ] Test: single-agent component only includes that agent's credentials

#### Files to Create/Modify

- `tests/unit/test_component_multiagent.py` — (create) mixed-agent tests

#### Implementation Notes

```python
from dkmv.tasks.manifest import ComponentManifest, ManifestTaskRef

def test_agents_needed_mixed_manifest():
    manifest = ComponentManifest(
        name="test",
        agent="claude",
        tasks=[
            ManifestTaskRef(file="plan.yaml", agent="claude"),
            ManifestTaskRef(file="implement.yaml", agent="codex"),
        ],
    )
    agents_needed = set()
    if manifest.agent:
        agents_needed.add(manifest.agent)
    for ref in manifest.tasks:
        if ref.agent:
            agents_needed.add(ref.agent)
    assert agents_needed == {"claude", "codex"}
```

For `_build_sandbox_config()` tests, mock the adapter `get_auth_env_vars()` and verify the env vars dict contains keys for both agents.

#### Evaluation Checklist

- [ ] `uv run pytest tests/unit/test_component_multiagent.py -v` — all pass

---

### T075: Full Test Suite and Integration Verification

**PRD Reference:** Section 18 (Evaluation Criteria)
**Depends on:** T070, T071, T072, T073, T074
**Blocks:** Nothing
**User Stories:** All Phase 3 stories
**Estimated scope:** 30 min

#### Description

Run the complete test suite and all quality gates to verify Phase 3 is complete.

#### Acceptance Criteria

- [ ] `uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short` — all pass, coverage >= 80%
- [ ] `uv run ruff check .` — clean
- [ ] `uv run ruff format --check .` — clean
- [ ] `uv run mypy dkmv/` — passes
- [ ] Dockerfile has both agent installs
- [ ] Init discovers Codex credentials
- [ ] Build command accepts --codex-version

#### Files to Create/Modify

- None — verification only

#### Implementation Notes

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy dkmv/
uv run pytest tests/ -v --cov --cov-fail-under=80 --tb=short
```

#### Evaluation Checklist

- [ ] All quality gates pass
- [ ] All Phase 3 evaluation criteria met
