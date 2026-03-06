# Interactive Pause Mechanism

## Status

Accepted

## Context and Problem Statement

Some DKMV workflows require human decisions between tasks. For example, after QA evaluation, the user should review the findings and choose whether to fix issues, ship as-is, or abort. After the plan agent analyzes a PRD, the user may need to answer architectural questions before implementation planning proceeds.

How should DKMV pause execution, present information to the user, collect decisions, and resume?

## Decision Drivers

- Must work between any two tasks in a component's sequence
- Must support two patterns: agent-generated questions (plan) and CLI-hardcoded menus (QA)
- User decisions must be available to subsequent tasks inside the container
- Must support skipping remaining tasks (e.g., "ship as-is" skips fix + re-evaluate)
- Must support fully automated runs with `--auto` (no interactive pauses)

## Decision Outcome

A callback-based pause system with three layers: YAML declaration (`pause_after: true`), data models (`PauseRequest`/`PauseResponse`), and CLI-side callbacks that present the UI.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│  component.yaml                                          │
│  tasks:                                                  │
│    - file: 01-evaluate.yaml                              │
│      pause_after: true         ◄── declaration           │
│    - file: 02-fix.yaml                                   │
│    - file: 03-re-evaluate.yaml                           │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  ComponentRunner.run()                                   │
│                                                          │
│  for each task:                                          │
│    result = TaskRunner.run(task)                          │
│    if result.status == "completed"                        │
│       and task_ref.pause_after                            │
│       and on_pause callback exists:                      │
│                                                          │
│      1. Build PauseRequest from task outputs              │
│         - Extract questions from JSON outputs             │
│         - Include output content as context               │
│      2. Call on_pause(request) → PauseResponse            │
│      3. Write answers to .agent/user_decisions.json       │
│      4. If skip_remaining: mark rest as "skipped", break  │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│  CLI Callbacks (one per use case)                        │
│                                                          │
│  _rich_pause_callback (plan):                            │
│    - If no questions: return empty answers                │
│    - Render agent-generated questions with Rich           │
│    - Collect answers via typer.prompt                     │
│    - Return PauseResponse(answers={...})                 │
│                                                          │
│  _qa_pause_callback (QA):                                │
│    - Parse qa_evaluation.json from context                │
│    - Display status, test counts, issue severity          │
│    - Present 3 hardcoded choices:                         │
│      1. Fix and re-evaluate → answers={"action": "fix"}  │
│      2. Ship as-is → skip_remaining=True                 │
│      3. Abort → raise typer.Exit(code=1)                 │
└─────────────────────────────────────────────────────────┘
```

### Data Models (`dkmv/tasks/pause.py`)

```python
class PauseQuestion(BaseModel):
    id: str                              # Unique ID for the question
    question: str                        # The question text
    options: list[dict[str, str]] = []   # [{"value": "v", "label": "l"}]
    default: str | None = None           # Default option value

class PauseRequest(BaseModel):
    task_name: str                       # Which task triggered the pause
    questions: list[PauseQuestion]       # Agent-generated questions (may be empty)
    context: dict[str, str] = {}         # Task outputs (path → content, truncated to 2000 chars)

class PauseResponse(BaseModel):
    answers: dict[str, str]              # User's answers keyed by question ID
    skip_remaining: bool = False         # If True, skip all subsequent tasks
```

### Question Extraction

Questions are extracted from task JSON outputs that contain a `questions` array:

```json
{
  "analysis": "...",
  "questions": [
    {
      "id": "auth_method",
      "question": "Which authentication method should be used?",
      "options": [
        {"value": "jwt", "label": "JWT tokens"},
        {"value": "session", "label": "Session-based"}
      ],
      "default": "jwt"
    }
  ]
}
```

This allows agents to generate questions dynamically based on their analysis. The CLI callback renders these with Rich and collects answers interactively.

### Decision Persistence

User answers are written to `.agent/user_decisions.json` inside the container, making them available to subsequent tasks:

```json
{
  "auth_method": "jwt",
  "action": "fix"
}
```

Tasks can reference this file in their prompts or read it directly.

### Skip Remaining

When `PauseResponse.skip_remaining = True`, `ComponentRunner` marks all subsequent tasks as `"skipped"` in the `ComponentResult` and breaks out of the task loop. This is used by QA's "ship as-is" option to skip the fix and re-evaluate tasks.

### `--auto` Flag

When `--auto` is passed, the CLI sets `on_pause=None`, which causes `ComponentRunner` to skip the pause entirely — the callback condition (`on_pause` is truthy) is not met, so execution continues to the next task without interruption.

## Consequences

- Good: Declarative `pause_after: true` — no code changes needed to add pauses to new components
- Good: Two callback patterns cover both agent-driven (plan) and CLI-driven (QA) use cases
- Good: `skip_remaining` provides clean short-circuiting without complex flow control
- Good: `--auto` flag enables fully automated CI runs
- Good: User decisions persisted as JSON — readable by both agents and humans
- Bad: Only supports pausing between tasks, not mid-task interruption
- Bad: Question extraction depends on specific JSON structure (`questions` array with `id`, `question`, `options` fields)
- Neutral: Each use case needs its own CLI callback function — but this keeps rendering logic close to the CLI
