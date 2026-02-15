from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# SWE-ReX API v1.4.0 types (not imported — runtime dep, not installed in Phase 0):
#   swerex.deployment.docker.DockerDeployment
#   swerex.runtime.abstract.BashAction, BashObservation, CreateBashSessionRequest


# --- T005: SWE-ReX mock fixtures ---


@pytest.fixture
def mock_bash_observation() -> MagicMock:
    """Mock mirroring swerex.runtime.abstract.BashObservation fields."""
    obs = MagicMock()
    obs.output = ""
    obs.exit_code = 0
    obs.failure_reason = ""
    return obs


@pytest.fixture
def mock_remote_runtime(mock_bash_observation: MagicMock) -> AsyncMock:
    """Mock mirroring swerex RemoteRuntime interface.

    TODO(T031): Align with actual RemoteRuntime API.
    """
    runtime = AsyncMock()
    runtime.create_session = AsyncMock()
    runtime.run_in_session = AsyncMock(return_value=mock_bash_observation)
    runtime.write_file = AsyncMock()
    runtime.read_file = AsyncMock(return_value="")
    return runtime


@pytest.fixture
def mock_docker_deployment(mock_remote_runtime: AsyncMock) -> AsyncMock:
    """Mock mirroring swerex DockerDeployment with async context manager support.

    TODO(T031): Align with actual DockerDeployment API.
    """
    deployment = AsyncMock()
    deployment.__aenter__ = AsyncMock(return_value=deployment)
    deployment.__aexit__ = AsyncMock(return_value=False)
    deployment.runtime = mock_remote_runtime
    return deployment


# --- T006: MockSandboxSession ---


class MockSandboxSession:
    """Records sandbox commands for assertion in integration tests."""

    def __init__(self, default_response: str = "") -> None:
        self.commands: list[str] = []
        self.default_response = default_response
        self._responses: dict[str, str] = {}

    def set_response(self, command: str, response: str) -> None:
        self._responses[command] = response

    async def execute(self, command: str, **kwargs: object) -> str:
        self.commands.append(command)
        return self._responses.get(command, self.default_response)

    def assert_command_executed(self, command: str) -> None:
        assert command in self.commands, (
            f"Expected command {command!r} was not executed.\nExecuted commands: {self.commands}"
        )

    def assert_commands_in_order(self, expected: list[str]) -> None:
        """Assert expected commands appear in order (non-consecutive matching)."""
        idx = 0
        for cmd in self.commands:
            if idx < len(expected) and cmd == expected[idx]:
                idx += 1
        assert idx == len(expected), (
            f"Commands not found in order.\n"
            f"Expected: {expected}\n"
            f"Actual: {self.commands}\n"
            f"Matched up to index {idx}"
        )

    @property
    def command_count(self) -> int:
        return len(self.commands)

    def reset(self) -> None:
        self.commands.clear()
        self._responses.clear()


@pytest.fixture
def mock_sandbox_session() -> MockSandboxSession:
    return MockSandboxSession()
