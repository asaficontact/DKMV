---
name: dkmvp-github-control-plane
description: The DKMV Platform GitHub control-plane playbook — fine-grained PAT auth, the agent:* label state machine via set_agent_state (PUT replace-all), the run-vs-label authority rule, the serialized write-queue, and rate-limit handling. Use for GitHub slices (1.1–1.3) and reconcile label changes (3.3).
allowed-tools: Read, Grep, Glob
---

DKMV Platform GitHub playbook (PRD §8.1, §5.3.1; ADR-P004). v1 = fine-grained PAT + poll-only (App/webhooks deferred).

**Auth.** `GitHubClient` wraps a fine-grained PAT scoped to ONE repo with `issues:write`, `pull_requests:write`, `contents:write`, `metadata:read`. Preflight verifies **effective write permission** on the selected repo (not just token presence). The PAT lives in the `SecretStore`, never logged.

**Label state machine (INV-11).** `agent:*` labels = `queued|in-progress|paused|review`, **single-occupancy** (at most one per issue). ALL transitions go through `set_agent_state(repo, num, target | none)` implemented with GitHub **`PUT /repos/{o}/{r}/issues/{num}/labels`** (replace-all over the `agent:*` set, preserving non-agent labels). The fictional `PATCH .../label` does NOT exist — never write it. Precedence if multiple `agent:*` are seen: `in-progress > paused > review > queued`. Create the four labels on connect if absent.

**Authority rule.** For an issue with an **active run**, the **DB `runs` row is authoritative** for board state; labels are advisory while a run is live. The label→column derivation (§5.3.1) governs only issues WITHOUT an active run. A human label edit on a running issue is handled by reconciliation, not by blindly trusting the label.

**State-machine completeness.** In Review→Done = `pull_request` merged (poll the PR `merged` field) + issue↔PR linkage (`runs.pr_num` / "Closes #N"); on merge strip `agent:review`. `issues.closed`→Done (cancel any live run); `issues.reopened`→out of Done. A failed run is demoted off `agent:in-progress` (to `agent:queued` if it will retry, else Backlog) — the board never strands a failed issue in In Progress.

**Write-queue + rate limits.** ALL mutating GitHub calls (label/branch/PR/comment) route through a **single serialized, token-bucket-paced write-queue** to respect the content-creation **secondary limit (~80/min, 500/hr)** which returns 403 + `Retry-After` and is NOT reflected in `X-RateLimit-Remaining`. Handle 403-secondary distinctly from primary limits; surface `X-RateLimit-*` headroom in the UI. Board reads use **GraphQL** (paginated, `since`/cursor, Done window) with self-hashed caching (GraphQL has no ETag); REST polls use conditional requests.

The acceptance check: `grep -rni "PATCH[^\n]*/label" platform` is empty; `set_agent_state`/`PUT .../labels` present; every mutating call goes through the write-queue.
