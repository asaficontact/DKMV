# DKMV Init v1 User Stories

## Summary

8 user stories across 4 categories, derived from PRD sections 2, 3, 6, and 9.

## Traceability Matrix

| US ID | Title | Feature | Task(s) | Status |
|-------|-------|---------|---------|--------|
| US-01 | First-time setup | F1, F2 | T200-T206, T210-T219 | [ ] |
| US-02 | Running without init | F1, F5 | T205, T240-T241 | [ ] |
| US-03 | Custom component registration | F3 | T220-T226 | [ ] |
| US-04 | Reinitializing | F2 | T217 | [ ] |
| US-05 | Project-scoped run history | F1, F5 | T203, T242-T243 | [ ] |
| US-06 | Listing available components | F3 | T222 | [ ] |
| US-07 | Non-interactive init (CI/CD) | F2, F5 | T216, T241 | [ ] |
| US-08 | Working from subdirectories | F1, F5 | T201, T204, T240 | [ ] |

---

## Stories by Category

### Setup & Configuration (US-01, US-02, US-04)

#### US-01: First-time Setup

> As a developer using DKMV for the first time, I want to run `dkmv init` in my project directory so that DKMV is configured with my repo, credentials, and defaults without manual file editing.

**Acceptance Criteria:**
- [ ] `dkmv init` auto-detects repo URL from `git remote`
- [ ] `dkmv init` discovers existing API keys from env vars or `.env`
- [ ] `dkmv init` discovers GitHub token from `gh auth token`
- [ ] `.dkmv/config.json` is created with detected values
- [ ] `.dkmv/` is added to `.gitignore`
- [ ] After init, `dkmv run dev --var prd_path=prd.md` works without `--repo`

**Feature:** F1, F2 | **Tasks:** T200-T206, T210-T219 | **Priority:** Must-have

---

#### US-02: Running Without Init

> As a developer who hasn't initialized DKMV, I want to still run commands with explicit flags so that DKMV works for one-off use without commitment.

**Acceptance Criteria:**
- [ ] `dkmv run dev --repo https://... --var prd_path=prd.md` works without `.dkmv/`
- [ ] Error message when `--repo` is missing suggests `dkmv init`
- [ ] No command crashes when `.dkmv/` doesn't exist

**Feature:** F1, F5 | **Tasks:** T205, T240-T241 | **Priority:** Must-have

---

#### US-04: Reinitializing

> As a developer who needs to update their DKMV config, I want to re-run `dkmv init` so that I can update my repo URL or re-detect credentials without losing run history.

**Acceptance Criteria:**
- [ ] `dkmv init` in an already-initialized project shows current config
- [ ] Asks for confirmation before reinitializing
- [ ] Preserves `.dkmv/runs/` and `.dkmv/components.json`
- [ ] Only regenerates `.dkmv/config.json`

**Feature:** F2 | **Tasks:** T217 | **Priority:** Should-have

---

### Component Management (US-03, US-06)

#### US-03: Custom Component Registration

> As a developer with custom components, I want to register them by name so that I can use short names instead of paths.

**Acceptance Criteria:**
- [ ] `dkmv register strict-judge ./components/strict-judge` adds to registry
- [ ] `dkmv run strict-judge --var prd_path=prd.md` resolves from registry
- [ ] `dkmv components` shows both built-in and registered components
- [ ] `dkmv unregister strict-judge` removes from registry
- [ ] Registering a built-in name (`dev`, `qa`, `judge`, `docs`) fails with error

**Feature:** F3 | **Tasks:** T220-T226 | **Priority:** Should-have

---

#### US-06: Listing Available Components

> As a developer, I want to see all available components so that I know what I can run.

**Acceptance Criteria:**
- [ ] `dkmv components` works without init (shows only built-ins)
- [ ] With init, shows built-in + registered components
- [ ] Shows task count for each component
- [ ] Clearly distinguishes built-in from custom

**Feature:** F3 | **Tasks:** T222 | **Priority:** Should-have

---

### CI/CD & Advanced Usage (US-07, US-08)

#### US-07: Non-interactive Init (CI/CD)

> As a CI/CD engineer, I want to run `dkmv init --yes --repo https://...` so that init works in non-interactive environments.

**Acceptance Criteria:**
- [ ] `--yes` skips all prompts
- [ ] `--repo` provides the repo URL when git remote isn't available
- [ ] Exits with error if required values can't be auto-detected
- [ ] No TTY required

**Feature:** F2, F5 | **Tasks:** T216, T241 | **Priority:** Should-have

---

#### US-08: Working from Subdirectories

> As a developer, I want to run DKMV commands from a subdirectory of my project so that I don't have to be in the project root.

**Acceptance Criteria:**
- [ ] `find_project_root()` walks up from CWD to find `.dkmv/config.json`
- [ ] `dkmv run dev --var prd_path=prd.md` works from `src/` subdirectory
- [ ] `dkmv runs` works from any subdirectory

**Feature:** F1, F5 | **Tasks:** T201, T204, T240 | **Priority:** Must-have

---

### Run History (US-05)

#### US-05: Project-scoped Run History

> As a developer working on multiple projects, I want run history to be project-scoped so that `dkmv runs` shows only this project's runs.

**Acceptance Criteria:**
- [ ] After init, runs are stored in `.dkmv/runs/`
- [ ] `dkmv runs` shows only runs from `.dkmv/runs/`
- [ ] Without init, runs go to `./outputs/runs/` (backward compatible)

**Feature:** F1, F5 | **Tasks:** T203, T242-T243 | **Priority:** Should-have
