# ADR-P008: `Executor` interface (LocalDocker now, remote later)

## Status

Accepted

## Context

v1 runs sandboxes via local Docker; the roadmap targets dedicated cloud VMs. The engine's `SandboxManager` hardcodes `DockerDeployment` and `_facade.py` shells the local `docker` CLI; SWE-ReX already ships `RemoteDeployment`/`fargate`/`modal`/`daytona` (unused by DKMV). We want cloud to be a swap, not a rewrite.

## Decision

The orchestrator depends only on an `Executor` interface: `start(run_spec) -> handle`, `stream(handle)`, `signal(handle, pause|resume|cancel)`, `cleanup(handle)`. v1 ships **`LocalDockerExecutor`** (wraps `RunService`/`EmbeddedRuntime` + local Docker under gVisor). The contract specifies that `stream()` is **re-attachable by `run_id`** and `signal(cancel)` works remotely — even though only `LocalDockerExecutor` ships — so the seam doesn't bake in the in-process assumption. **Do not** build `SSHRemoteDockerExecutor`/`K8sJobExecutor` in v1 (YAGNI); making `SandboxManager` deployment-pluggable is an engine ask (§11.3).

## Consequences

- + Cloud execution is additive; the orchestrator is execution-agnostic.
- − Today's `LocalDockerExecutor` still depends on the engine's local-Docker assumptions (engine ask to abstract).
- Implication: keep all container ops behind the `Executor`; don't let the orchestrator call Docker directly.

## PRD Reference

§8.7, §11 (engine ask 3), N2, R-9.
