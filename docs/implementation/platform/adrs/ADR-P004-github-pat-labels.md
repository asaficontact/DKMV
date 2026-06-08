# ADR-P004: Fine-grained PAT + poll-only + labels-as-control-plane (App/webhooks deferred)

## Status

Accepted

## Context

The platform connects to one GitHub repo, reads issues, tracks agent work state, and creates branches/PRs. The persona is solo, single-user, single-repo, self-hosted behind NAT. A GitHub App brings a bot identity, short-lived per-install tokens, and webhooks — but also a hosted App manifest, private key, installation flow, and a public webhook endpoint (smee/tunnel, not production-grade behind NAT).

## Decision

v1 uses a **fine-grained Personal Access Token** (default and only required auth), scoped to the single repo with `issues:write`, `pull_requests:write`, `contents:write`, `metadata:read`. Sync is **poll-only** (a single GraphQL board read per tick, paginated, with a persisted cursor). State is GitHub **`agent:*` labels** (`queued|in-progress|paused|review`) with a **single-occupancy invariant** set via `PUT .../labels` replace-all behind a `set_agent_state` primitive; for an active run the **DB row is authoritative** over the label. All mutating calls go through a serialized, token-bucket-paced write-queue (80/min secondary-limit). **The GitHub App + webhooks are deferred to the scaling/multi-tenant phase.** Everything sits behind a `GitHubClient` interface so the App is additive. (Resolves OQ-1.)

## Consequences

- + Paste-and-go; works behind NAT; no private-key/installation/webhook complexity for the solo persona.
- − No real-time push (poll latency); no built-in bot identity; per-user 5k req/hr (fine at solo scale).
- Implication: build state-machine completeness (In Review→Done on PR merge, closed/reopened, failed-run demotion) and echo-safety into the poll path; the App earns its keep only at multi-tenant.

## PRD Reference

§8.1, §5.3.1, OQ-1.
