"""Unit tests for the executor seam (slice 0.4 — PRD §8.7, INV-3).

Covers:

* The :class:`Executor` interface shape (``start``/``stream``/``signal``/
  ``cleanup``; ``stream`` re-attachable by ``run_id``) and ``RunSpec``.
* The gVisor isolation policy: ``runsc`` is the default; the OQ-6
  weaker-isolation paths log/raise the documented warning.
* :class:`LocalDockerExecutor` over a fake ``RunService``/engine runtime — no
  real Docker, no real ``EmbeddedRuntime`` (INV-13: consumed in-process only).
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import app.executor.runtime_policy as _rp_module
import pytest
from app.executor import (
    GVISOR_RUNTIME,
    RUNSC_UNAVAILABLE_WARNING,
    WEAKER_ISOLATION_WARNING,
    Executor,
    LocalDockerExecutor,
    RunSpec,
    Signal,
    StreamedEvent,
    WeakerIsolationError,
    resolve_runtime,
    runtime_docker_args,
)
from app.runtime import RunService

from tests.conftest import make_settings

# The genuine ``runtime_available`` impl, captured before the conftest autouse
# ``_gvisor_available_by_default`` shadows it → True for the rest of the suite.
# The probe tests below exercise the REAL function (its shutil/subprocess paths),
# so they restore this genuine impl over the autouse lambda.
_GENUINE_RUNTIME_AVAILABLE = _rp_module.runtime_available

# ── Order-independent log capture ────────────────────────────────────────────
#
# pytest's ``caplog`` relies on the root logger's handler + propagation, which
# other test modules / imported deps (uvicorn, swerex) can leave in a state that
# suppresses capture depending on collection order — and a stray
# ``logging.disable()`` elsewhere in the suite can mute records below CRITICAL
# regardless of handler placement. To make the weaker-isolation-warning
# assertions (AC-0.4-3) deterministic, we attach our OWN handler **directly** to
# every logger in the ``app.executor`` package (so we never depend on
# propagation), force each to WARNING, and clear any process-wide
# ``logging.disable`` for the duration of the capture (restoring it after).

#: The loggers that actually emit the isolation warnings (one per module).
_EXECUTOR_LOGGERS = (
    "app.executor",
    "app.executor.runtime_policy",
    "app.executor.local_docker",
)


class _RecordCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextmanager
def capture_executor_logs() -> Iterator[_RecordCollector]:
    """Capture WARNING+ from the ``app.executor`` loggers, order-independently.

    Attaches a collecting handler to each ``app.executor`` logger directly (no
    reliance on propagation), forces each to WARNING, and temporarily clears any
    process-wide ``logging.disable`` so a stray disable from another test module
    cannot mute the captured records.
    """
    collector = _RecordCollector()
    loggers = [logging.getLogger(name) for name in _EXECUTOR_LOGGERS]
    prev_levels = [lg.level for lg in loggers]
    # A ``logging.config.dictConfig`` call elsewhere in the suite (uvicorn /
    # TestClient deps) defaults to ``disable_existing_loggers=True`` — which sets
    # ``logger.disabled = True`` on every pre-existing logger, silencing it
    # regardless of level or handlers. Re-enable for the capture, then restore.
    prev_disabled = [lg.disabled for lg in loggers]
    prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    for lg in loggers:
        lg.disabled = False
        lg.setLevel(logging.WARNING)
        lg.addHandler(collector)
    try:
        yield collector
    finally:
        for lg, prev_level, prev_dis in zip(loggers, prev_levels, prev_disabled, strict=True):
            lg.removeHandler(collector)
            lg.setLevel(prev_level)
            lg.disabled = prev_dis
        logging.disable(prev_disable)


# ── Fakes (duck-typed engine stand-ins; no Docker, no real EmbeddedRuntime) ──


class FakeRunHandle:
    """Minimal RunHandle stand-in: run_id + a recording ``stop``."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.stop_calls: list[bool] = []

    async def stop(self, *, force: bool = False) -> None:
        self.stop_calls.append(force)


class FakeEngineRuntime:
    """Duck-typed EmbeddedRuntime: records start args, serves replay/handle/cleanup."""

    def __init__(self, events: list[Any] | None = None) -> None:
        self._events = events or []
        self._handles: dict[str, FakeRunHandle] = {}
        self.start_kwargs: dict[str, Any] | None = None
        self.cleanup_calls = 0
        self.replay_calls: list[tuple[str, int]] = []

    async def start(self, **kwargs: Any) -> FakeRunHandle:
        self.start_kwargs = kwargs
        handle = FakeRunHandle("run-123")
        self._handles[handle.run_id] = handle
        return handle

    def replay_events(self, run_id: str, offset: int = 0) -> list[Any]:
        self.replay_calls.append((run_id, offset))
        return self._events[offset:]

    def get_handle(self, run_id: str) -> FakeRunHandle | None:
        return self._handles.get(run_id)

    def cleanup(self) -> None:
        self.cleanup_calls += 1


def make_executor(
    *,
    runtime: str = "runsc",
    events: list[Any] | None = None,
    allow_weaker_isolation: bool = False,
) -> tuple[LocalDockerExecutor, FakeEngineRuntime]:
    """Build a LocalDockerExecutor over a fake engine runtime (no Docker probe)."""
    settings = make_settings(SANDBOX_RUNTIME=runtime)
    fake_runtime = FakeEngineRuntime(events=events)
    run_service = RunService(settings, runtime=fake_runtime)  # type: ignore[arg-type]  # DKMVP-ESCAPE: duck-typed engine stub
    executor = LocalDockerExecutor(
        run_service,
        settings,
        allow_weaker_isolation=allow_weaker_isolation,
        check_runtime_available=False,  # skip the docker daemon probe in unit tests
    )
    return executor, fake_runtime


# ── Interface shape (AC-0.4-1) ───────────────────────────────────────────────


def test_executor_interface_has_seam_methods() -> None:
    for name in ("start", "stream", "signal", "cleanup"):
        assert hasattr(Executor, name), f"Executor missing seam method {name}"


def test_local_docker_executor_is_an_executor() -> None:
    assert issubclass(LocalDockerExecutor, Executor)


def test_stream_signature_accepts_run_id_for_reattach() -> None:
    # The seam contract: stream() is re-attachable by run_id (ADR-P008). The
    # param accepts a handle OR a bare run_id string.
    sig = inspect.signature(Executor.stream)
    assert "handle_or_run_id" in sig.parameters
    assert "offset" in sig.parameters


def test_runspec_is_serializable_dataclass() -> None:
    spec = RunSpec(component="dev", repo="owner/repo", branch="main")
    assert spec.component == "dev"
    assert spec.repo == "owner/repo"
    assert spec.branch == "main"
    # frozen → immutable launch request
    with pytest.raises(Exception):  # noqa: B017,PT011 - FrozenInstanceError family
        spec.repo = "other/repo"  # type: ignore[misc]  # DKMVP-ESCAPE: asserting immutability


# ── Runtime isolation policy (AC-0.4-2, AC-0.4-3 / INV-3, OQ-6) ───────────────


def test_default_runtime_is_runsc() -> None:
    # gVisor is the secure default; available path returns runsc silently.
    assert resolve_runtime("runsc", check_available=False) == GVISOR_RUNTIME


def test_runtime_docker_args_emit_runtime_flag() -> None:
    assert runtime_docker_args("runsc") == ["--runtime=runsc"]


def test_runtime_available_runc_is_always_true(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.executor.runtime_policy as rp

    monkeypatch.setattr(rp, "runtime_available", _GENUINE_RUNTIME_AVAILABLE)
    # runc is Docker's built-in default; treated as always available.
    assert rp.runtime_available("runc") is True


def test_runtime_available_false_when_docker_cli_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.executor.runtime_policy as rp

    monkeypatch.setattr(rp, "runtime_available", _GENUINE_RUNTIME_AVAILABLE)
    monkeypatch.setattr(rp.shutil, "which", lambda _name: None)
    assert rp.runtime_available("runsc") is False


def test_runtime_available_parses_docker_info_runtimes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    import app.executor.runtime_policy as rp

    monkeypatch.setattr(rp, "runtime_available", _GENUINE_RUNTIME_AVAILABLE)
    monkeypatch.setattr(rp.shutil, "which", lambda _name: "/usr/bin/docker")

    class _Proc:
        returncode = 0
        stdout = "io.containerd.runc.v2 runc runsc "

    monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: _Proc())
    assert rp.runtime_available("runsc") is True
    assert rp.runtime_available("kata") is False

    # A failed probe → not available (fail-closed at the caller).
    class _Fail:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(rp.subprocess, "run", lambda *a, **k: _Fail())
    assert rp.runtime_available("runsc") is False

    # A daemon error/timeout → not available.
    def _raise(*_a: Any, **_k: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="docker", timeout=5.0)

    monkeypatch.setattr(rp.subprocess, "run", _raise)
    assert rp.runtime_available("runsc") is False


def test_explicit_non_runsc_runtime_warns_weaker_isolation() -> None:
    # AC-0.4-3: a non-runsc runtime logs the documented weaker-isolation warning.
    with capture_executor_logs() as logs:
        resolved = resolve_runtime("runc", check_available=False)
    assert resolved == "runc"
    assert any(WEAKER_ISOLATION_WARNING in m for m in logs.messages)


def test_runsc_unavailable_fails_closed_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # OQ-6: runsc selected but unavailable → log the warning AND raise (no silent
    # downgrade to runc) unless the operator explicitly opted into the fallback.
    import app.executor.runtime_policy as rp

    monkeypatch.setattr(rp, "runtime_available", lambda _r, **_kw: False)
    with capture_executor_logs() as logs, pytest.raises(WeakerIsolationError):
        rp.resolve_runtime("runsc", check_available=True)
    assert any(RUNSC_UNAVAILABLE_WARNING in m for m in logs.messages)


def test_runsc_unavailable_with_optin_falls_back_to_runc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.executor.runtime_policy as rp

    monkeypatch.setattr(rp, "runtime_available", lambda _r, **_kw: False)
    with capture_executor_logs() as logs:
        resolved = rp.resolve_runtime("runsc", allow_weaker_isolation=True, check_available=True)
    assert resolved == "runc"
    assert any(RUNSC_UNAVAILABLE_WARNING in m for m in logs.messages)
    assert any(WEAKER_ISOLATION_WARNING in m for m in logs.messages)


# ── isolation_status — the non-raising gate the preflight + launch consume (G1) ──


def test_isolation_status_runsc_available_ok() -> None:
    from app.executor.runtime_policy import isolation_status

    ok, detail = isolation_status("runsc", runtime_available_fn=lambda _r: True)
    assert ok is True
    assert "gVisor" in detail


def test_isolation_status_runsc_unavailable_blocks() -> None:
    from app.executor.runtime_policy import isolation_status

    ok, detail = isolation_status(
        "runsc", allow_weaker_isolation=False, runtime_available_fn=lambda _r: False
    )
    assert ok is False
    assert "blocked" in detail.lower()


def test_isolation_status_runsc_unavailable_optin_proceeds() -> None:
    from app.executor.runtime_policy import isolation_status

    ok, detail = isolation_status(
        "runsc", allow_weaker_isolation=True, runtime_available_fn=lambda _r: False
    )
    assert ok is True
    assert "weaker isolation" in detail.lower()


def test_isolation_status_non_runsc_is_optin_ok() -> None:
    from app.executor.runtime_policy import isolation_status

    # Choosing a non-runsc runtime is itself the documented opt-in → ok, with warn.
    ok, detail = isolation_status("runc", runtime_available_fn=lambda _r: False)
    assert ok is True
    assert "weaker-isolation opt-in" in detail


# ── LocalDockerExecutor behavior ─────────────────────────────────────────────


def test_executor_resolves_runsc_runtime_and_flag() -> None:
    executor, _ = make_executor(runtime="runsc")
    assert executor.runtime == "runsc"
    assert executor.runtime_docker_args == ["--runtime=runsc"]


def test_executor_construction_warns_on_non_runsc() -> None:
    # AC-0.4-3: constructing with a weaker runtime logs the documented warning.
    with capture_executor_logs() as logs:
        executor, _ = make_executor(runtime="runc")
    assert executor.runtime == "runc"
    assert any(WEAKER_ISOLATION_WARNING in m for m in logs.messages)


@pytest.mark.asyncio
async def test_start_delegates_to_run_service() -> None:
    executor, fake_runtime = make_executor()
    spec = RunSpec(component="dev", repo="owner/repo", branch="feat", feature_name="x")
    handle = await executor.start(spec)
    assert handle.run_id == "run-123"
    assert fake_runtime.start_kwargs is not None
    assert fake_runtime.start_kwargs["component"] == "dev"
    # RunService translates repo/branch into an engine ExecutionSource.
    source = fake_runtime.start_kwargs["source"]
    assert source.repo == "owner/repo"
    assert source.branch == "feat"
    assert fake_runtime.start_kwargs["feature_name"] == "x"


@pytest.mark.asyncio
async def test_stream_reattaches_by_run_id_via_replay() -> None:
    # ADR-P008: stream() re-attachable by run_id → engine durable replay.
    events = ["e0", "e1", "e2"]
    executor, fake_runtime = make_executor(events=events)
    out: list[StreamedEvent] = []
    async for ev in executor.stream("run-xyz"):
        out.append(ev)
    assert [e.event for e in out] == events
    assert all(e.run_id == "run-xyz" for e in out)
    # monotonic, 1-based sequence cursor
    assert [e.sequence for e in out] == [1, 2, 3]
    assert fake_runtime.replay_calls == [("run-xyz", 0)]


@pytest.mark.asyncio
async def test_stream_offset_is_a_replay_cursor() -> None:
    events = ["e0", "e1", "e2", "e3"]
    executor, fake_runtime = make_executor(events=events)
    out: list[StreamedEvent] = [ev async for ev in executor.stream("run-xyz", offset=2)]
    assert [e.event for e in out] == ["e2", "e3"]
    assert [e.sequence for e in out] == [3, 4]
    assert fake_runtime.replay_calls == [("run-xyz", 2)]


@pytest.mark.asyncio
async def test_signal_cancel_forces_stop() -> None:
    executor, fake_runtime = make_executor()
    handle = await executor.start(RunSpec(component="dev", repo="o/r"))
    await executor.signal(handle, Signal.CANCEL)
    assert handle.stop_calls == [True]  # force=True (Stop-safe path)


@pytest.mark.asyncio
async def test_signal_cancel_by_run_id_resolves_live_handle() -> None:
    executor, fake_runtime = make_executor()
    handle = await executor.start(RunSpec(component="dev", repo="o/r"))
    await executor.signal(handle.run_id, Signal.CANCEL)
    assert handle.stop_calls == [True]


@pytest.mark.asyncio
async def test_signal_unknown_run_id_is_noop() -> None:
    # INV-10: no live handle (dead-process run) → do NOT re-attach; warn + no-op.
    executor, _ = make_executor()
    with capture_executor_logs() as logs:
        await executor.signal("ghost-run", Signal.CANCEL)
    assert any("no live handle" in m for m in logs.messages)


@pytest.mark.asyncio
async def test_signal_pause_resume_are_phase2_noop() -> None:
    executor, _ = make_executor()
    handle = await executor.start(RunSpec(component="dev", repo="o/r"))
    # No exception; PAUSE/RESUME are the Phase-2 HITL seam, not synthesized here.
    await executor.signal(handle, Signal.PAUSE)
    await executor.signal(handle, Signal.RESUME)
    assert handle.stop_calls == []


@pytest.mark.asyncio
async def test_cleanup_delegates_to_engine() -> None:
    executor, fake_runtime = make_executor()
    handle = await executor.start(RunSpec(component="dev", repo="o/r"))
    await executor.cleanup(handle)
    assert fake_runtime.cleanup_calls == 1


def test_executor_owns_docker_no_direct_docker_in_orchestrator() -> None:
    # AC-0.4-1 structural guard: the only place that imports docker policy is the
    # executor package. Assert the public surface lives there.
    import app.executor as ex

    assert "LocalDockerExecutor" in ex.__all__
    assert "Executor" in ex.__all__
