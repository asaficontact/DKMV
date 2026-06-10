# DKMV Platform — Dev-environment setup & deploy (PRD §8.8)

This is the binding §8.8 setup guide: how to bring the platform up from a fresh
checkout, build + digest-pin the sandbox image, wire the brokered Docker socket,
configure the consolidated env surface, deploy with `docker compose up`, and run
the backup/restore procedure. The high-level overview lives in
[`../README.md`](../README.md); this is the operational detail.

> Source of truth: `docs/design_docs/platform/PRD_dkmv_platform_v1.md` (§8.8, §8.6,
> §6.5). The engine (`dkmv/`) is **locked** — consumed in-process via
> `dkmv.runtime.EmbeddedRuntime`, never shelled.

## 1. Editable engine install

The backend imports the engine in-process, so `dkmv` must be importable.

```bash
cd platform/backend
uv venv --python 3.12 && source .venv/bin/activate
uv pip install -e ../../          # the locked dkmv engine (editable, repo root)
uv pip install -e '.[dev]'        # the platform backend + dev tooling
python -c "import dkmv.runtime; from dkmv.runtime import EmbeddedRuntime"   # verify
```

(With plain pip: `python -m venv .venv && source .venv/bin/activate && pip install
-e ../../ && pip install -e '.[dev]'`.)

## 2. Build the sandbox image → SBOM scan → digest pin (§8.6, AC-13)

The sandbox runs autonomous, attacker-influenceable coding agents, so its image is
**digest-pinned** (never the mutable `:latest` tag) and **SBOM-scanned** before
release.

```bash
# Build the image (from the repo root).
docker build -t dkmv-sandbox:build dkmv/images/

# Generate a CycloneDX SBOM + scan for vulnerabilities (Trivy or Docker Scout);
# the script fails the build on HIGH/CRITICAL findings.
bash platform/scripts/sbom-scan.sh dkmv-sandbox:build

# Resolve the immutable content digest and record it in the deploy .env.
eval "$(bash platform/scripts/sbom-scan.sh --print-digest-env dkmv-sandbox:build)"
echo "DKMV_IMAGE=$DKMV_IMAGE" >> platform/.env       # DKMV_IMAGE=dkmv-sandbox@sha256:<digest>
```

**How prod resolves the real digest.** `docker build` produces an image whose
`RepoDigests` is the immutable `name@sha256:<digest>` reference; `sbom-scan.sh
--print-digest-env` reads it via `docker image inspect` and prints the env line.
CI pushes the image to the registry, captures the pushed digest, and writes
`DKMV_IMAGE=dkmv-sandbox@sha256:<digest>` into the deploy environment — so
`docker-compose.yml` (which consumes `${DKMV_IMAGE}`) always pins by digest. In an
environment with no real built image, the script emits the documented **all-zero
placeholder** digest so the pin-by-digest contract holds; replace it with the real
digest before a production deploy. A literal `dkmv-sandbox:latest` never appears in
the release/compose path.

Optionally pin the **base** images by digest too (defense-in-depth): replace
`python:3.12-slim` in `Dockerfile.backend` with `python:3.12-slim@sha256:<digest>`.

## 3. Brokered Docker socket + platform-owned output dir

The backend reaches Docker **only** through a method-allowlisted, non-root socket
proxy — never a raw `-v /var/run/docker.sock` mount (the Docker API is
root-equivalent). `docker-compose.yml` ships the `tecnativa/docker-socket-proxy`
service (`docker-proxy`):

- `/var/run/docker.sock` is mounted **only** into `docker-proxy` (read-only) and
  **never** the `backend` service.
- The proxy allow-lists only the verbs the orchestrator needs
  (`CONTAINERS`/`IMAGES`/`NETWORKS`/`INFO`/`VERSION` + `POST`) and denies the
  dangerous surfaces (`EXEC`, `SECRETS`, `SWARM`, `SYSTEM`, `VOLUMES`, `BUILD`, …).
- The backend talks to it via `DOCKER_HOST=tcp://docker-proxy:2375` over the
  internal-only `docker-broker` network (`internal: true`).

Alternatives (also §8.8-valid): **rootless Docker** or **Sysbox** — point
`DOCKER_HOST` at the rootless socket. Either avoids the raw root socket.

The engine's `output_dir` points at a **platform-owned** volume (`OUTPUT_DIR`,
mapped to `backend-data:/data/outputs`) so runs/artifacts are owned by the
platform, not scattered in the working copy.

## 4. Sandbox isolation (gVisor runsc — INV-3 / NFR-SEC-4)

Runs execute under **gVisor (`runsc`)** by default (`SANDBOX_RUNTIME=runsc`). Plain
`runc` shares the host kernel and is not a security boundary for this workload. The
executor (`app/executor/runtime_policy.py`) resolves the runtime once at
construction and pins the container with `--runtime=runsc`. If `runsc` is selected
but unavailable on the host, the executor **fails closed** (raises
`WeakerIsolationError`) unless the operator explicitly opts into the weaker
fallback. Install gVisor and enable it as a Docker runtime; setting the daemon's
`default-runtime: runsc` (and/or `DOCKER_DEFAULT_RUNTIME` in compose) makes it the
default for engine-launched containers.

The **egress allowlist** is default-on + network-enforced: the sandbox joins an
internal, egress-filtered network (`--network=dkmv-egress`) with DNS pinned to a
trusted resolver, so the agent cannot opt out. `EGRESS_ALLOWLIST` defaults to
GitHub + the model APIs; an empty allowlist falls back to those defaults, never
allow-all.

## 5. Consolidated env surface (§8.8)

Copy `.env.example` → `.env` and fill it in. The full key list + defaults are in
[`../.env.example`](../.env.example); the platform reads **all** config through the
single typed `Settings` object (`app/config.py`). The keys that govern Phase-5
behavior:

| Key | Default | Purpose |
|---|---|---|
| `DKMV_PLATFORM_TOKEN` | _(empty)_ | Local auth token, required on every API/SSE request (INV-1). |
| `DKMV_PLATFORM_BIND` | `127.0.0.1:8787` | Loopback bind (INV-1). |
| `DATABASE_URL` | `sqlite:///./data/dkmv.db` | The single SQLite (WAL) DB — source of truth for spend + audit. |
| `OUTPUT_DIR` | `./data/outputs` | Platform-owned runs/artifacts volume. |
| `DKMV_IMAGE` | `dkmv-sandbox@sha256:…` | Sandbox image, **digest-pinned** in release/compose (§8.6, AC-13). |
| `SANDBOX_RUNTIME` | `runsc` | gVisor by default (INV-3). |
| `EGRESS_ALLOWLIST` | GitHub + model APIs | Default-on network allowlist (INV-3). |
| `MAX_CONCURRENT_RUNS` | `3` | Dispatch concurrency cap — the `asyncio.Semaphore` ceiling (5.1). |
| `HOST_MEMORY_BUDGET` | _(none)_ | Aggregate memory admission budget, e.g. `32g` (5.1 / §8.2). |
| `DAILY_SPEND_CAP` | _(none)_ | Daily USD cap — Codex-excluded segment-sum (5.1 / INV-8). |
| `PER_STATE_CAPS` | _(empty)_ | Optional per-tick `agent:*`-state throttle, e.g. `agent:queued:2` (5.1). |
| `DKMV_PROJECT_ROOT` | _(none)_ | Local working copy holding `.dkmv/` (custom-component registry). |
| `DKMV_SECRET_KEY` | _(none)_ | Fernet key for the encrypted `SecretStore` (INV-4). |

**Capability-aware cost (5.2 / ADR-P009).** Codex runs are **time-bounded, not
cost-bounded**: timeout is the only guardrail and its default is strictly tighter
than the Claude default (`CODEX_DEFAULT_TIMEOUT_MINUTES=20` <
`CLAUDE_DEFAULT_TIMEOUT_MINUTES=40`). The API rejects `max_budget_usd` / `max_turns`
for a Codex agent with `400 unsupported_for_agent`; Codex cost renders "—" and is
excluded from spend.

## 6. Run the schema migration (binding — fresh DB)

The runtime uses raw `aiosqlite` (no SQLAlchemy ORM `create_all`), so a **fresh
database needs the schema created with Alembic** before the first request — the
app does not auto-create it. `docker compose up` runs this automatically on start
(the backend image's entrypoint runs `alembic upgrade head` before `uvicorn`); for
a **local** backend run it once yourself:

```bash
cd platform/backend && source .venv/bin/activate
alembic upgrade head        # creates the 9 tables; idempotent (no-op when at head)
```

<a name="local-dev"></a>
## 6a. Local dev (two terminals)

The fastest loop for exercising the UI + flows without Docker (an actual agent
*run* still needs Docker + the sandbox image — see the root
`PLATFORM_E2E_TESTING.md`):

```bash
# Terminal 1 — backend
cd platform/backend && source .venv/bin/activate
export DKMV_PLATFORM_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8787      # add --reload for hot reload

# Terminal 2 — frontend (Vite dev proxy → backend, same token)
cd platform/frontend && npm ci
printf 'DKMV_PLATFORM_TOKEN=%s\nDKMV_BACKEND_ORIGIN=http://127.0.0.1:8787\n' "$DKMV_PLATFORM_TOKEN" > .env
npm run dev                                            # → http://127.0.0.1:5173
```

The frontend talks to the backend over a same-origin `/api/v1` base; `vite.config.ts`
proxies `/api` → `DKMV_BACKEND_ORIGIN` and injects `DKMV_PLATFORM_TOKEN` as the
`Authorization: Bearer` header **server-side**, so the token never ships in the
browser bundle (INV-1). The SSE stream then authenticates via the HttpOnly cookie
the backend sets on `POST /runs`.

## 7. Deploy: `docker compose up`

```bash
cd platform
cp .env.example .env     # fill in DKMV_PLATFORM_TOKEN, ANTHROPIC_API_KEY/CODEX_API_KEY, DKMV_IMAGE (digest), …
docker compose up
# backend on http://127.0.0.1:8787 (loopback only), frontend on http://127.0.0.1:5173
```

`docker compose up` brings up the brokered Docker socket proxy, runs the schema
migration, starts the backend, and starts the frontend (its Vite proxy targets the
`backend` service and injects `DKMV_PLATFORM_TOKEN`). Both services publish to the
host loopback only (`127.0.0.1`). The backend additionally requires the local token
+ Host/Origin validation + CSRF (INV-1); loopback alone is not sufficient.

## 8. Backup & restore (§6.5, AC-14)

The single SQLite file is the source of truth for spend + audit. The backup is a
consistent `VACUUM INTO` snapshot; the helper is `app/db/backup.py`.

**Take + verify a snapshot** (the platform may stay running):

```python
from app.db.backup import snapshot, verify_backup
await snapshot(repository, "/data/backups/dkmv-YYYY-MM-DD.db")
await verify_backup("/data/backups/dkmv-YYYY-MM-DD.db")   # integrity_check + FK + schema
```

**Restore (offline — the platform must be stopped):**

```bash
# 1. Stop the stack (a running process holds WAL connections to the DB file).
cd platform && docker compose down

# 2. Verify + install the snapshot as the live DB. The prior DB is moved aside to
#    <live>.pre-restore (reversible); a corrupt snapshot is refused (fail-closed).
python -c "import asyncio; from app.db.backup import restore; \
  asyncio.run(restore('/data/backups/dkmv-YYYY-MM-DD.db', '/data/dkmv.db'))"

# 3. Start the stack — it comes up on the restored DB.
cd platform && docker compose up
```

The round-trip (snapshot → restore → row counts + the Codex-excluded spend rollup
MATCH) is covered by `backend/tests/test_backup.py`.

## 9. Verify the install

```bash
cd platform/backend && source .venv/bin/activate
ruff check . && ruff format --check . && mypy app && pytest -q --cov --cov-fail-under=80
pytest -q tests/e2e tests/test_backup.py          # the §13 matrix + the backup round-trip
```

The §13 acceptance matrix + the live-vs-Docker-gated breakdown are in
[`acceptance_matrix.md`](acceptance_matrix.md).
