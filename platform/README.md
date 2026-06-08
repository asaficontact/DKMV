# DKMV Platform

A self-hostable web control plane that turns GitHub Issues into autonomous
DKMV coding-agent runs. The platform **wraps the existing, locked DKMV engine**
(`../dkmv/`) by importing `dkmv.runtime.EmbeddedRuntime` **in-process** — it
never shells the `dkmv` CLI and never edits the engine.

- **Backend:** `backend/` — Python 3.12, FastAPI, SQLite (WAL) + Alembic +
  aiosqlite, sse-starlette, in-process asyncio orchestrator.
- **Frontend:** `frontend/` — React 18 + Vite + TypeScript, design tokens
  ported from the design prototype.
- **Deploy:** `docker compose up` runs the backend + frontend.

> Source of truth is the PRD: `docs/design_docs/platform/PRD_dkmv_platform_v1.md`.
> This README documents the dev-environment setup that PRD §8.8 makes binding
> for milestone M0.

## Prerequisites

- **Python ≥ 3.12** (the engine uses 3.10+ unions / `from __future__`).
- **Docker** with the **gVisor `runsc`** runtime available (the default sandbox
  runtime — see [Sandbox isolation](#sandbox-isolation-binding) below).
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip` + `venv`.
- Node 20+ / npm 10+ for the frontend.

## Dev-environment setup (binding — PRD §8.8)

M0 will **not** `docker compose up` cleanly without these steps.

### 1. Editable-install the engine into the backend env

The backend consumes the engine in-process, so the `dkmv` package must be
importable. Install it **editable** from the sibling repo root:

```bash
cd platform/backend
python -m venv .venv && source .venv/bin/activate
pip install -e .            # the platform backend
pip install -e ../../       # the dkmv engine (editable, from the repo root)
```

With `uv`:

```bash
cd platform/backend
uv venv --python 3.12
uv pip install -e . -e ../../
```

Verify the engine is importable in-process (never shelled):

```bash
cd platform/backend
python -c "import dkmv.runtime; from dkmv.runtime import EmbeddedRuntime"
python -c "import sys; assert sys.version_info[:2] >= (3, 12)"
```

### 2. Build the sandbox image

The preflight check only *checks* for this image; nothing auto-builds it, so
build it once from the engine's image context. From the **repo root**:

```bash
docker build -t dkmv-sandbox:latest dkmv/images/
```

Pin by digest for production (PRD §8.6).

### 3. Brokered Docker socket + platform-owned output dir

The backend reaches Docker through a **method-allowlisted, non-root socket
proxy** — **never** a raw `-v /var/run/docker.sock` mount (the Docker API is
root-equivalent and "a request to the API ≈ code execution on the host"; a
read-only mount does not help). The engine's `output_dir` points at a
**platform-owned** volume (`OUTPUT_DIR`), where runs/artifacts land.

`docker-compose.yml` ships the **`tecnativa/docker-socket-proxy`** service
(`docker-proxy`) as the default broker:

- `/var/run/docker.sock` is mounted **only** into `docker-proxy` (read-only) —
  it appears on exactly one service and **never** on the `backend` service.
- The proxy allow-lists only the verbs the orchestrator needs
  (`CONTAINERS`/`IMAGES`/`NETWORKS`/`INFO`/`VERSION` + `POST`) and **denies** the
  dangerous surfaces (`EXEC`, `SECRETS`, `SWARM`, `SYSTEM`, `VOLUMES`, `BUILD`,
  …).
- The backend talks to it via `DOCKER_HOST=tcp://docker-proxy:2375` over an
  **internal-only** Compose network (`docker-broker`, `internal: true`) — the
  proxy is never published to the host.

**Alternatives** (also valid per §8.8): run **rootless Docker** or **Sysbox** on
the host and point `DOCKER_HOST` at the rootless socket — both avoid exposing the
root socket. Pick one; do not raw-mount the socket into the backend.

## Sandbox isolation (binding — NFR-SEC-4)

Autonomous untrusted-code execution runs under **gVisor (`runsc`)** by default
(`SANDBOX_RUNTIME=runsc`). Plain `runc` shares the host kernel and is *not* a
security boundary for this workload. microVM (Firecracker/Kata) is the stronger
tier for the cloud/multi-tenant path.

The `Executor` (`backend/app/executor/`) is the single seam that owns runtime
policy: at construction `LocalDockerExecutor` resolves the effective runtime from
`SANDBOX_RUNTIME` via `app.executor.runtime_policy.resolve_runtime()` and pins
the container to it with the `--runtime=<name>` Docker flag. The orchestrator
never calls Docker directly — all container ops go through the `Executor`
interface (`start`/`stream`/`signal`/`cleanup`; `stream` is re-attachable by
`run_id` per ADR-P008).

### Weaker-isolation opt-in + warning (OQ-6)

gVisor is the default and the secure posture is **fail-closed**:

- **`runsc` selected (default) and available** → used silently.
- **`runsc` selected but the runtime is unavailable on the host** (some Docker
  Desktop hosts lack `runsc`) → the executor logs the
  **`SANDBOX ISOLATION WARNING: SANDBOX_RUNTIME=runsc but the runsc (gVisor)
  runtime is unavailable…`** warning and **raises `WeakerIsolationError`** so the
  backend will not silently downgrade to `runc`. To deliberately accept weaker
  isolation on a trusted single-user host, construct the executor with
  `allow_weaker_isolation=True` (it then logs the weaker-isolation warning and
  falls back to `runc`).
- **A non-`runsc` runtime selected explicitly** (e.g. `SANDBOX_RUNTIME=runc`) is
  itself the documented **weaker-isolation opt-in**: the executor logs
  **`SANDBOX ISOLATION WARNING: running sandboxes under a non-runsc runtime is a
  weaker-isolation opt-in…`** and honors the choice. Only do this on a trusted,
  single-user host; you lose the primary kernel-isolation boundary against
  prompt-injected untrusted agent code (R-13/R-14).

Install gVisor and enable it as a Docker runtime so `runsc` is available; on the
host, setting the daemon's `default-runtime: runsc` (and/or the
`DOCKER_DEFAULT_RUNTIME` env wired in `docker-compose.yml`) makes gVisor the
default for engine-launched sandbox containers.

## App network / auth (binding — NFR-SEC-2)

The backend binds **`127.0.0.1`** and requires a **local auth token**
(`DKMV_PLATFORM_TOKEN`) on every API/SSE request; it validates `Host`/`Origin`
headers (anti-DNS-rebinding) and applies CSRF protection on state-changing
POSTs. The SSE auth token rides an HttpOnly `SameSite=Strict` cookie and never
appears in a URL. Loopback alone is not sufficient. (The middleware lands in the
`0.2-runservice` slice.)

## Configuration (PRD §8.8 env surface)

All configuration is read through the single typed settings object
(`backend/app/config.py`). See [`.env.example`](.env.example) for the full key
list and defaults. Highlights:

| Key | Default | Notes |
|---|---|---|
| `DKMV_PLATFORM_TOKEN` | _(empty)_ | Local auth token (required in real use). |
| `DKMV_PLATFORM_BIND` | `127.0.0.1:8787` | Loopback bind (INV-1). |
| `DATABASE_URL` | `sqlite:///./data/dkmv.db` | SQLite (WAL); Postgres later. |
| `OUTPUT_DIR` | `./data/outputs` | Platform-owned runs/artifacts volume. |
| `DKMV_IMAGE` | `dkmv-sandbox:latest` | Sandbox image (pin by digest in prod). |
| `SANDBOX_RUNTIME` | `runsc` | gVisor by default (INV-3). |
| `MAX_CONCURRENT_RUNS` | `3` | Dispatch concurrency cap. |
| `DAILY_SPEND_CAP` | _(none)_ | Daily USD cap; unset disables it. |
| `EGRESS_ALLOWLIST` | GitHub + model APIs | Default-on network allowlist (INV-3). |

Secrets live in the encrypted `SecretStore`, not plain env, in real deployments
(PRD §8.6).

## Running

### Local (backend)

```bash
cd platform/backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8787
curl -fsS -H "Authorization: Bearer $DKMV_PLATFORM_TOKEN" \
  http://127.0.0.1:8787/api/v1/preflight
```

### Docker Compose (backend + frontend)

```bash
cd platform
docker compose up
# backend on http://127.0.0.1:8787, frontend on http://127.0.0.1:5173
```

## Quality gates

```bash
# Backend
cd platform/backend
ruff check . && ruff format --check . && mypy app && pytest -q --cov --cov-fail-under=80

# Frontend (scaffold only in Phase 0)
cd platform/frontend
npm ci
npx tsc --noEmit
```

## Layout

```
platform/
  backend/   app/ (FastAPI: api/ orchestrator/ github/ executor/ db/ sse/ secrets/ security/)
  frontend/  (React + Vite + TypeScript; design tokens ported from the prototype)
  docker-compose.yml   Dockerfile.backend   Dockerfile.frontend
  README.md   alembic/   pyproject.toml
  backend/pyproject.toml
```

`pyproject.toml` at the `platform/` root is a thin, installable wrapper over the
backend package (it builds the same `app` module under `backend/`), present to
match the PRD §8.8 repo layout. The **canonical** dev/test/CI flow stays in
`backend/`: `cd platform/backend && ruff check . && mypy app && pytest -q` and
`alembic upgrade head` all read `backend/pyproject.toml` (the source of truth for
tool config + dependencies), mirroring how `alembic/` points at
`backend/alembic/`.
