from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest


# --- T005/T031: SWE-ReX mock fixtures (aligned with actual API) ---


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
    """Mock mirroring swerex RemoteRuntime interface."""
    runtime = AsyncMock()
    runtime.create_session = AsyncMock()
    runtime.run_in_session = AsyncMock(return_value=mock_bash_observation)
    runtime.write_file = AsyncMock()

    read_response = MagicMock()
    read_response.content = ""
    runtime.read_file = AsyncMock(return_value=read_response)

    runtime.close_session = AsyncMock()
    runtime.close = AsyncMock()
    return runtime


@pytest.fixture
def mock_docker_deployment(mock_remote_runtime: AsyncMock) -> MagicMock:
    """Mock mirroring swerex DockerDeployment with start/stop methods."""
    deployment = MagicMock()
    deployment.start = AsyncMock()
    deployment.stop = AsyncMock()
    deployment.runtime = mock_remote_runtime

    type(deployment).container_name = PropertyMock(return_value="dkmv-sandbox-abc123")

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
