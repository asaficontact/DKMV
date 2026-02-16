from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from dkmv.core.models import SandboxConfig
from dkmv.core.sandbox import SandboxManager


class TestSandboxIntegration:
    @patch("dkmv.core.sandbox.DockerDeployment")
    async def test_full_lifecycle(
        self, mock_dd_cls: MagicMock, mock_remote_runtime: AsyncMock
    ) -> None:
        """Test start → execute → read_file → write_file → stop lifecycle."""
        mock_dep = MagicMock()
        mock_dep.start = AsyncMock()
        mock_dep.stop = AsyncMock()
        mock_dep.runtime = mock_remote_runtime
        type(mock_dep).container_name = PropertyMock(return_value="test-container")
        mock_dd_cls.return_value = mock_dep

        obs = MagicMock()
        obs.output = "hello world"
        obs.exit_code = 0
        obs.failure_reason = ""
        mock_remote_runtime.run_in_session = AsyncMock(return_value=obs)

        read_resp = MagicMock()
        read_resp.content = "file content"
        mock_remote_runtime.read_file = AsyncMock(return_value=read_resp)

        manager = SandboxManager()
        config = SandboxConfig(image="test:latest", memory_limit="2g")

        # Start
        session = await manager.start(config, "dev")
        assert session.container_name == "test-container"

        # Execute
        result = await manager.execute(session, "echo hello")
        assert result.output == "hello world"
        assert result.exit_code == 0

        # Write file
        await manager.write_file(session, "/tmp/test.txt", "data")
        mock_remote_runtime.write_file.assert_awaited()

        # Read file
        content = await manager.read_file(session, "/tmp/test.txt")
        assert content == "file content"

        # Stop
        await manager.stop(session)
        mock_dep.stop.assert_awaited_once()

    @patch("dkmv.core.sandbox.DockerDeployment")
    async def test_env_vars_and_memory_in_docker_args(
        self, mock_dd_cls: MagicMock, mock_remote_runtime: AsyncMock
    ) -> None:
        mock_dep = MagicMock()
        mock_dep.start = AsyncMock()
        mock_dep.runtime = mock_remote_runtime
        type(mock_dep).container_name = PropertyMock(return_value="c")
        mock_dd_cls.return_value = mock_dep

        config = SandboxConfig(
            env_vars={"KEY": "val"},
            memory_limit="16g",
        )
        manager = SandboxManager()
        await manager.start(config, "test")

        docker_args = mock_dd_cls.call_args.kwargs["docker_args"]
        assert "--memory=16g" in docker_args
        assert "-e=KEY=val" in docker_args

    @patch("dkmv.core.sandbox.DockerDeployment")
    async def test_git_auth_setup(
        self, mock_dd_cls: MagicMock, mock_remote_runtime: AsyncMock
    ) -> None:
        mock_dep = MagicMock()
        mock_dep.start = AsyncMock()
        mock_dep.runtime = mock_remote_runtime
        type(mock_dep).container_name = PropertyMock(return_value="c")
        mock_dd_cls.return_value = mock_dep

        obs = MagicMock()
        obs.output = ""
        obs.exit_code = 0
        obs.failure_reason = ""
        mock_remote_runtime.run_in_session = AsyncMock(return_value=obs)

        manager = SandboxManager()
        config = SandboxConfig()
        session = await manager.start(config, "dev")

        result = await manager.setup_git_auth(session)
        assert result.exit_code == 0

        call_args = mock_remote_runtime.run_in_session.call_args[0][0]
        assert "gh auth login" in call_args.command
