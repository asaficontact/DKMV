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

### 2. Build the sandbox image → SBOM scan → pin by digest (binding — §8.6, AC-13)

The preflight check only *checks* for this image; nothing auto-builds it, so
build it once from the engine's image context. From the **repo root**:

```bash
docker build -t dkmv-sandbox:build dkmv/images/
```

Then **generate + scan an SBOM** and **pin the image by digest** (never the
mutable `:latest` tag — the sandbox runs autonomous, attacker-influenceable
agents, so a re-pushed tag could silently swap the image under a run):

```bash
# SBOM (CycloneDX) + vulnerability scan (Trivy or Docker Scout); fails on HIGH/CRITICAL.
bash platform/scripts/sbom-scan.sh dkmv-sandbox:build

# Resolve + record the immutable content digest into your deploy .env:
eval "$(bash platform/scripts/sbom-scan.sh --print-digest-env dkmv-sandbox:build)"
echo "DKMV_IMAGE=$DKMV_IMAGE" >> platform/.env     # -> dkmv-sandbox@sha256:<digest>
```

`docker-compose.yml` consumes `DKMV_IMAGE` **by digest** (`dkmv-sandbox@sha256:…`)
and never falls back to `:latest`; CI wires `sbom-scan.sh` as a release gate. In
an environment without a real built image, the script emits the documented
all-zero **placeholder** digest so the pin-by-digest contract still holds — replace
it with the real digest before a production deploy.

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
POSTs. The SSE auth token rides an HttpOnly `SameSite=Strict` cookie (set on the
first authenticated `POST /runs`) and never appears in a URL. Loopback alone is
not sufficient. The middleware is `app/security/access_control.py`; a request
without the token gets `401`, a foreign `Host`/`Origin` gets `403`. The browser
app reads the token from a runtime-injected global (`window.__DKMV_TOKEN__`); in
`npm run dev` the Vite proxy injects it server-side from `DKMV_PLATFORM_TOKEN` so
it never ships in the bundle — see [`docs/setup.md`](docs/setup.md#local-dev) and
the root `PLATFORM_E2E_TESTING.md`.

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
| `DKMV_IMAGE` | `dkmv-sandbox@sha256:…` | Sandbox image — **pin by digest** in the release/compose path, never `:latest` (§8.6, AC-13). The in-app dev default is the `:latest` tag; the digest is resolved by `scripts/sbom-scan.sh`. |
| `SANDBOX_RUNTIME` | `runsc` | gVisor by default (INV-3). |
| `MAX_CONCURRENT_RUNS` | `3` | Dispatch concurrency cap — the `asyncio.Semaphore` ceiling (5.1 / NFR-SCALE-1). |
| `HOST_MEMORY_BUDGET` | _(none)_ | Total host memory for aggregate admission, e.g. `32g`; a run is denied + re-queued if `Σ container memory` would exceed it (5.1 / §8.2). Unset disables the memory dimension. |
| `DAILY_SPEND_CAP` | _(none)_ | Daily USD cap; a run is denied + re-queued once today's **Codex-excluded** segment-sum spend exceeds it (5.1 / INV-8). Unset disables it. |
| `PER_STATE_CAPS` | _(empty)_ | Optional per-tick dispatch throttle per `agent:*` state, e.g. `agent:queued:2` (5.1). |
| `EGRESS_ALLOWLIST` | GitHub + model APIs | Default-on network allowlist (INV-3). |
| `DKMV_PROJECT_ROOT` | _(none)_ | Optional local working copy of the connected project (the dir holding `.dkmv/` — the `components.json` registry). Lets the Workflows viewer + launch path resolve registered custom components; unset → built-ins only. |
| `DKMV_SECRET_KEY` | _(none)_ | Fernet key for the encrypted `SecretStore` (INV-4); source from the OS keychain / a sealed secret in prod. Generate one with `python -c "from app.secrets import SecretStore; print(SecretStore.generate_key())"`. |

**Capability-aware run timeouts (5.2 / ADR-P009).** For **Codex** (no budget / no
turn cap — timeout is the *only* runtime guardrail), the default `timeout_minutes`
is **strictly tighter** than the Claude default (`CODEX_DEFAULT_TIMEOUT_MINUTES=20`
vs `CLAUDE_DEFAULT_TIMEOUT_MINUTES=40`, in `app/config.py`). The API **rejects**
`max_budget_usd` / `max_turns` for a resolved Codex agent with `400
unsupported_for_agent`; the launch UI states *"Codex runs are time-bounded, not
cost-bounded."*

Secrets live in the encrypted `SecretStore`, not plain env, in real deployments
(PRD §8.6).

### Secrets & exfiltration containment (INV-3 / INV-4, slice 0.5)

The sandbox-security capstone (`backend/app/secrets/` + `backend/app/executor/egress.py`):

- **Egress allowlist (network-enforced, default-on).** `EGRESS_ALLOWLIST` is
  applied at the **network layer** — the sandbox joins an internal,
  egress-filtered Docker network (`--network=dkmv-egress`) with DNS pinned to a
  trusted resolver, so the agent cannot opt out (no honor-system `endsWith`
  bypass). An empty allowlist falls back to the GitHub + model-API defaults,
  never allow-all. See `EgressPolicy`.
- **Encrypted `SecretStore` + file-mount injection.** Secrets are encrypted at
  rest (Fernet) and injected into a run as a **read-only file mount under
  `/run/secrets/`**, never as an environment variable (keeps them out of
  `docker inspect` / crash logs, §8.6).
- **Repo-scoped, ≤1 hr GitHub token.** `GitHubTokenMinter` mints a token scoped
  to exactly the one target repo with a ≤1 hr TTL; `MintedToken.authorize_push`
  refuses a second repo even under prompt injection.
- **Redact-before-persist.** Every event payload is scrubbed for known secret
  shapes (`sk-ant-…`, `ghp_…`, `github_pat_…`, `ANTHROPIC_API_KEY=…`) **and** the
  platform's own credential values *before* it reaches the append-only `events`
  table (a leak there is permanent + replayable). The same `RedactingLogFilter`
  scrubs structured logs. This is a backstop, not the boundary — the egress
  allowlist + repo-scoped token are the actual containment controls.

Run the security baseline: `cd backend && pytest -q -k security_baseline`.

## Running

> **A full step-by-step end-to-end testing walkthrough** (browser flow + curl +
> the automated suites + troubleshooting) is in the repo-root
> [`PLATFORM_E2E_TESTING.md`](../PLATFORM_E2E_TESTING.md). The summary:

### Local (backend)

The runtime uses raw `aiosqlite` (no ORM `create_all`), so a **fresh DB needs the
schema created with Alembic first** — then start the server:

```bash
cd platform/backend
source .venv/bin/activate
export DKMV_PLATFORM_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
alembic upgrade head                                   # create the schema (once, per fresh DB)
uvicorn app.main:app --host 127.0.0.1 --port 8787      # serve the API
curl -fsS -H "Authorization: Bearer $DKMV_PLATFORM_TOKEN" \
  http://127.0.0.1:8787/api/v1/preflight               # readiness checks (ready:false until configured)
```

### Local (frontend)

In a second terminal, point the Vite dev proxy at the backend with the **same**
token, then start the dev server:

```bash
cd platform/frontend
npm ci
printf 'DKMV_PLATFORM_TOKEN=%s\nDKMV_BACKEND_ORIGIN=http://127.0.0.1:8787\n' "$DKMV_PLATFORM_TOKEN" > .env
npm run dev      # → http://127.0.0.1:5173 (proxies /api → the backend, injecting the token)
```

Open `http://127.0.0.1:5173` and follow the Connect → Board → Run flow.

### Docker Compose (backend + frontend)

`docker compose up` runs the migration on start, the brokered Docker socket, the
backend, and the frontend. Set the token (and the digest-pinned `DKMV_IMAGE`) in
`platform/.env` first:

```bash
cd platform
cp .env.example .env     # then fill in DKMV_PLATFORM_TOKEN, ANTHROPIC_API_KEY, DKMV_IMAGE (digest), …
docker compose up
# backend on http://127.0.0.1:8787, frontend on http://127.0.0.1:5173
```

## Backup & restore (binding — §6.5, AC-14)

The single SQLite file is the **source of truth for spend + audit**, so back it up
and verify the backup is restorable. The backup is a consistent `VACUUM INTO`
snapshot (fully checkpointed + defragmented), taken on the single writer so it
never races a write. The helper lives in `backend/app/db/backup.py`.

**Take + verify a snapshot** (the platform may stay running — `VACUUM INTO` is
consistent):

```python
from app.db.backup import snapshot, verify_backup, backup_summary
await snapshot(repository, "/data/backups/dkmv-2026-06-09.db")   # VACUUM INTO
await verify_backup("/data/backups/dkmv-2026-06-09.db")          # integrity + schema
print(await backup_summary("/data/backups/dkmv-2026-06-09.db"))  # row counts + spend rollup
```

`verify_backup` runs SQLite's own `PRAGMA integrity_check` + `foreign_key_check`
and confirms the spend/audit schema — a snapshot that does not pass is **not** a
backup.

**Restore procedure (offline).** The platform MUST be stopped during a restore (a
live process holds WAL connections to the file being swapped):

```bash
# 1. Stop the stack.
cd platform && docker compose down            # or stop the local uvicorn

# 2. Verify + install the snapshot as the live DB (the prior DB is moved aside,
#    the snapshot is re-verified after install). restore() refuses a corrupt
#    snapshot (fail-closed) so a bad backup can never replace a good DB.
python -c "import asyncio; from app.db.backup import restore; \
  asyncio.run(restore('/data/backups/dkmv-2026-06-09.db', '/data/dkmv.db'))"

# 3. Start the stack — it comes up on the restored DB.
cd platform && docker compose up
```

The prior live DB is preserved as `<live>.pre-restore`, so the restore is
reversible. The round-trip is covered by `backend/tests/test_backup.py` (snapshot →
restore → row counts + the Codex-excluded spend rollup MATCH).

## Scope & known limitations (v1 — honest)

v1 is a **single-operator, single-repo, loopback** control plane. The documented
residuals (full detail + the compensating controls in
[`docs/acceptance_matrix.md`](docs/acceptance_matrix.md#known-limitations-v1--honest)):

- **One connected repo** — the orchestrator polls + dispatches for exactly one
  project; multi-repo is post-v1.
- **Sandbox isolation** is pinned per-run (gVisor `--runtime` + the `dkmv-egress`
  network + `--dns`) and **fail-closes** if gVisor isn't registered, but the
  **over-the-wire** egress block needs live Docker+gVisor validation — see
  [`docs/egress.md`](docs/egress.md).
- **PR-push approval gate** fires for workflow-authored pauses; the agent pushes
  in-container, so an arbitrary in-container push isn't intercepted (the egress
  allowlist is the compensating control; a pre-push hook is an engine §11 ask).
- **GitHub credential** is a fine-grained, repo-scoped operator PAT, **file-mounted**
  (not env); short-lived per-run GitHub-App tokens are post-v1 (ADR-P004).
- **Observability:** `GET /api/v1/health/orchestrator` surfaces loop health (detects a
  wedged loop) and `GET /api/v1/audit` the audit trail; both are authenticated.

## Acceptance matrix (v1 ship sign-off — §13)

The PRD §13 end-to-end acceptance suite lives in `backend/tests/e2e/` (one module
per AT) and is run by `cd platform/backend && pytest -q tests/e2e`. The
live-vs-Docker-gated breakdown + the sign-off are recorded in
[`docs/acceptance_matrix.md`](docs/acceptance_matrix.md). Full dev-env setup +
deploy details are in [`docs/setup.md`](docs/setup.md).

## Quality gates

```bash
# Backend — lint, format, type, test (≥80% coverage). 645 tests + the §13 e2e suite.
cd platform/backend
ruff check . && ruff format --check . && mypy app && pytest -q --cov --cov-fail-under=80

# Frontend — type-check + the vitest suite (118 tests incl. the a11y axe + contrast checks).
cd platform/frontend
npm ci
npx tsc --noEmit && npx vitest run
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
