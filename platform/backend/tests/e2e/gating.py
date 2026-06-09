"""Docker / gVisor availability gates for the live-only §13 ATs (slice 5.4).

The brief's environment note (be HONEST, do not fake): the ATs that need a LIVE
gVisor container + real network egress cannot run for real in a sandbox without
Docker + runsc. So those assertions are split:

* the **in-process** half (config present + Python-level enforcement denies a
  non-allowlisted host / a foreign-repo push / a secret in a log) runs ALWAYS;
* the **live-container** half is gated behind these ``skipif`` marks, which
  self-skip with a clear reason when the prerequisite is absent — reported as
  SKIPPED, never faked, never silently passed.

``DKMV_E2E_LIVE=1`` is an additional explicit opt-in so the live assertions only
run where the operator has both the daemon AND has asked for them (a Docker daemon
being present does not by itself mean a runsc-capable, network-isolated sandbox is
wired — that is the full §8.8 setup).
"""

from __future__ import annotations

import os
import shutil

import pytest
from app.executor.runtime_policy import GVISOR_RUNTIME, runtime_available


def _docker_available() -> bool:
    """True iff a ``docker`` CLI + a reachable daemon are present (best-effort)."""
    if shutil.which("docker") is None:
        return False
    # ``runtime_available("runc")`` short-circuits to True without probing; probe a
    # real runtime name so a missing/unreachable daemon reports False.
    return runtime_available(GVISOR_RUNTIME) or _runc_reachable()


def _runc_reachable() -> bool:
    """A daemon-reachability probe that doesn't require runsc specifically."""
    import subprocess

    try:
        proc = subprocess.run(  # noqa: S603,S607 - fixed argv, no shell, daemon reachability probe
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _live_opt_in() -> bool:
    return os.environ.get("DKMV_E2E_LIVE", "").strip() in {"1", "true", "TRUE", "yes"}


#: True when a live sandboxed-run AT can actually run (daemon + opt-in).
LIVE_SANDBOX_AVAILABLE: bool = _live_opt_in() and _docker_available()

#: True when the gVisor (runsc) runtime is registered with the local daemon.
RUNSC_AVAILABLE: bool = runtime_available(GVISOR_RUNTIME)

#: ``skipif`` for ATs that require a live container started under the real sandbox.
requires_live_sandbox = pytest.mark.skipif(
    not LIVE_SANDBOX_AVAILABLE,
    reason=(
        "live sandbox AT: requires a reachable Docker daemon + DKMV_E2E_LIVE=1 "
        "(the full §8.8 setup). Self-skipped — NOT faked. The in-process enforcement "
        "half of this AT still runs."
    ),
)

#: ``skipif`` for the live gVisor-runtime assertion (runsc registered on the host).
requires_runsc = pytest.mark.skipif(
    not (LIVE_SANDBOX_AVAILABLE and RUNSC_AVAILABLE),
    reason=(
        "live gVisor AT: requires the runsc runtime registered with the Docker "
        "daemon + DKMV_E2E_LIVE=1. Self-skipped — NOT faked. The config + policy "
        "assertions (SANDBOX_RUNTIME=runsc resolves, --runtime=runsc emitted) still run."
    ),
)
