# Append to the project-root `CLAUDE.md`

> Pre-flight copies this block into the repo-root `CLAUDE.md` (the DKMV repo's memory file). Keep it short — every byte is in every session's context.

## DKMV Platform conventions

The DKMV **Platform** (the web control plane) is built in `platform/` and is a **separate concern from the `dkmv/` engine**. The engine is **locked** — consume it via `dkmv.runtime.EmbeddedRuntime` in-process; never shell its CLI; never edit `dkmv/**` (engine gaps are PRD §11 asks).

- **Source of truth:** `docs/design_docs/platform/PRD_dkmv_platform_v1.md` (LOCKED during implementation — edits require `PRD_UNLOCK=1`). Design prototype + tokens in `docs/design_docs/platform/` (LOCKED — `DESIGN_UNLOCK=1`).
- **Implementation plan:** `docs/implementation/platform/` — start at `README.md`, then `CLAUDE.md`, the phase briefs `phase_*.md`, and `_conventions.md` (system invariants INV-1..15).
- **Stack:** `platform/backend/` = Python 3.12 / FastAPI / SQLite(WAL)+Alembic / sse-starlette / in-process asyncio (ruff + mypy + pytest). `platform/frontend/` = React 18 + Vite + TS (tsc + vitest), design tokens only (no hardcoded hex).
- **Quality gates (every slice):** backend `ruff check . && mypy app && pytest -q`; frontend `npx tsc --noEmit && npx vitest run`.
- **Merge authority:** every phase ends in a PR Tawab reviews and merges. No auto-merge. Serialized PR mode (one open PR at a time).
- **Hooks** enforce the locks + typecheck + no-hardcoded-hex (see `.claude/settings.json`). `.claude/worktrees/` is gitignored.
