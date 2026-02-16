from __future__ import annotations

import asyncio
import json
import logging
import shlex
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from swerex.deployment.docker import DockerDeployment
from swerex.runtime.abstract import (
    BashAction,
    BashObservation,
    CloseBashSessionRequest,
    CreateBashSessionRequest,
    ReadFileRequest,
    WriteFileRequest,
)

from dkmv.core.models import SandboxConfig

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    output: str
    exit_code: int | None
    failure_reason: str = ""


@dataclass
class SandboxSession:
    deployment: DockerDeployment
    session_name: str = "main"
    container_name: str = ""
    _extra_sessions: list[str] = field(default_factory=list)


class SandboxManager:
    async def start(
        self,
        sandbox_config: SandboxConfig,
        component_name: str,
    ) -> SandboxSession:
        docker_args = [
            f"--memory={sandbox_config.memory_limit}",
            f"--memory-swap={sandbox_config.memory_limit}",
            *[f"-e={k}={v}" for k, v in sandbox_config.env_vars.items()],
            *sandbox_config.docker_args,
        ]

        deployment = DockerDeployment(
            image=sandbox_config.image,
            docker_args=docker_args,
            startup_timeout=sandbox_config.startup_timeout,
            remove_container=not sandbox_config.keep_alive,
            pull="missing",
        )

        await deployment.start()

        try:
            runtime = deployment.runtime
            await runtime.create_session(CreateBashSessionRequest(session="main"))
        except Exception:
            # Clean up the started container to avoid leaks
            try:
                await deployment.stop()
            except Exception:
                logger.warning(
                    "Failed to stop container after session creation failure", exc_info=True
                )
            raise

        container_name = deployment.container_name or ""
        logger.info("Started container %s for %s", container_name, component_name)

        return SandboxSession(
            deployment=deployment,
            session_name="main",
            container_name=container_name,
        )

    async def execute(
        self,
        session: SandboxSession,
        command: str,
        timeout: float | None = None,
    ) -> CommandResult:
        obs: BashObservation = await session.deployment.runtime.run_in_session(
            BashAction(
                command=command,
                session=session.session_name,
                timeout=timeout,
                check="silent",
            )
        )
        return CommandResult(
            output=obs.output,
            exit_code=obs.exit_code,
            failure_reason=obs.failure_reason,
        )

    async def write_file(
        self,
        session: SandboxSession,
        path: str,
        content: str,
    ) -> None:
        await session.deployment.runtime.write_file(WriteFileRequest(path=path, content=content))

    async def read_file(self, session: SandboxSession, path: str) -> str:
        resp = await session.deployment.runtime.read_file(ReadFileRequest(path=path))
        return resp.content

    async def stop(self, session: SandboxSession, keep_alive: bool = False) -> None:
        try:
            # Clean up extra sessions first
            for extra_session in session._extra_sessions:
                try:
                    await session.deployment.runtime.close_session(
                        CloseBashSessionRequest(session=extra_session)
                    )
                except Exception:
                    pass
            session._extra_sessions.clear()

            if keep_alive:
                await session.deployment.runtime.close()
            else:
                await session.deployment.stop()
        except Exception:
            logger.warning("Error during sandbox stop (idempotent)", exc_info=True)

    def get_container_name(self, session: SandboxSession) -> str:
        return session.container_name

    async def _create_session(self, session: SandboxSession, name: str) -> None:
        await session.deployment.runtime.create_session(CreateBashSessionRequest(session=name))
        session._extra_sessions.append(name)

    async def _run_in_session(
        self,
        session: SandboxSession,
        session_name: str,
        command: str,
        timeout: float | None = None,
    ) -> CommandResult:
        obs: BashObservation = await session.deployment.runtime.run_in_session(
            BashAction(
                command=command,
                session=session_name,
                timeout=timeout,
                check="silent",
            )
        )
        return CommandResult(
            output=obs.output,
            exit_code=obs.exit_code,
            failure_reason=obs.failure_reason,
        )

    async def setup_git_auth(self, session: SandboxSession) -> CommandResult:
        return await self.execute(
            session,
            'echo "$GITHUB_TOKEN" | gh auth login --with-token && gh auth setup-git',
        )

    async def stream_claude(
        self,
        session: SandboxSession,
        prompt: str,
        model: str,
        max_turns: int,
        timeout_minutes: int,
        max_budget_usd: float | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        await self.write_file(session, "/tmp/dkmv_prompt.md", prompt)

        budget_flag = (
            f" --max-budget-usd {shlex.quote(str(max_budget_usd))}"
            if max_budget_usd is not None
            else ""
        )
        cmd = (
            'claude -p "$(cat /tmp/dkmv_prompt.md)" '
            "--dangerously-skip-permissions "
            "--output-format stream-json "
            f"--model {shlex.quote(model)} "
            f"--max-turns {shlex.quote(str(max_turns))}"
            f"{budget_flag}"
            " > /tmp/dkmv_stream.jsonl 2>/tmp/dkmv_stream.err & echo $!"
        )

        result = await self.execute(session, cmd)
        lines = result.output.strip().splitlines()
        if not lines:
            msg = "Failed to launch Claude Code: no PID returned"
            raise RuntimeError(msg)
        pid = lines[-1].strip()
        if not pid.isdigit():
            msg = f"Failed to launch Claude Code: invalid PID {pid!r}"
            raise RuntimeError(msg)

        await self._create_session(session, "tail")

        lines_read = 0
        result_seen = False
        result_seen_at: float | None = None

        try:
            async with asyncio.timeout(timeout_minutes * 60):
                while True:
                    alive_result = await self._run_in_session(
                        session, session.session_name, f"kill -0 {pid} 2>/dev/null; echo $?"
                    )
                    is_alive = alive_result.output.strip().endswith("0")

                    tail_result = await self._run_in_session(
                        session,
                        "tail",
                        f"tail -n +{lines_read + 1} /tmp/dkmv_stream.jsonl 2>/dev/null",
                    )

                    if tail_result.output.strip():
                        for line in tail_result.output.strip().splitlines():
                            lines_read += 1
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                event = json.loads(line)
                                yield event
                                if event.get("type") == "result":
                                    result_seen = True
                                    result_seen_at = asyncio.get_running_loop().time()
                            except json.JSONDecodeError:
                                logger.warning("Non-JSON line in stream: %s", line[:200])

                    if result_seen and is_alive:
                        if (
                            result_seen_at is not None
                            and asyncio.get_running_loop().time() - result_seen_at > 10
                        ):
                            await self._run_in_session(
                                session, session.session_name, f"kill {pid} 2>/dev/null"
                            )
                            break

                    if not is_alive and not result_seen:
                        # Process ended; read any remaining lines
                        tail_result = await self._run_in_session(
                            session,
                            "tail",
                            f"tail -n +{lines_read + 1} /tmp/dkmv_stream.jsonl 2>/dev/null",
                        )
                        if tail_result.output.strip():
                            for line in tail_result.output.strip().splitlines():
                                lines_read += 1
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    event = json.loads(line)
                                    yield event
                                    if event.get("type") == "result":
                                        result_seen = True
                                except json.JSONDecodeError:
                                    logger.warning("Non-JSON line in stream: %s", line[:200])

                        # Log stderr if process crashed without a result event
                        if not result_seen:
                            stderr_result = await self._run_in_session(
                                session,
                                "tail",
                                "cat /tmp/dkmv_stream.err 2>/dev/null",
                            )
                            stderr = stderr_result.output.strip()
                            if stderr:
                                logger.warning(
                                    "Claude Code exited without result. stderr:\n%s",
                                    stderr[:2000],
                                )
                        break

                    if not is_alive and result_seen:
                        break

                    await asyncio.sleep(0.5)
        finally:
            # Kill Claude Code process to stop API credit spend (runs even on TimeoutError)
            try:
                await self._run_in_session(session, session.session_name, f"kill {pid} 2>/dev/null")
            except Exception:
                pass
            # Clean up tail session
            try:
                await session.deployment.runtime.close_session(
                    CloseBashSessionRequest(session="tail")
                )
                if "tail" in session._extra_sessions:
                    session._extra_sessions.remove("tail")
            except Exception:
                pass
