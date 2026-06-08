"""Sandbox-runtime isolation policy (gVisor ``runsc`` default; OQ-6 fallback).

This module is the *single* place the platform decides which container runtime a
sandbox launches under and turns that decision into the Docker run flag
(``--runtime=<name>``). It enforces INV-3 / NFR-SEC-4 / ADR-P005:

* **gVisor (``runsc``) is the default** (``settings.SANDBOX_RUNTIME``). Plain
  ``runc`` shares the host kernel and "is not a security boundary" for
  autonomous untrusted-code execution.
* Selecting **any non-``runsc`` runtime is a documented weaker-isolation opt-in**
  and emits an explicit warning (OQ-6); the same warning fires when ``runsc`` is
  configured but **unavailable** on the host.
* By default a misconfiguration (``runsc`` selected but missing) is treated as a
  hard error (fail-closed) — the secure posture — unless the operator has
  explicitly opted into the weaker fallback.

The runtime flag is produced here and consumed by the executor when it assembles
the container start args (see ``LocalDockerExecutor``). Threading the flag the
rest of the way into the engine's ``SandboxManager.docker_args`` is an engine
ask (PRD §8.7 / §11.3: the engine's ``SandboxManager`` hardcodes
``DockerDeployment`` and exposes no public ``docker_args`` passthrough on
``EmbeddedRuntime.start``); the platform owns the policy + the flag at this seam.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

#: The required-by-default, network-isolated sandbox runtime (gVisor).
GVISOR_RUNTIME = "runsc"

#: The exact warning string the platform logs/raises on the weaker-isolation
#: path. Greppable for AC-0.4-3 ("weaker isolation" / "isolation warning" /
#: "runsc ... unavailable").
WEAKER_ISOLATION_WARNING = (
    "SANDBOX ISOLATION WARNING: running sandboxes under a non-runsc runtime is a "
    "weaker-isolation opt-in. gVisor (runsc) is the required default (NFR-SEC-4, "
    "INV-3); plain runc shares the host kernel and is NOT a security boundary for "
    "autonomous untrusted-code execution. Proceed only on a trusted single-user host."
)

#: The warning when runsc is selected but the host runtime is unavailable (OQ-6).
RUNSC_UNAVAILABLE_WARNING = (
    "SANDBOX ISOLATION WARNING: SANDBOX_RUNTIME=runsc but the runsc (gVisor) runtime "
    "is unavailable on this Docker host. This is the OQ-6 fallback: continuing would "
    "run sandboxes under weaker isolation. Install/enable gVisor, or explicitly opt "
    "into the weaker-isolation fallback (allow_weaker_isolation=True)."
)


class WeakerIsolationError(RuntimeError):
    """Raised when runsc is required but unavailable and no opt-in was given.

    Fail-closed default: a missing gVisor runtime must not silently downgrade the
    sandbox to ``runc`` (the most dangerous-quiet failure mode for this product
    class). The operator must explicitly opt into the weaker fallback.
    """


def runtime_available(runtime: str, *, timeout: float = 5.0) -> bool:
    """Return whether ``runtime`` is registered with the local Docker daemon.

    Probes ``docker info`` and looks for the runtime in the daemon's registered
    runtimes. Best-effort: if the ``docker`` CLI is absent or the probe errors,
    returns ``False`` (caller decides whether that is fatal). ``runc`` is always
    treated as available (it is Docker's built-in default).
    """
    if runtime == "runc":
        return True
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(  # noqa: S603,S607 - fixed argv, no shell, host docker probe
            ["docker", "info", "--format", "{{range $r, $_ := .Runtimes}}{{$r}} {{end}}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if proc.returncode != 0:
        return False
    registered = proc.stdout.split()
    return runtime in registered


def resolve_runtime(
    configured: str,
    *,
    allow_weaker_isolation: bool = False,
    check_available: bool = True,
) -> str:
    """Resolve the effective sandbox runtime, enforcing the isolation policy.

    Args:
        configured: ``settings.SANDBOX_RUNTIME`` (default ``runsc``).
        allow_weaker_isolation: Operator opt-in to a non-``runsc`` runtime or to
            continuing when ``runsc`` is unavailable (OQ-6). When ``False``
            (default), a missing-``runsc`` misconfiguration is fail-closed
            (raises :class:`WeakerIsolationError`).
        check_available: When ``True``, probe the Docker daemon for the runtime
            (skippable in unit tests / when the daemon is unreachable).

    Returns:
        The runtime name to pass to the container as ``--runtime=<name>``.

    Behavior:

    * ``configured == "runsc"`` and available → returns ``"runsc"`` silently
      (the secure default path).
    * ``configured == "runsc"`` but **unavailable** → logs
      :data:`RUNSC_UNAVAILABLE_WARNING`; raises :class:`WeakerIsolationError`
      unless ``allow_weaker_isolation`` is set, in which case it warns and
      returns ``"runc"`` (the documented OQ-6 weaker fallback).
    * ``configured != "runsc"`` (an explicit weaker runtime) → logs
      :data:`WEAKER_ISOLATION_WARNING` and returns ``configured`` (the opt-in is
      implicit in choosing a non-``runsc`` runtime; this is the documented
      weaker-isolation opt-in).
    """
    runtime = (configured or GVISOR_RUNTIME).strip()

    if runtime == GVISOR_RUNTIME:
        if check_available and not runtime_available(runtime):
            logger.warning(RUNSC_UNAVAILABLE_WARNING)
            if not allow_weaker_isolation:
                raise WeakerIsolationError(RUNSC_UNAVAILABLE_WARNING)
            logger.warning(WEAKER_ISOLATION_WARNING)
            return "runc"
        return runtime

    # An explicit non-runsc runtime is itself the documented weaker-isolation
    # opt-in: warn loudly but honor the operator's choice.
    logger.warning(WEAKER_ISOLATION_WARNING)
    return runtime


def runtime_docker_args(runtime: str) -> list[str]:
    """Return the Docker run args that pin the container to ``runtime``.

    The ``--runtime=<name>`` flag is what selects gVisor (``runsc``) at container
    start (INV-3). Returned as a list so it can be concatenated into the sandbox
    ``docker_args`` the executor controls.
    """
    return [f"--runtime={runtime}"]
