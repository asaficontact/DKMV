---
name: dkmvp-design-system-applier
description: Enforces the DKMV Platform design system — ported tokens from styles.css, the semantic state palette, dark/indigo default theme, and accessibility (icon+label state, AA contrast). Use when implementing or reviewing any platform/frontend UI slice. Returns the token rules and verbatim values to apply.
allowed-tools: Read, Grep, Glob
---

DKMV Platform frontend design playbook. Stack: React 18 + Vite + TypeScript. **Port** tokens from `docs/design_docs/platform/styles.css` into `platform/frontend/src` (the prototype is LOCKED — read it, don't edit it).

**No hardcoded hex (INV-14).** Colors come from CSS variables / token constants only. The no-hardcoded-hex hook blocks `#rrggbb` in `platform/frontend/src/**` outside the tokens file. Port these verbatim:

- Theme default: `data-mode="dark" data-theme="indigo"` (persist `localStorage` `dkmv-mode`/`dkmv-skin`). Indigo accent `#7b7bf5` (light `#5b54e0`). Six skins selectable.
- Semantic state palette: `--st-queued #94a3b8`, `--st-running #4f8cff`, `--st-paused #f5a623`, `--st-review #a78bfa`, `--st-done #34c98a`, `--st-failed #f2666b`, `--st-cancel #7c7a82`. Running/paused dots pulse.
- GitHub label colors (from `data.jsx LABELS`): bug `#f2666b`, backend `#4f8cff`, frontend `#a78bfa`, enhancement `#34c98a`, auth `#f5a623`, docs `#7c7a82`, infra `#22b8cf`, good-first-issue `#34c98a`.
- Type: `--font-ui "Plus Jakarta Sans"`; `--font-mono "JetBrains Mono"` for code/run-ids/numbers (`tnum`). Radii 8/12/16/22/pill. Easing `cubic-bezier(.4,0,.2,1)` / `cubic-bezier(.16,1,.3,1)`.

**State mapping (one palette everywhere).** Use the `STATE_OF`/`STATE_LABEL` mapping from `components.jsx`: `progress→running, needsyou→paused, review→review, done|completed→done, failed|timed_out→failed, cancelled|pending|interrupted→cancel`. `timed_out` renders with the failed palette + "timed out" label; `interrupted` (platform-only) renders with the cancel palette.

**Accessibility (NFR-A11Y-1).** State is conveyed by **icon + text label**, never color alone. AA contrast in dark and light. Board and forms are keyboard-navigable.

**Fidelity.** Build spec-only screens (Board, chrome, Workflows viewer) to `dkmv_dashboard_design_prompt.md` + the PDF; build implemented screens to their JSX (`connect/issue/run/history/settings.jsx`). Pause-card options use the **engine-authoritative** `{value,label,description?}` shape, NOT the `data.jsx` `{label,description}` mock.

**Quality gate:** `cd platform/frontend && npx tsc --noEmit && npx vitest run`; no `as any` without `// DKMVP-ESCAPE: <reason>`.
