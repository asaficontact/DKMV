# DKMV Platform v1 — §13 Acceptance Matrix (ship sign-off)

This is the v1 ship-gate sign-off (PRD §13, slice 5.4 / AC-17). The end-to-end
acceptance suite lives in `platform/backend/tests/e2e/` (one module per AT) and is
run by:

```bash
cd platform/backend && pytest -q tests/e2e
```

## Live vs Docker-gated

The brief's honest split (no faking): the **in-process** ATs run for REAL against
the FastAPI app + the real platform components + fakes (no Docker / engine). The
ATs that need a **live gVisor container + real network egress** assert the
*configuration* + the *Python-level enforcement* in-process, and gate the
live-container assertions behind a Docker/runsc-availability `skipif`
(`tests/e2e/gating.py`) that **self-skips** when the prerequisite is absent —
reported as SKIPPED, never faked, never silently passed. Set `DKMV_E2E_LIVE=1` on a
host with Docker + runsc to run the live halves.

| AT | Module | Runs | What it asserts |
|---|---|---|---|
| **AT-Connect** | `test_at_api_flows.py` | **LIVE (in-process)** | `POST /connect/github` echoes the four required permissions; PAT not leaked; behind the INV-1 token gate. |
| **AT-Board** | `test_at_api_flows.py` | **LIVE (in-process)** | `GET /board/aggregate` In-Progress / Needs-You split (§5.3.1 authority). |
| **AT-Launch** | `test_at_api_flows.py` | **LIVE (in-process)** | `POST /runs` returns a platform UUID + moves the issue to `agent:in-progress` (INV-11); duplicate dispatch → `409` (INV-5 claim-lock). |
| **AT-Live** | `test_at_live.py` | **LIVE (in-process)** | Segment-sum cost climbs to the run total across stages with **no reset / no double-count** (INV-7); SSE replay no-gaps-no-dups across the backlog→live handoff (INV-2); SSE token rides the HttpOnly `SameSite=Strict` cookie, **never the URL** (INV-2). |
| **AT-HITL** | `test_at_hitl.py` | **LIVE (in-process)** | A pause resolves **exactly once** (rowcount guard — concurrent answers → one winner); a pause **releases** the concurrency slot + resume re-acquires; no phantom capacity (INV-9). |
| **AT-Recovery** | `test_at_recovery.py` | **LIVE (in-process)** | Boot recovery kills the orphan (reaper seam) + marks `interrupted` + offers `start_task` from the pushed boundary; the terminal run is untouched (no duplicate PR / re-launch); **no re-attach symbol** exists (INV-10). |
| **AT-History** | `test_at_api_flows.py` | **LIVE (in-process)** | `GET /runs` lists finished runs; cost is the **segment-sum**, not a naive sum (INV-7). |
| **AT-Workflows** | `test_at_api_flows.py` | **LIVE (in-process)** | `GET /workflows` surfaces the read-only built-in pipelines; no create/update route (ADR-P010). |
| **AT-Concurrency** | `test_at_concurrency.py` | **LIVE (in-process)** | Only N=`MAX_CONCURRENT_RUNS` run at once, the rest queue + drain; a run over `HOST_MEMORY_BUDGET` / `DAILY_SPEND_CAP` is admission-**denied + re-queued** (not dropped); Codex $0 spend never trips the cap (INV-8). |
| **AT-CodexCost** | `test_at_api_flows.py` | **LIVE (in-process)** | A Codex run's cost renders **null ("—"), not `$0.00`**, is **excluded from spend**, and its **tokens still count** (FR-06-1a / INV-8). |
| **AT-Isolation** | `test_at_isolation.py` | **LIVE (in-process) + Docker-gated** | In-process (always): `SANDBOX_RUNTIME=runsc` resolves + the executor emits `--runtime=runsc` + egress-confinement args; the egress policy **denies** a non-allowlisted host + audits it; the repo-scoped token **refuses** a foreign-repo push (INV-3/4). Docker-gated (self-skips): runsc registered with the daemon; egress-deny observed over the wire. |
| **AT-PromptInjection** | `test_at_prompt_injection.py` | **LIVE (in-process)** | A run with an **injected issue body** still pauses for human approval before the PR push (the NFR-SEC-5 gate fires via the F9 pause primitive); the push is unreachable until the decision resolves (AC-16). |
| **AT-Security** (cross-cutting) | `test_at_isolation.py` | **LIVE (in-process)** | No secret reaches the append-only `events` table or the audit log — redact-before-persist covers shapes + the platform's own values (INV-4). |

## Docker-gated assertions (self-skip when the prerequisite is absent)

| Gated assertion | Gate | Covered in-process by |
|---|---|---|
| runsc runtime registered with the local Docker daemon | `requires_runsc` (`DKMV_E2E_LIVE=1` + runsc registered) | `SANDBOX_RUNTIME=runsc` resolves + `--runtime=runsc` emitted (always). |
| egress-deny observed over the wire (live exfil attempt blocked) | `requires_live_sandbox` (`DKMV_E2E_LIVE=1` + reachable daemon) | the egress policy's default-deny decision + audit line (always). |

These are reported as **SKIPPED** (with a clear reason) when Docker/runsc/opt-in is
absent — they are never faked and never silently passed.

## Sign-off

- The full §13 in-process AT matrix **passes** (`pytest -q tests/e2e`): every AT
  above runs for real except the two Docker-gated halves, which self-skip.
- The backup round-trip **passes** (`pytest -q tests/test_backup.py`): snapshot →
  restore → row counts + the Codex-excluded spend rollup MATCH (AC-14).
- The sandbox image is **digest-pinned** (not `:latest`) in `docker-compose.yml`
  and an **SBOM scan** step (`scripts/sbom-scan.sh`) is wired into the build (AC-13).
- The security INVs hold: gVisor runsc + the default-on egress allowlist in config
  (INV-3); redact-before-persist over events/logs/audit (INV-4); the PR-push gate
  fires on injected input (NFR-SEC-5); no `SKIP LOCKED`/`FOR UPDATE`; no inbound
  webhook receiver (App/webhooks deferred, ADR-P004).

**v1 ship gate: GREEN** (subject to the gates above passing in CI + the human merge
review).
