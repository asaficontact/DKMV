# ADR-P009: Capability-aware cost enforcement (Codex = timeout-only)

## Status

Accepted

## Context

The platform promises hard budget caps to a cost-conscious solo dev. But the Codex adapter reports `total_cost_usd = 0.0` and `supports_budget()`/`supports_max_turns()` are both `false` — and Codex is the **default agent for the `dev` and `docs` built-ins** (with `dev` the for-each `$10/phase × N` workhorse). Claude supports all caps.

## Decision

Enforcement **branches on the adapter capability**, not a blanket assumption:
- **Claude** (`supports_budget`/`supports_max_turns` = true): enforce `max_budget_usd` + `max_turns` + `timeout_minutes` as hard caps; optional soft-threshold pause-for-approval.
- **Codex** (both false): `timeout_minutes` is the **only** runtime guardrail. The launch UI states "time-bounded, not cost-bounded," the API **rejects** `max_budget_usd`/`max_turns` for Codex (`400 unsupported_for_agent`), Codex workflows default to a **tighter** timeout, and Codex cost renders "—" and is **excluded** from spend aggregates (tokens still count).
- Aggregate **daily-spend admission** (ADR-P002/§8.2) bounds total spend across runs regardless of agent.

## Consequences

- + Honest cost story; no false "hard cap" promise the product can't keep for Codex.
- − A runaway Codex `dev` run is bounded only by wall-clock — mitigated by a tighter default timeout + daily-spend admission.
- Implication: consider an engine ask for a Codex cost signal / turn cap (§11.7).

## PRD Reference

NFR-COST-1, §7.2 footnotes, FR-06-1a, R-10/R-16, §8.10.
