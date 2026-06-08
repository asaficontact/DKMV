# ADR-P010: Workflows screen read-only in v1 (authoring → v1.1)

## Status

Accepted

## Context

Screen 07 in the design is a full form→YAML workflow/component builder (defaults, component inputs, ordered tasks, per-task IO, a pause-question/options sub-builder, for-each UX). It is the highest-drift, lowest-relative-value screen for a solo dev who already has five working built-ins, and it is spec-only prose with no `builder.jsx` prototype (R-12).

## Decision

v1 ships a **read-only Workflows viewer**: list built-in + registered components (`list_components`), show each component's pipeline summary (ordered stages, per-stage budget, pause points, est. total) and a read-only "compiles to YAML" view. Editing is disabled with a "Workflow authoring coming in v1.1 — edit the YAML directly for now" note. Custom components authored on disk + `ComponentRegistry.register` still appear and are runnable. **Full form-based authoring is deferred to v1.1**, gated on a `builder.jsx` design spike.

## Consequences

- + Removes the riskiest UI from v1; users keep full power via on-disk YAML + the registry.
- − No in-app workflow creation in v1.
- Implication: the read endpoints (`GET /workflows`, `GET /workflows/{id}`) are v1; write endpoints (`POST/PUT /workflows`) are v1.1.

## PRD Reference

§5.8 (FR-07-1v), G7, N7, R-12, §12 (M4).
