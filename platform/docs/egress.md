# Sandbox isolation + egress enforcement (G1/G2) — operator runbook

This documents how the DKMV Platform enforces sandbox isolation (gVisor) and a
network-level egress allowlist, and **how the operator validates it live** on a
real Docker + gVisor host. The full chain (gVisor `runsc` + the `dkmv-egress`
internal network + the egress proxy + pinned DNS) can only be validated on such a
host; the platform/engine pieces are unit-tested, but the live network behavior
is **operator-validated** (it is not asserted by CI here).

## What enforces what

| Layer | Mechanism | Setting |
| --- | --- | --- |
| Kernel isolation | gVisor `runsc` via `--runtime=runsc` on **every** sandbox (engine §11.3 passthrough), plus a fail-closed boot/launch check | `SANDBOX_RUNTIME=runsc`, `ALLOW_WEAKER_ISOLATION` |
| Egress allowlist (network) | `dkmv-egress` Docker network is `internal: true` → **no internet route**; the only way out is the `egress-proxy` | `EGRESS_NETWORK=dkmv-egress` |
| Egress allowlist (filter) | `egress-proxy` (Squid) CONNECT-tunnels HTTPS only to allowlisted domains; denies all else | `platform/egress/squid.conf`, `EGRESS_ALLOWLIST` |
| DNS on the custom net | sandbox `--dns=<proxy/resolver>` (gVisor's embedded 127.0.0.11 breaks on custom networks) | `SANDBOX_DNS` |
| Credential hygiene | GitHub PAT delivered as a read-only file mount at `/run/secrets/github_token`, not an env var | `SECRET_FILE_MOUNT=true` |

The **enforcement is the `internal: true` network**, not the proxy env vars: a
prompt-injected agent that ignores `HTTP(S)_PROXY` still cannot reach a
non-allowlisted host, because the network it is on has no route off-host except
through the proxy.

## Fail-closed gVisor gate (G1)

When `SANDBOX_RUNTIME=runsc` but the Docker daemon has **no `runsc` runtime
registered**, the platform refuses to dispatch:

- `GET /api/v1/preflight` returns a failing `sandbox_runtime` check and lists
  "Sandbox isolation (gVisor)" as a blocker (`ready: false`).
- `POST /runs` (and the orchestrator/retry redispatch) raise
  `503 sandbox_isolation_unavailable` **before** claiming the run row — a run can
  never start under bare `runc` when gVisor was required.

To proceed anyway on a host without gVisor (trusted single-user host only), set
`ALLOW_WEAKER_ISOLATION=1`. A loud warning is logged on every launch.

## Installing gVisor on the host

```sh
# Debian/Ubuntu — see https://gvisor.dev/docs/user_guide/install/
( set -e
  curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list
  sudo apt-get update && sudo apt-get install -y runsc
  sudo runsc install            # registers runsc with dockerd
  sudo systemctl reload docker )

# Verify the daemon now lists runsc:
docker info --format '{{range $r, $_ := .Runtimes}}{{$r}} {{end}}'
# → expect to see: runc runsc ...
```

The platform's preflight runs the same `docker info` probe; once `runsc` is
listed, the `sandbox_runtime` check turns green.

## Wiring DNS (`SANDBOX_DNS`)

On the `dkmv-egress` custom network under gVisor, the embedded resolver
(127.0.0.11) does not work, so the sandbox must be given an explicit `--dns`.
Point it at the egress-proxy (which can resolve + filter) or a resolver reachable
on `dkmv-egress`:

```sh
# Find the egress-proxy's IP on the dkmv-egress network after `compose up`:
docker inspect -f '{{(index .NetworkSettings.Networks "dkmv-egress").IPAddress}}' \
  "$(docker compose -f platform/docker-compose.yml ps -q egress-proxy)"
# Export it (the backend threads it through as --dns):
export SANDBOX_DNS=<that-ip>
```

## Live validation (operator — Docker + gVisor host required)

This is the `DKMV_E2E_LIVE`-style smoke test. **Not run by CI**; run it on the
deployment host after `docker compose up`.

1. **gVisor active.** Launch a run; confirm the sandbox container runs under runsc:
   ```sh
   docker inspect -f '{{.HostConfig.Runtime}}' <sandbox-container>
   # → runsc
   ```

2. **Allowlisted host reachable.** Inside the sandbox network, an allowlisted host
   succeeds (the run itself cloning from github.com is the positive case):
   ```sh
   docker run --rm --network dkmv-egress --dns "$SANDBOX_DNS" curlimages/curl:8.8.0 \
     -sS -o /dev/null -w '%{http_code}\n' https://api.github.com
   # → 200 (or 401/403 from GitHub — but it CONNECTED)
   ```

3. **Non-allowlisted host BLOCKED (the key assertion).**
   ```sh
   docker run --rm --network dkmv-egress --dns "$SANDBOX_DNS" curlimages/curl:8.8.0 \
     -sS --max-time 10 https://example.com ; echo "exit=$?"
   # → connection refused / 403 from the proxy / timeout — NON-ZERO exit.
   #   A 200 here is a FAILURE: the allowlist is not being enforced.
   ```

4. **No internet route without the proxy.** Confirm the network itself is the
   boundary (a direct connection, bypassing any proxy env var, must fail):
   ```sh
   docker run --rm --network dkmv-egress alpine:3.20 \
     sh -c 'wget -T 5 -qO- https://example.com; echo exit=$?'
   # → non-zero (no route off the internal network)
   ```

5. **PAT not in `docker inspect` (G2).** With `SECRET_FILE_MOUNT=true`:
   ```sh
   docker inspect <sandbox-container> | grep -i GITHUB_TOKEN
   # → no match (the token is a file mount, not an env var)
   docker inspect -f '{{json .Mounts}}' <sandbox-container> | grep github_token
   # → /run/secrets/github_token (read-only)
   ```

If steps 3 and 4 do not block, the egress allowlist is **not** enforced — recheck
that `dkmv-egress` is `internal: true`, that the sandbox actually joined it
(`--network=dkmv-egress`), and that `squid.conf` mounted into the proxy.

## Keeping the allowlist in sync

`platform/egress/squid.conf` (the enforced filter) and the `EGRESS_ALLOWLIST`
setting (what preflight reports) describe the same intended set
(`.github.com`, `.githubusercontent.com`, `api.anthropic.com`, `api.openai.com`).
When you add a model/Git host, update **both**.
