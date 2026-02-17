# Sandbox Layer: SWE-ReX

## Status

Accepted

## Context and Problem Statement

DKMV needs to manage Docker container lifecycles and execute commands inside containers. This includes starting containers, running shell commands, reading/writing files, and stopping containers. Should we use a container management library or build our own Docker wrapper?

## Decision Drivers

- Need persistent sessions inside containers (not just one-shot commands)
- Need file I/O operations (read/write files inside running containers)
- Must support environment variable forwarding to containers
- Should be backend-swappable (Docker today, Modal/Fargate in v2+)
- Proven at scale in similar AI agent workloads

## Considered Options

- SWE-ReX (Software Engineering Remote Execution) — purpose-built for AI agent container orchestration
- Raw Docker SDK (`docker-py`) — direct Docker API access
- Subprocess calls to `docker` CLI — shell out to docker commands
- Kubernetes Jobs — container orchestration via k8s

## Decision Outcome

Chosen option: "SWE-ReX", because it provides a high-level abstraction for container lifecycle management with persistent sessions, file I/O, and bash execution — exactly what DKMV needs — and is proven at scale in SWE-bench evaluations.

### Architecture

```
Host Machine (DKMV CLI)
┌──────────────────────────────────────────────────┐
│  SandboxManager (dkmv/core/sandbox.py)           │
│  ├── start()    → DockerDeployment.start()       │
│  ├── execute()  → runtime.run_in_session()       │
│  ├── stop()     → DockerDeployment.stop()        │
│  ├── write_file() → runtime.write_file()         │
│  ├── read_file()  → runtime.read_file()          │
│  └── stream_claude() (file-based workaround)     │
└──────────────────┬───────────────────────────────┘
                   │ SWE-ReX API (async)
                   ▼
┌──────────────────────────────────────────────────┐
│  DockerDeployment                                │
│  ├── Creates container from dkmv-sandbox image   │
│  ├── Manages ports, memory, env vars             │
│  ├── container_name (auto-generated)             │
│  └── remove_container flag (set at construction) │
│                                                  │
│  RemoteRuntime                                   │
│  ├── run_in_session(session, BashAction)         │
│  ├── read_file(ReadFileRequest)                  │
│  └── write_file(WriteFileRequest)                │
└──────────────────┬───────────────────────────────┘
                   │ Docker API
                   ▼
┌──────────────────────────────────────────────────┐
│  Docker Container (dkmv-sandbox)                 │
│  ├── swerex-remote (SWE-ReX server, via pipx)    │
│  ├── Named sessions: "default", "tail"           │
│  ├── Persistent bash state within each session   │
│  └── File system (PRD, code, artifacts)          │
└──────────────────────────────────────────────────┘
```

### File-Based Streaming Workaround

SWE-ReX's `run_in_session()` blocks until a command completes. Since Claude Code runs can take 10-30+ minutes, DKMV uses a workaround with two concurrent sessions:

```
Session "default"                    Session "tail"
┌─────────────────────┐             ┌──────────────────────┐
│ claude -p "..."     │             │ tail -n +N           │
│   --output-format   │  writes to  │   /tmp/dkmv_stream   │
│   stream-json       │ ──────────► │   .jsonl             │
│ > /tmp/dkmv_stream  │  (file)     │                      │
│   .jsonl &          │             │ Reads new lines      │
│                     │             │ every poll cycle      │
│ echo $! (PID)       │             │                      │
└─────────────────────┘             └──────────┬───────────┘
                                               │ yields events
                                               ▼
                                    ┌──────────────────────┐
                                    │ Host: StreamParser    │
                                    │ Parse JSON → render   │
                                    └──────────────────────┘
```

### Consequences

- Good: `DockerDeployment` handles container creation, port allocation, and cleanup.
- Good: `RemoteRuntime` provides persistent bash sessions and file I/O via `run_in_session()`, `ReadFileRequest`, `WriteFileRequest`.
- Good: Backend-swappable by design — Docker, Modal, and Fargate deployments share the same `RemoteRuntime` interface.
- Good: Automatic port allocation avoids conflicts when running multiple containers.
- Bad: Additional dependency (`swe-rex>=1.4`) with transitive dependencies including `aiohttp`.
- Bad: SWE-ReX's `run_in_session()` blocks until command completes, requiring the file-based streaming workaround above.
- Neutral: SWE-ReX uses `start()`/`stop()` methods rather than async context managers, requiring explicit lifecycle management.

## Implementation Notes

- SWE-ReX is installed inside the container via `pipx install swe-rex` (as the non-root `dkmv` user)
- Container naming is auto-generated by SWE-ReX via `deployment.container_name`
- `remove_container` flag is set at deployment construction time, not at stop time
- PID of Claude Code process is tracked for timeout handling (killed in `finally` block)
- Tail session is cleaned up in `finally` block to prevent double-close in `stop()`
