# DKMV Platform — End-to-End Local Testing Guide

This guide walks you through running the **DKMV Platform** (the web control plane
in `platform/`) on your machine and testing it end-to-end: the automated test
suites, the backend control plane, the browser UI, the API directly with `curl`,
and a full sandboxed agent run.

It is grounded in the actual code — every command here was verified against the
current `platform` branch.

> **Companion docs:** [`platform/README.md`](platform/README.md) (overview +
> config surface), [`platform/docs/setup.md`](platform/docs/setup.md) (deploy
> detail), [`platform/docs/acceptance_matrix.md`](platform/docs/acceptance_matrix.md)
> (the §13 acceptance matrix). This guide ties them together for a tester.

---

## 1. What the platform is (one screen)

```
   Browser (React/Vite UI, :5173)
        │  relative /api/v1  (Vite dev-proxy injects the local token)
        ▼
   FastAPI control plane (backend, :8787, loopback only)
        │  in-process import (never the CLI)
        ▼
   dkmv engine  ──launches──▶  sandboxed agent run (Docker container,
   (locked, ../dkmv)                gVisor/runsc, egress-allowlisted)
        │
        ▼
   SQLite (WAL) — runs / events / spend / audit (the source of truth)
```

- The **backend** turns a GitHub issue into an autonomous coding-agent run, streams
  the run live over SSE, pauses for human approval (HITL), and opens a PR.
- The **frontend** is the Connect → Board → Run → Live UI.
- The **engine** (`dkmv/`) is **locked** and consumed **in-process**; the platform
  never shells the `dkmv` CLI and never edits the engine.
- Everything binds **loopback only** and requires a **local token** (it can reach a
  root-equivalent Docker socket and spend real money — it must not be open).

## 2. What you can test — with and without Docker

You do **not** need Docker to test most of the platform. Be clear on the split:

| Capability | Needs Docker? | Notes |
|---|---|---|
| All automated test suites (645 backend + §13 e2e in-process + 118 frontend + backup + security baseline) | **No** | The in-process suites run the real FastAPI app + components against fakes. |
| Backend control plane (health, preflight, connect, board sync, run **validation/launch** path) | **No** | `preflight` will report Docker/sandbox-image as missing, but the API works. |
| The browser UI (Connect, Board, Issue, Run panel, navigation) | **No** | You can click through everything up to the point a run actually executes. |
| An actual **agent run executing** (clone repo, run the agent, stream real events, open a PR) | **Yes** | Needs Docker + the `dkmv-sandbox` image + a model API key. |
| Full sandbox **isolation** (gVisor) + over-the-wire egress-deny | **Yes + gVisor** | `SANDBOX_RUNTIME=runsc`; the live-isolation e2e halves gate behind `DKMV_E2E_LIVE=1`. |

**Recommended order:** Part A (automated suites) → Part B (run it locally) → Part C
(browser walkthrough) / Part D (curl) → Part E (a real run, if you have Docker).

## 3. Prerequisites

- **Python ≥ 3.12** and [`uv`](https://docs.astral.sh/uv/) (recommended) or
  `python -m venv` + `pip`.
- **Node ≥ 20 / npm ≥ 10** (for the frontend).
- **A GitHub fine-grained PAT** scoped to **one repo** with these four permissions
  (needed for Connect + real runs, not for the automated suites):
  `issues:write`, `pull_requests:write`, `contents:write`, `metadata:read`.
- **At least one model key** for real runs: `ANTHROPIC_API_KEY` (Claude) and/or
  `CODEX_API_KEY` (Codex).
- **Docker** (+ optionally **gVisor `runsc`**) — only for Part E (real runs).

---

## Part A — Run the automated test suites (no Docker)

This is the fastest, most complete end-to-end verification: it exercises the whole
control plane, the orchestrator, HITL, recovery, concurrency, cost governance, and
the §13 acceptance matrix in-process.

### A.1 Backend — install + the full suite

```bash
cd platform/backend

# Create a venv and install the locked engine (editable) + the backend + dev tooling.
uv venv --python 3.12
VIRTUAL_ENV="$(pwd)/.venv" uv pip install -e ../../ -e '.[dev]'
# (plain pip alternative: python -m venv .venv && source .venv/bin/activate
#  && pip install -e ../../ && pip install -e '.[dev]')

# Verify the engine imports in-process (it must — the platform never shells the CLI).
.venv/bin/python -c "from dkmv.runtime import EmbeddedRuntime; print('engine OK')"

# Lint, type-check, and the full suite with coverage (≥80%).
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy app
.venv/bin/pytest -q --cov --cov-fail-under=80
```

Expected: **645 passed, 2 skipped** (the 2 skips are the live-gVisor e2e halves).

### A.2 The §13 acceptance matrix + the backup round-trip

```bash
cd platform/backend
.venv/bin/pytest -q tests/e2e tests/test_backup.py
```

Expected: **32 passed, 2 skipped**. The matrix is documented in
[`platform/docs/acceptance_matrix.md`](platform/docs/acceptance_matrix.md). To run
the two live-isolation halves you need Docker + `runsc`:

```bash
DKMV_E2E_LIVE=1 .venv/bin/pytest -q tests/e2e/test_at_isolation.py
```

### A.3 The security baseline

```bash
cd platform/backend
.venv/bin/pytest -q -k security_baseline
```

Asserts the access-control stack (loopback + token + Host/Origin + CSRF), secret
redaction, and the no-secret-in-events invariant.

### A.4 Frontend — type-check + the vitest suite

```bash
cd platform/frontend
npm ci
npx tsc --noEmit
npx vitest run
```

Expected: **118 passed** (includes the axe accessibility + AA-contrast render checks).

---

## Part B — Run the platform locally (two terminals)

### B.1 Terminal 1 — the backend

```bash
cd platform/backend
source .venv/bin/activate                       # the venv from Part A

# A strong local token. EVERY API/SSE request must present it (INV-1).
export DKMV_PLATFORM_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo "token: $DKMV_PLATFORM_TOKEN"               # copy this — the frontend needs the same value

# (Optional, but recommended) a stable secret-store key so a GitHub PAT you connect
# survives a backend restart. If unset, a fresh dev key is generated each start and
# a previously-stored PAT becomes unreadable (you'd just re-Connect).
export DKMV_SECRET_KEY="$(python -c 'from app.secrets import SecretStore; print(SecretStore.generate_key())')"

# (Optional) a model key so real runs can execute later.
export ANTHROPIC_API_KEY="sk-ant-…"

# Create the schema on a fresh DB (the runtime uses raw aiosqlite — no auto-create),
# then serve. `data/` is created relative to the CWD by default.
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8787      # add --reload for hot reload
```

Smoke-test it from a third shell (or just below, before starting the frontend):

```bash
# Liveness is token-exempt → 200.
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/api/v1/healthz          # 200

# Readiness checks (Docker, sandbox image, model keys, GitHub write perm).
curl -s -H "Authorization: Bearer $DKMV_PLATFORM_TOKEN" \
  http://127.0.0.1:8787/api/v1/preflight | python -m json.tool

# Auth is enforced: no token → 401; a foreign Host → 403.
curl -s -o /dev/null -w 'no-token: %{http_code}\n' http://127.0.0.1:8787/api/v1/preflight   # 401
curl -s -o /dev/null -w 'bad-host: %{http_code}\n' \
  -H "Authorization: Bearer $DKMV_PLATFORM_TOKEN" -H 'Host: evil.example.com' \
  http://127.0.0.1:8787/api/v1/preflight                                                # 403
```

`preflight` returns `ready:false` until Docker, the sandbox image, and a model key
are present — that is expected for a UI-only test session. (The sandbox-image check
reports the in-app default `dkmv-sandbox:latest` until you set a digest-pinned
`DKMV_IMAGE`; see Part E.)

### B.2 Terminal 2 — the frontend

```bash
cd platform/frontend
npm ci

# Point the Vite dev proxy at the backend with the SAME token. The proxy injects it
# server-side as `Authorization: Bearer …`, so the token never ships in the browser.
printf 'DKMV_PLATFORM_TOKEN=%s\nDKMV_BACKEND_ORIGIN=http://127.0.0.1:8787\n' \
  "$DKMV_PLATFORM_TOKEN" > .env

npm run dev      # → http://127.0.0.1:5173
```

Open **http://127.0.0.1:5173**. The UI's relative `/api/v1` calls are proxied to the
backend and authenticated by the injected token; you should land on the **Connect**
screen.

> **How auth works here:** the browser app reads no token. `vite.config.ts` proxies
> `/api` → `DKMV_BACKEND_ORIGIN` and adds the `Authorization: Bearer` header on the
> server side. The SSE stream (`EventSource`, which can't set headers) authenticates
> via the HttpOnly `SameSite=Strict` cookie the backend sets on `POST /runs`.

---

## Part C — The browser walkthrough

With both terminals running, follow the product flow:

1. **Connect** (`/connect`). Paste your **fine-grained GitHub PAT** into
   *"Fine-grained personal access token"* and click **Connect GitHub**. The screen
   lists the four required permissions. The PAT is stored **encrypted** (Fernet) in
   the SecretStore — never logged, never echoed (you get back only a redacted hint
   like `github_pat_••••1234`).
   *Under the hood:* `POST /api/v1/connect/github`.

2. **Pick a repo.** The app lists repos your PAT can see (`GET /api/v1/repos`) with a
   preflight checklist. Select one and click **Open project** — this imports its
   issues (`POST /api/v1/projects/{owner}/{name}/sync`).

3. **Board** (`/board?repo=…`). Six columns keyed by agent state:
   *Backlog → Queued → In Progress → Needs You → In Review → Done*. The board is
   **poll-driven** (refreshes ~every 10 s). Drag an issue Backlog → Queued (or click a
   card to open it).

4. **Issue detail** (`/issues/{owner}/{name}/{num}`). Left: the issue (title, body,
   labels, comments). Right: the **Run panel** — pick a **workflow** (from
   `GET /api/v1/workflows`), an **agent** (`auto | claude | codex`), a **branch**
   (prefilled `dkmv/issue-{num}-…`), and optional guardrails (max budget / max turns /
   timeout / memory). For **Codex** the budget/turn fields are hidden — Codex runs are
   *time-bounded, not cost-bounded*.

5. **Launch.** Click **Run with {Claude|Codex}** → `POST /api/v1/runs`. You're taken to
   the **Live run** view (`/runs/{id}`). *(A run only actually executes if Docker + the
   `dkmv-sandbox` image + a model key are present — see Part E. Without them the launch
   validates and records, but the sandbox can't start; `preflight` will have warned you.)*

6. **Live run.** Watch the **event feed** stream (Friendly/Raw toggle), the **stage
   tracker**, and the **meters** (elapsed / cost / tokens / turns — the cost is a
   segment-sum that climbs to the run total, never resets). The stream is SSE
   (`GET /api/v1/runs/{id}/events`, cookie-authenticated).

7. **Pause / approve (HITL).** When a workflow pauses, a **decision card** appears with
   the engine-authored question + options. Choose **Approve / Ship / Abort** →
   `POST /api/v1/runs/{id}/answer`. A pause resolves exactly once (a double-submit gets
   `409`). The platform also injects an approval gate **before the PR push** as
   defense-in-depth against prompt injection.

8. **Done.** The run completes (or you **Stop** it → `POST /api/v1/runs/{id}/stop`). The
   **Runs** screen (history) shows finished runs, spend (Codex excluded, rendered "—"),
   and a retry queue; a failed run offers **Retry now**.

---

## Part D — API-level end-to-end with `curl` (no browser)

You can drive the whole control plane without the UI. Set the token first:

```bash
TOKEN="$DKMV_PLATFORM_TOKEN"
H=(-H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json')
BASE=http://127.0.0.1:8787/api/v1
```

```bash
# 1. Readiness.
curl -s "${H[@]}" "$BASE/preflight" | python -m json.tool

# 2. Connect a GitHub PAT (stored encrypted; returns a redacted hint + the perms).
curl -s "${H[@]}" -X POST "$BASE/connect/github" \
  -d '{"token":"github_pat_xxxxxxxx"}' | python -m json.tool

# 3. List the repos the PAT can see.
curl -s "${H[@]}" "$BASE/repos" | python -m json.tool

# 4. Import a repo's issues (board sync).
curl -s "${H[@]}" -X POST "$BASE/projects/<owner>/<name>/sync" | python -m json.tool

# 5. The board list + the aggregate strip.
curl -s "${H[@]}" "$BASE/repos/<owner>/<name>/issues" | python -m json.tool
curl -s "${H[@]}" "$BASE/repos/<owner>/<name>/board/aggregate" | python -m json.tool

# 6. Available workflows.
curl -s "${H[@]}" "$BASE/workflows" | python -m json.tool

# 7. Launch a run (201 + a platform run_id). Codex must NOT carry max_budget_usd/
#    max_turns — that returns 400 unsupported_for_agent.
curl -s "${H[@]}" -X POST "$BASE/runs" -d '{
  "repo":"<owner>/<name>", "issue_num":42, "workflow_id":"<id>",
  "agent":"auto", "branch":"dkmv/issue-42-demo"
}' | python -m json.tool

# 8. Stream the run's events (SSE). The cookie was set on the POST above; with curl,
#    pass the token cookie explicitly:
curl -sN -H "Cookie: dkmv_sse_token=$TOKEN" "$BASE/runs/<run_id>/events"

# 9. Answer a pause (HITL).
curl -s "${H[@]}" -X POST "$BASE/runs/<run_id>/answer" \
  -d '{"answers":{"<question_id>":"<value>"}, "skip_remaining":false}' | python -m json.tool

# 10. Stats + run history.
curl -s "${H[@]}" "$BASE/stats" | python -m json.tool
curl -s "${H[@]}" "$BASE/runs?limit=20" | python -m json.tool
```

### API reference (all under `/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness (token-exempt). |
| GET | `/preflight` | Readiness checks (Docker, image, model keys, GitHub write). |
| POST | `/connect/github` | Store the fine-grained PAT (encrypted). |
| GET | `/repos` | List connected/accessible repos. |
| POST | `/projects/{owner}/{name}/sync` | Import a repo's issues. |
| GET | `/repos/{owner}/{name}/issues` | Board issue list. |
| GET | `/repos/{owner}/{name}/board/aggregate` | In-Progress / Needs-You / spent-today. |
| GET | `/issues/{owner}/{name}/{num}` | Single issue detail. |
| POST | `/issues/{owner}/{name}/{num}/agent-state` | Move an issue's agent-state label. |
| GET | `/workflows`, `/workflows/{workflow_id}` | Read-only workflow viewer. |
| POST | `/runs` | Launch a run (`201` + `run_id`). |
| GET | `/runs`, `/runs/{run_id}` | Run history / detail. |
| GET | `/runs/{run_id}/events` | SSE event stream (cookie auth). |
| POST | `/runs/{run_id}/answer` | Resolve a pause (HITL). |
| POST | `/runs/{run_id}/stop` · `/runs/{run_id}/retry` | Stop / retry. |
| GET | `/stats`, `/retry-queue` | Aggregate spend/tokens; pending retries. |

---

## Part E — A full sandboxed agent run (Docker)

A run only *executes* with Docker + the sandbox image + a model key.

### E.1 Build + scan + digest-pin the sandbox image

```bash
# From the repo root. The sandbox Dockerfile lives at dkmv/images/Dockerfile.
docker build -t dkmv-sandbox:build dkmv/images/

# Generate an SBOM + scan (Trivy or Docker Scout); fails on HIGH/CRITICAL.
bash platform/scripts/sbom-scan.sh dkmv-sandbox:build

# Resolve the immutable content digest and record it (pin by digest, never :latest).
eval "$(bash platform/scripts/sbom-scan.sh --print-digest-env dkmv-sandbox:build)"
echo "DKMV_IMAGE=$DKMV_IMAGE"      # → dkmv-sandbox@sha256:<digest>
```

### E.2 Run it

- **Local backend:** export `DKMV_IMAGE=dkmv-sandbox@sha256:<digest>` and
  `ANTHROPIC_API_KEY` (and/or `CODEX_API_KEY`) in Terminal 1 before `uvicorn`, ensure
  the Docker daemon is reachable, then launch a run from the UI/`curl`.
- **`docker compose up`** (backend + frontend + the brokered Docker socket proxy, with
  migrations run on start):

  ```bash
  cd platform
  cp .env.example .env       # fill DKMV_PLATFORM_TOKEN, ANTHROPIC_API_KEY, DKMV_IMAGE (digest), …
  docker compose up
  # backend :8787, frontend :5173 (loopback only)
  ```

`preflight` should now show **ready:true**. A launched run starts a sandbox container,
the agent works the issue, events stream live, and (on success) a PR is pushed.

### E.3 Sandbox isolation (gVisor)

Runs default to **gVisor (`runsc`)** (`SANDBOX_RUNTIME=runsc`). If `runsc` isn't
installed/registered with Docker, the executor **fails closed** with a
`WeakerIsolationError` rather than silently dropping to `runc`. On a trusted
single-user host you can opt into the weaker fallback (`SANDBOX_RUNTIME=runc`), but you
lose the primary kernel-isolation boundary against prompt-injected agent code — only do
this knowingly. See [`platform/README.md`](platform/README.md#sandbox-isolation-binding).

---

## Part F — Backup & restore

The single SQLite file is the source of truth for spend + audit. The backup is a
consistent `VACUUM INTO` snapshot (the helper is `platform/backend/app/db/backup.py`),
and the round-trip is covered by `tests/test_backup.py`. The exact snapshot + offline
restore procedure is in [`platform/docs/setup.md`](platform/docs/setup.md#8-backup--restore-65-ac-14).

---

## Part G — Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `401 unauthorized` on every API call | Missing/incorrect token. Send `Authorization: Bearer $DKMV_PLATFORM_TOKEN`; ensure the frontend `.env` `DKMV_PLATFORM_TOKEN` matches the backend's. |
| `403 forbidden` | Foreign `Host`/`Origin`. Use `http://127.0.0.1:…` (not a LAN IP or hostname); the Vite proxy is configured to preserve the loopback Host. |
| `no such table: runs` / DB errors on first request | You skipped `alembic upgrade head`. Run it once against a fresh DB (compose does this automatically). |
| `preflight` shows `ready:false` | Expected without Docker/sandbox-image/model-key. Build the image (Part E) + set a model key for real runs; the UI/API still work for everything up to executing a run. |
| `docker compose up` complains about the image / a run can't pull the sandbox | The default `DKMV_IMAGE` is an all-zero **placeholder** digest. Build + resolve the real digest (Part E.1) and set it in `platform/.env`. |
| A connected GitHub PAT stops working after a backend restart | `DKMV_SECRET_KEY` was unset, so a fresh dev key was generated and the encrypted PAT can't be decrypted. Set a stable `DKMV_SECRET_KEY` (Part B.1) or just re-Connect. |
| `WeakerIsolationError` at run start | `runsc` (gVisor) isn't available. Install + register gVisor as a Docker runtime, or opt into the weaker fallback knowingly (Part E.3). |
| Frontend loads but API calls 404 / fail | The Vite proxy didn't pick up `.env`. Restart `npm run dev` after writing `platform/frontend/.env`; confirm `DKMV_BACKEND_ORIGIN` points at the running backend. |
| Port already in use | Change the backend port (`--port`) + `DKMV_BACKEND_ORIGIN`, or the Vite port (`server.port` in `vite.config.ts`). |

---

## Reference

- **Config / env surface:** [`platform/.env.example`](platform/.env.example) +
  the tables in [`platform/README.md`](platform/README.md#configuration-prd-88-env-surface).
- **Deploy detail (image build, brokered socket, gVisor, backup):**
  [`platform/docs/setup.md`](platform/docs/setup.md).
- **§13 acceptance matrix (ship sign-off):**
  [`platform/docs/acceptance_matrix.md`](platform/docs/acceptance_matrix.md).
- **Quality gates (run before any change):**
  - Backend: `cd platform/backend && ruff check . && mypy app && pytest -q`
  - Frontend: `cd platform/frontend && npx tsc --noEmit && npx vitest run`
