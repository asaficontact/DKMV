"""Tests verifying Dockerfile content for multi-agent support."""

from pathlib import Path

DOCKERFILE = Path(__file__).parent.parent.parent / "dkmv" / "images" / "Dockerfile"


def test_dockerfile_has_codex_version_arg() -> None:
    content = DOCKERFILE.read_text()
    assert "ARG CODEX_VERSION" in content


def test_dockerfile_installs_codex() -> None:
    content = DOCKERFILE.read_text()
    assert "@openai/codex@${CODEX_VERSION}" in content


def test_dockerfile_has_codex_config() -> None:
    content = DOCKERFILE.read_text()
    assert "config.toml" in content


def test_dockerfile_has_codex_dir() -> None:
    content = DOCKERFILE.read_text()
    assert ".codex" in content


def test_dockerfile_preserves_claude_config() -> None:
    content = DOCKERFILE.read_text()
    assert "IS_SANDBOX=1" in content
    assert "CLAUDE_CODE_DISABLE_NONINTERACTIVE_CHECK=1" in content
    assert "hasCompletedOnboarding" in content
    assert "@anthropic-ai/claude-code" in content


def test_dockerfile_claude_version_arg_unchanged() -> None:
    content = DOCKERFILE.read_text()
    assert "ARG CLAUDE_CODE_VERSION" in content


def test_dockerfile_codex_install_after_claude() -> None:
    content = DOCKERFILE.read_text()
    claude_pos = content.find("@anthropic-ai/claude-code")
    codex_pos = content.find("@openai/codex")
    assert claude_pos != -1
    assert codex_pos != -1
    assert codex_pos > claude_pos


def test_dockerfile_installs_docker_cli() -> None:
    content = DOCKERFILE.read_text()
    assert "docker-ce-cli" in content


def test_dockerfile_installs_docker_compose_plugin() -> None:
    content = DOCKERFILE.read_text()
    assert "docker-compose-plugin" in content


def test_dockerfile_docker_group_for_dkmv_user() -> None:
    content = DOCKERFILE.read_text()
    assert "groupadd -f docker" in content
    assert "usermod -aG docker dkmv" in content


def test_dockerfile_installs_playwright_chromium() -> None:
    content = DOCKERFILE.read_text()
    assert "PLAYWRIGHT_BROWSERS_PATH" in content
    assert "playwright install --with-deps chromium" in content
