from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from dkmv.core.models import SandboxConfig
from dkmv.core.sandbox import CommandResult, SandboxManager, SandboxSession


@pytest.fixture
def sandbox_manager() -> SandboxManager:
    return SandboxManager()


@pytest.fixture
def mock_deployment() -> MagicMock:
    deployment = MagicMock()
    deployment.start = AsyncMock()
    deployment.stop = AsyncMock()

    runtime = AsyncMock()
    runtime.create_session = AsyncMock()
    runtime.close_session = AsyncMock()
    runtime.close = AsyncMock()

    obs = MagicMock()
    obs.output = "hello"
    obs.exit_code = 0
    obs.failure_reason = ""
    runtime.run_in_session = AsyncMock(return_value=obs)
    runtime.write_file = AsyncMock()

    read_resp = MagicMock()
    read_resp.content = "file content"
    runtime.read_file = AsyncMock(return_value=read_resp)

    deployment.runtime = runtime
    type(deployment).container_name = PropertyMock(return_value="dkmv-sandbox-test123")

    return deployment


@pytest.fixture
def session(mock_deployment: MagicMock) -> SandboxSession:
    return SandboxSession(
        deployment=mock_deployment,
        session_name="main",
        container_name="dkmv-sandbox-test123",
    )


class TestSandboxManagerStart:
    @patch("dkmv.core.sandbox.DockerDeployment")
    async def test_start_creates_deployment_and_session(
        self, mock_dd_cls: MagicMock, sandbox_manager: SandboxManager
    ) -> None:
        mock_dep = MagicMock()
        mock_dep.start = AsyncMock()
        mock_dep.runtime = AsyncMock()
        mock_dep.runtime.create_session = AsyncMock()
        type(mock_dep).container_name = PropertyMock(return_value="container-abc")
        mock_dd_cls.return_value = mock_dep

        config = SandboxConfig(image="test:latest", memory_limit="4g")
        session = await sandbox_manager.start(config, "dev")

        mock_dd_cls.assert_called_once()
        call_kwargs = mock_dd_cls.call_args.kwargs
        assert call_kwargs["image"] == "test:latest"
        assert call_kwargs["pull"] == "missing"
        assert call_kwargs["remove_container"] is True
        assert "--memory=4g" in call_kwargs["docker_args"]

        mock_dep.start.assert_awaited_once()
        mock_dep.runtime.create_session.assert_awaited_once()
        assert session.container_name == "container-abc"

    @patch("dkmv.core.sandbox.DockerDeployment")
    async def test_start_env_vars_forwarded(
        self, mock_dd_cls: MagicMock, sandbox_manager: SandboxManager
    ) -> None:
        mock_dep = MagicMock()
        mock_dep.start = AsyncMock()
        mock_dep.runtime = AsyncMock()
        mock_dep.runtime.create_session = AsyncMock()
        type(mock_dep).container_name = PropertyMock(return_value="c")
        mock_dd_cls.return_value = mock_dep

        config = SandboxConfig(env_vars={"API_KEY": "secret", "FOO": "bar"})
        await sandbox_manager.start(config, "dev")

        docker_args = mock_dd_cls.call_args.kwargs["docker_args"]
        assert "-e=API_KEY=secret" in docker_args
        assert "-e=FOO=bar" in docker_args

    @patch("dkmv.core.sandbox.DockerDeployment")
    async def test_start_keep_alive_preserves_container(
        self, mock_dd_cls: MagicMock, sandbox_manager: SandboxManager
    ) -> None:
        mock_dep = MagicMock()
        mock_dep.start = AsyncMock()
        mock_dep.runtime = AsyncMock()
        mock_dep.runtime.create_session = AsyncMock()
        type(mock_dep).container_name = PropertyMock(return_value="c")
        mock_dd_cls.return_value = mock_dep

        config = SandboxConfig(keep_alive=True)
        await sandbox_manager.start(config, "dev")

        assert mock_dd_cls.call_args.kwargs["remove_container"] is False


class TestSandboxManagerExecute:
    async def test_execute_returns_command_result(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        result = await sandbox_manager.execute(session, "echo hello")
        assert isinstance(result, CommandResult)
        assert result.output == "hello"
        assert result.exit_code == 0

    async def test_execute_passes_timeout(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        await sandbox_manager.execute(session, "sleep 5", timeout=10.0)
        call_args = session.deployment.runtime.run_in_session.call_args
        action = call_args[0][0]
        assert action.timeout == 10.0
        assert action.check == "silent"


class TestSandboxManagerFileOps:
    async def test_write_file(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        await sandbox_manager.write_file(session, "/tmp/test.txt", "hello")
        session.deployment.runtime.write_file.assert_awaited_once()
        req = session.deployment.runtime.write_file.call_args[0][0]
        assert req.path == "/tmp/test.txt"
        assert req.content == "hello"

    async def test_read_file(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        content = await sandbox_manager.read_file(session, "/tmp/test.txt")
        assert content == "file content"
        session.deployment.runtime.read_file.assert_awaited_once()


class TestSandboxManagerFileExists:
    async def test_file_exists_returns_true(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        obs = MagicMock()
        obs.output = "exists"
        obs.exit_code = 0
        obs.failure_reason = ""
        session.deployment.runtime.run_in_session = AsyncMock(return_value=obs)

        result = await sandbox_manager.file_exists(session, "/tmp/test.txt")
        assert result is True

    async def test_file_exists_returns_false(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        obs = MagicMock()
        obs.output = ""
        obs.exit_code = 1
        obs.failure_reason = ""
        session.deployment.runtime.run_in_session = AsyncMock(return_value=obs)

        result = await sandbox_manager.file_exists(session, "/tmp/missing.txt")
        assert result is False

    async def test_file_exists_quotes_path(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        obs = MagicMock()
        obs.output = ""
        obs.exit_code = 1
        obs.failure_reason = ""
        session.deployment.runtime.run_in_session = AsyncMock(return_value=obs)

        await sandbox_manager.file_exists(session, "/tmp/file with spaces.txt")
        action = session.deployment.runtime.run_in_session.call_args[0][0]
        assert "'/tmp/file with spaces.txt'" in action.command


class TestSandboxManagerStop:
    async def test_stop_calls_deployment_stop(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        await sandbox_manager.stop(session)
        session.deployment.stop.assert_awaited_once()

    async def test_stop_keep_alive_only_closes_runtime(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        await sandbox_manager.stop(session, keep_alive=True)
        session.deployment.runtime.close.assert_awaited_once()
        session.deployment.stop.assert_not_awaited()

    async def test_stop_idempotent_on_error(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        session.deployment.stop = AsyncMock(side_effect=RuntimeError("already stopped"))
        await sandbox_manager.stop(session)  # Should not raise


class TestSandboxManagerHelpers:
    def test_get_container_name(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        assert sandbox_manager.get_container_name(session) == "dkmv-sandbox-test123"

    async def test_create_extra_session(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        await sandbox_manager._create_session(session, "tail")
        assert "tail" in session._extra_sessions
        session.deployment.runtime.create_session.assert_awaited_once()

    async def test_setup_git_auth(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        result = await sandbox_manager.setup_git_auth(session)
        assert isinstance(result, CommandResult)

    async def test_setup_git_auth_runs_setup_git_only(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """Auth uses gh auth setup-git (not gh auth login) since GITHUB_TOKEN env var
        is already set via Docker -e flag."""
        await sandbox_manager.setup_git_auth(session)
        action = session.deployment.runtime.run_in_session.call_args[0][0]
        assert action.command == "gh auth setup-git"
        assert "login" not in action.command


class TestStreamClaude:
    async def test_stream_claude_basic_flow(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """Test stream_claude yields parsed events from JSONL output."""
        import json

        result_event = json.dumps(
            {
                "type": "result",
                "total_cost_usd": 0.05,
                "duration_ms": 5000,
                "num_turns": 3,
                "session_id": "sess-123",
            }
        )
        assistant_event = json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hello"}]},
            }
        )

        # First execute call: launch claude command, return PID
        pid_obs = MagicMock()
        pid_obs.output = "12345"
        pid_obs.exit_code = 0
        pid_obs.failure_reason = ""

        # Kill -0 check: process alive then dead
        alive_obs = MagicMock()
        alive_obs.output = "0"
        alive_obs.exit_code = 0
        alive_obs.failure_reason = ""

        dead_obs = MagicMock()
        dead_obs.output = "1"
        dead_obs.exit_code = 0
        dead_obs.failure_reason = ""

        # Tail reads
        tail_obs_1 = MagicMock()
        tail_obs_1.output = f"{assistant_event}\n{result_event}"
        tail_obs_1.exit_code = 0
        tail_obs_1.failure_reason = ""

        empty_obs = MagicMock()
        empty_obs.output = ""
        empty_obs.exit_code = 0
        empty_obs.failure_reason = ""

        # Sequence: execute(claude cmd) -> [kill -0, tail] per loop iteration
        # Note: _create_session uses runtime.create_session (separate mock)
        session.deployment.runtime.run_in_session = AsyncMock(
            side_effect=[
                pid_obs,  # execute: launch claude
                alive_obs,  # loop 1: kill -0 (alive)
                tail_obs_1,  # loop 1: tail (events, result_seen=True)
                dead_obs,  # loop 2: kill -0 (dead)
                empty_obs,  # loop 2: tail (empty) -> break
            ]
        )
        session.deployment.runtime.create_session = AsyncMock()
        session.deployment.runtime.close_session = AsyncMock()

        events = []
        async for event in sandbox_manager.stream_claude(
            session=session,
            prompt="test prompt",
            model="claude-sonnet-4-6",
            max_turns=10,
            timeout_minutes=5,
        ):
            events.append(event)

        assert len(events) == 2
        assert events[0]["type"] == "assistant"
        assert events[1]["type"] == "result"

    async def test_stream_claude_handles_non_json_lines(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """Non-JSON lines should be skipped without error."""
        import json

        result_event = json.dumps({"type": "result", "total_cost_usd": 0.01})

        pid_obs = MagicMock()
        pid_obs.output = "999"
        pid_obs.exit_code = 0
        pid_obs.failure_reason = ""

        alive_obs = MagicMock()
        alive_obs.output = "0"
        alive_obs.exit_code = 0
        alive_obs.failure_reason = ""

        dead_obs = MagicMock()
        dead_obs.output = "1"
        dead_obs.exit_code = 0
        dead_obs.failure_reason = ""

        tail_obs = MagicMock()
        tail_obs.output = f"not json\n{result_event}"
        tail_obs.exit_code = 0
        tail_obs.failure_reason = ""

        empty_obs = MagicMock()
        empty_obs.output = ""
        empty_obs.exit_code = 0
        empty_obs.failure_reason = ""

        session.deployment.runtime.run_in_session = AsyncMock(
            side_effect=[pid_obs, alive_obs, tail_obs, dead_obs, empty_obs]
        )
        session.deployment.runtime.create_session = AsyncMock()
        session.deployment.runtime.close_session = AsyncMock()

        events = []
        async for event in sandbox_manager.stream_claude(
            session=session,
            prompt="test",
            model="m",
            max_turns=5,
            timeout_minutes=1,
        ):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "result"

    async def test_stream_claude_timeout(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """stream_claude should raise TimeoutError when timeout expires."""
        alive_obs = MagicMock()
        alive_obs.output = "0"
        alive_obs.exit_code = 0
        alive_obs.failure_reason = ""

        empty_obs = MagicMock()
        empty_obs.output = ""
        empty_obs.exit_code = 0
        empty_obs.failure_reason = ""

        pid_obs = MagicMock()
        pid_obs.output = "999"
        pid_obs.exit_code = 0
        pid_obs.failure_reason = ""

        session.deployment.runtime.run_in_session = AsyncMock(
            side_effect=[pid_obs] + [alive_obs, empty_obs] * 100
        )
        session.deployment.runtime.create_session = AsyncMock()
        session.deployment.runtime.close_session = AsyncMock()

        with pytest.raises(TimeoutError):
            async for _ in sandbox_manager.stream_claude(
                session=session,
                prompt="test",
                model="m",
                max_turns=5,
                timeout_minutes=0,
            ):
                pass

    async def test_stop_cleans_extra_sessions(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """Extra sessions should be cleaned up during stop."""
        session._extra_sessions = ["tail", "debug"]
        await sandbox_manager.stop(session)
        assert session._extra_sessions == []
        assert session.deployment.runtime.close_session.await_count == 2

    async def test_stream_claude_empty_pid_raises(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """S-3: Empty PID output should raise RuntimeError, not IndexError."""
        empty_obs = MagicMock()
        empty_obs.output = ""
        empty_obs.exit_code = 0
        empty_obs.failure_reason = ""

        session.deployment.runtime.run_in_session = AsyncMock(return_value=empty_obs)
        session.deployment.runtime.create_session = AsyncMock()
        session.deployment.runtime.close_session = AsyncMock()

        with pytest.raises(RuntimeError, match="Failed to launch Claude Code"):
            async for _ in sandbox_manager.stream_claude(
                session=session,
                prompt="test",
                model="m",
                max_turns=5,
                timeout_minutes=1,
            ):
                pass


class TestStreamClaudePidKill:
    async def test_pid_killed_on_timeout(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """N3: On timeout, the Claude Code PID should be killed in the finally block."""
        alive_obs = MagicMock()
        alive_obs.output = "0"
        alive_obs.exit_code = 0
        alive_obs.failure_reason = ""

        empty_obs = MagicMock()
        empty_obs.output = ""
        empty_obs.exit_code = 0
        empty_obs.failure_reason = ""

        pid_obs = MagicMock()
        pid_obs.output = "42"
        pid_obs.exit_code = 0
        pid_obs.failure_reason = ""

        call_count = 0
        calls_log: list[str] = []

        async def side_effect(action):
            nonlocal call_count
            call_count += 1
            cmd = action.command if hasattr(action, "command") else ""
            calls_log.append(cmd)
            if call_count == 1:
                return pid_obs  # launch claude
            if "kill -0" in cmd:
                return alive_obs  # process alive
            if "kill 42" in cmd:
                return empty_obs  # kill command
            return empty_obs  # tail etc.

        session.deployment.runtime.run_in_session = AsyncMock(side_effect=side_effect)
        session.deployment.runtime.create_session = AsyncMock()
        session.deployment.runtime.close_session = AsyncMock()

        with pytest.raises(TimeoutError):
            async for _ in sandbox_manager.stream_claude(
                session=session,
                prompt="test",
                model="m",
                max_turns=5,
                timeout_minutes=0,
            ):
                pass

        # Verify kill was called in finally block
        kill_calls = [c for c in calls_log if "kill 42" in c and "kill -0" not in c]
        assert len(kill_calls) >= 1


class TestStreamClaudeStderrLogging:
    async def test_stderr_logged_on_crash(
        self,
        sandbox_manager: SandboxManager,
        session: SandboxSession,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """N4: When Claude Code crashes without result, stderr should be logged."""
        pid_obs = MagicMock()
        pid_obs.output = "999"
        pid_obs.exit_code = 0
        pid_obs.failure_reason = ""

        dead_obs = MagicMock()
        dead_obs.output = "1"
        dead_obs.exit_code = 0
        dead_obs.failure_reason = ""

        empty_obs = MagicMock()
        empty_obs.output = ""
        empty_obs.exit_code = 0
        empty_obs.failure_reason = ""

        stderr_obs = MagicMock()
        stderr_obs.output = "Error: API key invalid"
        stderr_obs.exit_code = 0
        stderr_obs.failure_reason = ""

        kill_obs = MagicMock()
        kill_obs.output = ""
        kill_obs.exit_code = 0
        kill_obs.failure_reason = ""

        call_count = 0

        async def side_effect(action):
            nonlocal call_count
            call_count += 1
            cmd = action.command if hasattr(action, "command") else ""
            if call_count == 1:
                return pid_obs  # launch
            if "kill -0" in cmd:
                return dead_obs  # process dead
            if "tail -n" in cmd:
                return empty_obs  # no stream output
            if "cat /tmp/dkmv_stream.err" in cmd:
                return stderr_obs  # stderr content
            if "kill" in cmd:
                return kill_obs  # kill in finally
            return empty_obs

        session.deployment.runtime.run_in_session = AsyncMock(side_effect=side_effect)
        session.deployment.runtime.create_session = AsyncMock()
        session.deployment.runtime.close_session = AsyncMock()

        import logging

        with caplog.at_level(logging.WARNING, logger="dkmv.core.sandbox"):
            events = []
            async for event in sandbox_manager.stream_claude(
                session=session,
                prompt="test",
                model="m",
                max_turns=5,
                timeout_minutes=1,
            ):
                events.append(event)

        assert len(events) == 0  # No result event
        assert "API key invalid" in caplog.text
        assert "stderr" in caplog.text.lower()


class TestStreamClaudePidValidation:
    async def test_non_numeric_pid_raises(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """PID should be validated as numeric to prevent shell injection."""
        bad_pid_obs = MagicMock()
        bad_pid_obs.output = "bash: command not found"
        bad_pid_obs.exit_code = 0
        bad_pid_obs.failure_reason = ""

        session.deployment.runtime.run_in_session = AsyncMock(return_value=bad_pid_obs)
        session.deployment.runtime.create_session = AsyncMock()
        session.deployment.runtime.close_session = AsyncMock()

        with pytest.raises(RuntimeError, match="invalid PID"):
            async for _ in sandbox_manager.stream_claude(
                session=session,
                prompt="test",
                model="m",
                max_turns=5,
                timeout_minutes=1,
            ):
                pass


class TestStreamClaudeBudgetFlag:
    async def test_budget_zero_includes_flag(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """max_budget_usd=0.0 should still include the --max-budget-usd flag."""
        import json

        result_event = json.dumps({"type": "result", "total_cost_usd": 0.0})

        pid_obs = MagicMock()
        pid_obs.output = "123"
        pid_obs.exit_code = 0
        pid_obs.failure_reason = ""

        alive_obs = MagicMock()
        alive_obs.output = "0"
        alive_obs.exit_code = 0
        alive_obs.failure_reason = ""

        dead_obs = MagicMock()
        dead_obs.output = "1"
        dead_obs.exit_code = 0
        dead_obs.failure_reason = ""

        tail_obs = MagicMock()
        tail_obs.output = result_event
        tail_obs.exit_code = 0
        tail_obs.failure_reason = ""

        empty_obs = MagicMock()
        empty_obs.output = ""
        empty_obs.exit_code = 0
        empty_obs.failure_reason = ""

        calls_log: list[str] = []

        async def side_effect(action):
            cmd = action.command if hasattr(action, "command") else ""
            calls_log.append(cmd)
            if not calls_log[:-1]:  # first call
                return pid_obs
            if "kill -0" in cmd:
                if len([c for c in calls_log if "kill -0" in c]) > 1:
                    return dead_obs
                return alive_obs
            if "tail -n" in cmd:
                if len([c for c in calls_log if "tail -n" in c]) > 1:
                    return empty_obs
                return tail_obs
            if "kill" in cmd:
                return empty_obs
            return pid_obs

        session.deployment.runtime.run_in_session = AsyncMock(side_effect=side_effect)
        session.deployment.runtime.create_session = AsyncMock()
        session.deployment.runtime.close_session = AsyncMock()
        session.deployment.runtime.write_file = AsyncMock()

        events = []
        async for event in sandbox_manager.stream_claude(
            session=session,
            prompt="test",
            model="m",
            max_turns=5,
            timeout_minutes=1,
            max_budget_usd=0.0,
        ):
            events.append(event)

        # The first call should contain --max-budget-usd
        launch_cmd = calls_log[0]
        assert "--max-budget-usd" in launch_cmd


class TestStreamClaudeEnvVars:
    async def test_stream_claude_with_env_vars(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """IU-1: env_vars should produce 'env KEY=VALUE ...' prefix in command."""
        import json

        result_event = json.dumps({"type": "result", "total_cost_usd": 0.0})

        pid_obs = MagicMock()
        pid_obs.output = "123"
        pid_obs.exit_code = 0
        pid_obs.failure_reason = ""

        alive_obs = MagicMock()
        alive_obs.output = "0"
        alive_obs.exit_code = 0
        alive_obs.failure_reason = ""

        dead_obs = MagicMock()
        dead_obs.output = "1"
        dead_obs.exit_code = 0
        dead_obs.failure_reason = ""

        tail_obs = MagicMock()
        tail_obs.output = result_event
        tail_obs.exit_code = 0
        tail_obs.failure_reason = ""

        empty_obs = MagicMock()
        empty_obs.output = ""
        empty_obs.exit_code = 0
        empty_obs.failure_reason = ""

        calls_log: list[str] = []

        async def side_effect(action):
            cmd = action.command if hasattr(action, "command") else ""
            calls_log.append(cmd)
            if not [c for c in calls_log[:-1] if c]:
                return pid_obs
            if "kill -0" in cmd:
                if len([c for c in calls_log if "kill -0" in c]) > 1:
                    return dead_obs
                return alive_obs
            if "tail -n" in cmd:
                if len([c for c in calls_log if "tail -n" in c]) > 1:
                    return empty_obs
                return tail_obs
            if "kill" in cmd:
                return empty_obs
            return pid_obs

        session.deployment.runtime.run_in_session = AsyncMock(side_effect=side_effect)
        session.deployment.runtime.create_session = AsyncMock()
        session.deployment.runtime.close_session = AsyncMock()
        session.deployment.runtime.write_file = AsyncMock()

        async for _ in sandbox_manager.stream_claude(
            session=session,
            prompt="test",
            model="m",
            max_turns=5,
            timeout_minutes=1,
            env_vars={"FOO": "bar", "BAZ": "qux"},
        ):
            pass

        launch_cmd = calls_log[0]
        assert "env FOO=" in launch_cmd
        assert "BAZ=" in launch_cmd
        assert launch_cmd.index("env ") < launch_cmd.index("claude -p")

    async def test_stream_claude_without_env_vars_unchanged(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """IU-1: No env_vars should produce no 'env ' prefix."""
        import json

        result_event = json.dumps({"type": "result", "total_cost_usd": 0.0})

        pid_obs = MagicMock()
        pid_obs.output = "123"
        pid_obs.exit_code = 0
        pid_obs.failure_reason = ""

        alive_obs = MagicMock()
        alive_obs.output = "0"
        alive_obs.exit_code = 0
        alive_obs.failure_reason = ""

        dead_obs = MagicMock()
        dead_obs.output = "1"
        dead_obs.exit_code = 0
        dead_obs.failure_reason = ""

        tail_obs = MagicMock()
        tail_obs.output = result_event
        tail_obs.exit_code = 0
        tail_obs.failure_reason = ""

        empty_obs = MagicMock()
        empty_obs.output = ""
        empty_obs.exit_code = 0
        empty_obs.failure_reason = ""

        calls_log: list[str] = []

        async def side_effect(action):
            cmd = action.command if hasattr(action, "command") else ""
            calls_log.append(cmd)
            if not [c for c in calls_log[:-1] if c]:
                return pid_obs
            if "kill -0" in cmd:
                if len([c for c in calls_log if "kill -0" in c]) > 1:
                    return dead_obs
                return alive_obs
            if "tail -n" in cmd:
                if len([c for c in calls_log if "tail -n" in c]) > 1:
                    return empty_obs
                return tail_obs
            if "kill" in cmd:
                return empty_obs
            return pid_obs

        session.deployment.runtime.run_in_session = AsyncMock(side_effect=side_effect)
        session.deployment.runtime.create_session = AsyncMock()
        session.deployment.runtime.close_session = AsyncMock()
        session.deployment.runtime.write_file = AsyncMock()

        async for _ in sandbox_manager.stream_claude(
            session=session,
            prompt="test",
            model="m",
            max_turns=5,
            timeout_minutes=1,
        ):
            pass

        launch_cmd = calls_log[0]
        assert "env " not in launch_cmd


class TestStreamClaudeResume:
    async def test_stream_claude_resume_uses_resume_flag(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """When resume_session_id is set, command includes --resume."""
        import json

        result_event = json.dumps({"type": "result", "total_cost_usd": 0.0})

        pid_obs = MagicMock()
        pid_obs.output = "123"
        pid_obs.exit_code = 0
        pid_obs.failure_reason = ""

        alive_obs = MagicMock()
        alive_obs.output = "0"
        alive_obs.exit_code = 0
        alive_obs.failure_reason = ""

        dead_obs = MagicMock()
        dead_obs.output = "1"
        dead_obs.exit_code = 0
        dead_obs.failure_reason = ""

        tail_obs = MagicMock()
        tail_obs.output = result_event
        tail_obs.exit_code = 0
        tail_obs.failure_reason = ""

        empty_obs = MagicMock()
        empty_obs.output = ""
        empty_obs.exit_code = 0
        empty_obs.failure_reason = ""

        calls_log: list[str] = []

        async def side_effect(action):
            cmd = action.command if hasattr(action, "command") else ""
            calls_log.append(cmd)
            if not [c for c in calls_log[:-1] if c]:
                return pid_obs
            if "kill -0" in cmd:
                if len([c for c in calls_log if "kill -0" in c]) > 1:
                    return dead_obs
                return alive_obs
            if "tail -n" in cmd:
                if len([c for c in calls_log if "tail -n" in c]) > 1:
                    return empty_obs
                return tail_obs
            if "kill" in cmd:
                return empty_obs
            return pid_obs

        session.deployment.runtime.run_in_session = AsyncMock(side_effect=side_effect)
        session.deployment.runtime.create_session = AsyncMock()
        session.deployment.runtime.close_session = AsyncMock()
        session.deployment.runtime.write_file = AsyncMock()

        async for _ in sandbox_manager.stream_claude(
            session=session,
            prompt="Fix the output",
            model="m",
            max_turns=5,
            timeout_minutes=1,
            resume_session_id="sess-abc-123",
        ):
            pass

        launch_cmd = calls_log[0]
        assert "--resume" in launch_cmd
        assert "sess-abc-123" in launch_cmd

    async def test_stream_claude_without_resume_uses_p_flag(
        self, sandbox_manager: SandboxManager, session: SandboxSession
    ) -> None:
        """Default behavior without resume_session_id uses -p flag."""
        import json

        result_event = json.dumps({"type": "result", "total_cost_usd": 0.0})

        pid_obs = MagicMock()
        pid_obs.output = "123"
        pid_obs.exit_code = 0
        pid_obs.failure_reason = ""

        alive_obs = MagicMock()
        alive_obs.output = "0"
        alive_obs.exit_code = 0
        alive_obs.failure_reason = ""

        dead_obs = MagicMock()
        dead_obs.output = "1"
        dead_obs.exit_code = 0
        dead_obs.failure_reason = ""

        tail_obs = MagicMock()
        tail_obs.output = result_event
        tail_obs.exit_code = 0
        tail_obs.failure_reason = ""

        empty_obs = MagicMock()
        empty_obs.output = ""
        empty_obs.exit_code = 0
        empty_obs.failure_reason = ""

        calls_log: list[str] = []

        async def side_effect(action):
            cmd = action.command if hasattr(action, "command") else ""
            calls_log.append(cmd)
            if not [c for c in calls_log[:-1] if c]:
                return pid_obs
            if "kill -0" in cmd:
                if len([c for c in calls_log if "kill -0" in c]) > 1:
                    return dead_obs
                return alive_obs
            if "tail -n" in cmd:
                if len([c for c in calls_log if "tail -n" in c]) > 1:
                    return empty_obs
                return tail_obs
            if "kill" in cmd:
                return empty_obs
            return pid_obs

        session.deployment.runtime.run_in_session = AsyncMock(side_effect=side_effect)
        session.deployment.runtime.create_session = AsyncMock()
        session.deployment.runtime.close_session = AsyncMock()
        session.deployment.runtime.write_file = AsyncMock()

        async for _ in sandbox_manager.stream_claude(
            session=session,
            prompt="test",
            model="m",
            max_turns=5,
            timeout_minutes=1,
        ):
            pass

        launch_cmd = calls_log[0]
        assert "--resume" not in launch_cmd
        assert "claude -p" in launch_cmd


class TestMemorySwapDockerArg:
    @patch("dkmv.core.sandbox.DockerDeployment")
    async def test_memory_swap_included(
        self, mock_dd_cls: MagicMock, sandbox_manager: SandboxManager
    ) -> None:
        """--memory-swap should be set equal to --memory per PRD."""
        mock_dep = MagicMock()
        mock_dep.start = AsyncMock()
        mock_dep.runtime = AsyncMock()
        mock_dep.runtime.create_session = AsyncMock()
        type(mock_dep).container_name = PropertyMock(return_value="c")
        mock_dd_cls.return_value = mock_dep

        config = SandboxConfig(memory_limit="16g")
        await sandbox_manager.start(config, "dev")

        docker_args = mock_dd_cls.call_args.kwargs["docker_args"]
        assert "--memory=16g" in docker_args
        assert "--memory-swap=16g" in docker_args


class TestStartContainerLeak:
    @patch("dkmv.core.sandbox.DockerDeployment")
    async def test_start_cleans_up_on_session_failure(
        self, mock_dd_cls: MagicMock, sandbox_manager: SandboxManager
    ) -> None:
        """S-1: If create_session fails, the container should be stopped."""
        mock_dep = MagicMock()
        mock_dep.start = AsyncMock()
        mock_dep.stop = AsyncMock()
        mock_dep.runtime = AsyncMock()
        mock_dep.runtime.create_session = AsyncMock(
            side_effect=RuntimeError("Session creation failed")
        )
        type(mock_dep).container_name = PropertyMock(return_value="c")
        mock_dd_cls.return_value = mock_dep

        config = SandboxConfig(image="test:latest")
        with pytest.raises(RuntimeError, match="Session creation failed"):
            await sandbox_manager.start(config, "dev")

        # Container should have been stopped to prevent leak
        mock_dep.stop.assert_awaited_once()
