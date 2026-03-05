# CLAUDE.md Setup — 3-Layer Context Injection

How DKMV assembles the `.claude/CLAUDE.md` file that Claude Code reads inside each sandbox container.

## Overview

Every task run writes a `CLAUDE.md` to `/home/dkmv/workspace/.claude/CLAUDE.md` before invoking Claude Code. The file is assembled from 3 layers, separated by `---` dividers:

```
Layer 1: System Context       (always present, identical for all tasks)
---
Layer 2: Component agent_md   (optional, from component.yaml)
---
Layer 3: Task Instructions     (optional, from task YAML's `instructions` field)
```

## Assembly Code

**File:** `dkmv/tasks/runner.py`, method `_write_instructions()` (lines 81-94)

```python
async def _write_instructions(
    self,
    task: TaskDefinition,
    session: SandboxSession,
    component_agent_md: str | None = None,
) -> None:
    layers: list[str] = [DKMV_SYSTEM_CONTEXT]
    if component_agent_md:
        layers.append(component_agent_md)
    if task.instructions:
        layers.append(f"## Task-Specific Instructions\n\n{task.instructions}")
    content = "\n\n---\n\n".join(layers) + "\n"
    await self._sandbox.execute(session, f"mkdir -p {WORKSPACE_DIR}/.claude")
    await self._sandbox.write_file(session, f"{WORKSPACE_DIR}/.claude/CLAUDE.md", content)
```

Key behavior:
- Called once per task, **before** Claude Code is invoked
- Overwrites the previous task's CLAUDE.md (each task gets a fresh file)
- The `component_agent_md` is passed through from `ComponentRunner` → `TaskRunner`
- Empty/None layers are skipped (no empty `---` blocks)

## Layer 1: System Context

**Source:** `dkmv/tasks/system_context.py` — `DKMV_SYSTEM_CONTEXT`

Present for **every** task across **all** components. Defines the agent's identity and universal rules.

### Current Content

```
# DKMV Agent

You are a DKMV agent running inside a sandboxed Docker container. You are part
of a team of agents, each handling a specific task in a component pipeline. Prior
tasks may have produced outputs that inform your work; subsequent tasks will
build on yours.

## Core Rules

1. **Work within the workspace.** All code changes happen in `/home/dkmv/workspace/`.
2. **Check `.agent/` for context.** This directory contains inputs (PRDs, design
   docs) and outputs from prior tasks. Review it to understand what came before you.
3. **Follow your task instructions.** Your specific task is defined in the prompt.
   The CLAUDE.md layers below provide component-wide and task-specific rules.
4. **Follow existing conventions.** Read the codebase before writing. Match patterns
   and style.
5. **Make reasonable decisions.** When facing ambiguity, choose the pragmatic path
   and document your assumption in the relevant output file.
6. **Respect boundaries.** Only modify files relevant to your task. Your work feeds
   into the next task — keep scope tight.
7. **Commit meaningful changes.** Use git with conventional commit messages when your
   task involves code changes.

## Environment

- **Workspace:** `/home/dkmv/workspace/`
- **Agent directory:** `/home/dkmv/workspace/.agent/` (shared between tasks, gitignored)
- **Git:** Pre-configured with auth. You can commit and push.
- **Tools:** Standard Linux tools, Python, Node.js are available.
- **Constraints:** You have limited turns and budget. Be efficient.
```

## Layer 2: Component `agent_md`

**Source:** `component.yaml` → `agent_md` field, loaded by `TaskLoader.load_manifest()`, passed via `ComponentRunner` → `TaskRunner` as `component_agent_md`.

Present for **all tasks within a component** that defines it. Provides component-wide context like workspace layout, shared rules, and conventions.

### Current State Per Component

| Component | Has `agent_md`? | Content Summary |
|-----------|----------------|-----------------|
| **dev**   | No             | — |
| **qa**    | No             | — |
| **judge** | No             | — |
| **docs**  | No             | — |
| **plan**  | **Yes**        | Workspace layout + planning rules |

Only `plan` uses this layer. The other 4 components go directly from Layer 1 to Layer 3.

### Plan Component `agent_md`

```
## Workspace Layout

- `.agent/prd.md` — The PRD (source of truth, read-only)
- `.agent/design_docs/` — Design documents (if provided)
- `.agent/analysis.json` — PRD analysis (produced by task 1, includes `output_dir`)
- `docs/implementation/<name>/` — Implementation output directory (determined by task 1)

## Planning Rules

- Do NOT write any implementation code
- Task 1 chooses the output subdirectory name and records it as `output_dir` in `.agent/analysis.json`
- Tasks 2-5 read `output_dir` from `.agent/analysis.json` to find the output directory
- Reference PRD sections, do not copy verbatim
- Every task must be independently testable
- Every phase must end with verifiable functionality
```

### Assessment Notes

- `dev`, `qa`, `judge`, and `docs` have no component-level context. Their agents don't know the workspace layout (e.g., where the PRD lives, what `.agent/` contains).
- The `dev` component is the most obvious candidate for an `agent_md` — it has 2 tasks that share the PRD and feedback context.
- `qa` and `judge` could benefit from knowing "the PRD is at `.agent/prd.md`" at the component level rather than repeating it in each task prompt.

## Layer 3: Task `instructions`

**Source:** Task YAML file → `instructions` field, loaded by `TaskLoader.load()` into `TaskDefinition.instructions`.

Injected with the heading `## Task-Specific Instructions` prepended. Unique per task — defines behavioral constraints, output expectations, and guardrails.

### Current Content Per Task

#### dev/01-plan.yaml

```
## Planning Rules
- Output the plan to `.agent/plan.md`
- Do NOT write any implementation code in this phase
- Do NOT modify any existing files
- Include sections for: architecture, file changes, dependencies, test strategy
- If design docs are available at `.agent/design_docs/`, incorporate them
- If feedback is available at `.agent/feedback.json`, address every issue raised
```

#### dev/02-implement.yaml

```
## Implementation Rules
- Follow the plan at `.agent/plan.md` precisely
- Write tests for all new public interfaces
- Run the full test suite before finishing — all tests must pass
- Follow existing code style and patterns in the codebase
- Commit with meaningful conventional commit messages using `[dkmv-dev]` suffix
- Do not push to main/master directly
- Do not modify unrelated files
```

#### qa/01-evaluate.yaml

```
## QA Agent Rules
- You are evaluating an implementation — do NOT modify any source code
- Be thorough but fair in your evaluation
- Provide specific file and line references for any issues found
- The QA report must be valid JSON at `.agent/qa_report.json`
- Pay special attention to the "## Evaluation Criteria" section in the PRD
- Run the FULL test suite, not just individual files
```

#### judge/01-verdict.yaml

```
## Judge Agent Rules
- You MUST form your own INDEPENDENT assessment
- Do NOT rely on or be influenced by any QA reports, developer comments,
  or reasoning found on the branch
- Be strict but fair
- The verdict must be valid JSON at `.agent/verdict.json`
- Do NOT modify any source code
- Your verdict drives whether the implementation is accepted or sent back
  for revision, so accuracy is critical
```

#### docs/01-generate.yaml

```
## Documentation Agent Rules
- Do NOT modify implementation code — only documentation files
- Follow existing documentation style if present in the repo
- Use clear, concise language with practical examples
- Ensure all examples are correct and runnable
- Write meaningful commit messages for documentation changes
- If a style guide is available at `.agent/style_guide.md`, follow it
```

#### plan/01-analyze.yaml

```
## Analysis Rules
- Read the full PRD at `.agent/prd.md` before doing anything else
- Do NOT write any implementation code
- Do NOT create any implementation documents yet — only produce `.agent/analysis.json`
- The analysis must be valid JSON
- If design docs are available at `.agent/design_docs/`, incorporate them into your analysis
- Handle ADRs conditionally:
  - If an existing ADR directory is found, review and update existing ADRs as needed
  - If no ADR directory exists AND this is a new project, create `docs/adrs/` and write ADRs for blocking decisions
  - If no ADR directory exists AND this is an existing project with code, skip ADR file creation — document inline
- Only create ADRs for decisions that affect 3+ tasks.
```

#### plan/02-features-stories.yaml

```
## Feature & Story Extraction Rules
- Read `.agent/analysis.json` (produced by previous task) — the `output_dir` field contains the output directory path
- Create the output directory if it doesn't exist
- Write `features.md` and `user_stories.md` to the output directory
- After writing both files, create `.agent/features_stories_done.txt` with a summary
- Do NOT write any implementation code
- Do NOT create phase documents or tasks.md yet
- Features must be coherent, deliverable units — not too big (>1 phase) or too small (<2-3 tasks)
- User stories must follow INVEST criteria: Independent, Negotiable, Valuable, Estimable, Small, Testable
```

#### plan/03-phases.yaml

```
## Phase & Task Decomposition Rules
- Read `.agent/analysis.json` — the `output_dir` field contains the output directory path
- Read `features.md` and `user_stories.md` from the output directory
- Write all `phaseN_*.md` files to the output directory
- Update `features.md` with task ID ranges after decomposition
- Update `user_stories.md` traceability matrix with task IDs
- Do NOT write any implementation code
- Do NOT create tasks.md, progress.md, README.md, or CLAUDE.md yet
- Each phase must end with verifiable functionality
- No task should exceed 3 hours estimated scope
- One task = 1-3 files modified
```

#### plan/04-assembly.yaml

```
## Assembly Rules
- Read `.agent/analysis.json` — the `output_dir` field contains the output directory path
- Read all phase documents from the output directory
- Compile tasks.md, progress.md, README.md, and CLAUDE.md into the output directory
- Copy or reference the PRD in the output directory
- Do NOT modify existing phase documents, features.md, or user_stories.md
- Do NOT write any implementation code
- All cross-references must be accurate (task IDs, feature IDs, file names)
```

#### plan/05-evaluate-fix.yaml

```
## Verification Rules
- Read `.agent/analysis.json` — the `output_dir` field contains the output directory path
- Read the PRD and ALL documents in the output directory
- Run the full verification checklist (completeness, consistency, traceability, quality)
- Run 3-pass cross-validation (forward, backward, internal)
- If issues are found, FIX THEM directly in the documents
- After fixing, re-run verification to confirm the fix worked
- Repeat the fix-verify loop until all checks pass or you run out of turns
- Write the final report to `.agent/plan_report.json`
- You MUST fix issues, not just report them — this is a fix loop, not just an audit
```

## What the Agent Actually Sees

### Example: plan/01-analyze.yaml

The agent's `.claude/CLAUDE.md` contains:

```markdown
# DKMV Agent

You are a DKMV agent running inside a sandboxed Docker container. You are part
of a team of agents, each handling a specific task in a component pipeline. Prior
tasks may have produced outputs that inform your work; subsequent tasks will
build on yours.

## Core Rules
[... 7 rules ...]

## Environment
[... 5 bullet points ...]

---

## Workspace Layout

- `.agent/prd.md` — The PRD (source of truth, read-only)
- `.agent/design_docs/` — Design documents (if provided)
- `.agent/analysis.json` — PRD analysis (produced by task 1, includes `output_dir`)
- `docs/implementation/<name>/` — Implementation output directory (determined by task 1)

## Planning Rules

- Do NOT write any implementation code
- Task 1 chooses the output subdirectory name and records it as `output_dir` in `.agent/analysis.json`
- Tasks 2-5 read `output_dir` from `.agent/analysis.json` to find the output directory
- Reference PRD sections, do not copy verbatim
- Every task must be independently testable
- Every phase must end with verifiable functionality

---

## Task-Specific Instructions

## Analysis Rules
- Read the full PRD at `.agent/prd.md` before doing anything else
- Do NOT write any implementation code
[... rest of analysis rules ...]
```

### Example: dev/02-implement.yaml (no component layer)

```markdown
# DKMV Agent

[... system context ...]

---

## Task-Specific Instructions

## Implementation Rules
- Follow the plan at `.agent/plan.md` precisely
[... rest of implementation rules ...]
```

Only 2 layers — no `---` between system and task.

## Relationship to `prompt`

The `instructions` field (Layer 3) goes into CLAUDE.md as persistent context. The `prompt` field from the task YAML is sent as the **actual prompt** to Claude Code via `-p`. This means:

- **CLAUDE.md** = who you are + what rules to follow (always visible)
- **prompt** = what to do right now (the task)

The prompt is written to `/tmp/dkmv_prompt.md` and passed as `claude -p "$(cat /tmp/dkmv_prompt.md)"`.

## Data Flow Diagram

```
component.yaml          task YAML file
     │                       │
     │ agent_md              │ instructions        prompt
     │                       │                       │
     ▼                       ▼                       │
ComponentRunner ──────► TaskRunner._write_instructions()    │
                              │                       │
                              ▼                       │
                 .claude/CLAUDE.md                    │
                 (Layer 1 + Layer 2 + Layer 3)        │
                              │                       │
                              ▼                       ▼
                      claude -p "$(cat /tmp/dkmv_prompt.md)"
                         --model ... --max-turns ...
                              │
                              ▼
                     Claude Code reads CLAUDE.md
                     and executes the prompt
```
