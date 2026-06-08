# DKMV Public Embedded Runtime API Follow-Up PRD

Date: 2026-03-17  
Owner: ODIN  
Audience: DKMV maintainers, ODIN maintainers, future DKMV embedding consumers  
Status: Follow-up requirements PRD  
Related documents:
- [DKMV Public Embedded Runtime API PRD](/Users/tawab/Projects/Odin/docs/prds/DKMV_Public_Embedded_Runtime_API_PRD.md)
- [Odin Tasks Tab PRD](/Users/tawab/Projects/Odin/docs/prds/Odin_Tasks_Tab_PRD.md)

## 0. Purpose

This PRD is a follow-up to the original DKMV embedded runtime API request.

The original PRD asked DKMV to provide a public, host-agnostic runtime API that ODIN and other applications can embed without scraping the CLI or reaching into unstable internals.

The DKMV team has now implemented an initial public embedded runtime surface. ODIN reviewed that implementation against:

- the original embedded runtime API PRD
- ODIN’s current and planned task UX
- ODIN’s multi-project, multi-workspace execution model
- general runtime and workflow-system design patterns

That review found that the new runtime API is directionally strong, but still has several important gaps that should be addressed before ODIN treats the API as complete and stable for production integration.

This follow-up PRD documents those remaining gaps precisely.

## 1. ODIN Context for DKMV

DKMV should treat this section as the host context needed to understand why these gaps matter.

ODIN is a local-first desktop development environment built around:

- real local repositories and Git worktrees
- multiple concurrent projects and workspaces
- long-running canvas-based task surfaces
- rich task inspection, replay, debugging, and artifact review

ODIN wants to use DKMV as the workflow execution engine, while keeping DKMV independent as a reusable standalone package and CLI.

ODIN’s expectations are:

- runs may start from the user’s current local worktree state
- runs may include committed and uncommitted local work
- runs must execute in isolated sandboxes/containers
- ODIN must be able to observe runs live, reconnect later, inspect outputs, and debug failures
- ODIN must be able to support many runs across many workspaces without them interfering with each other

ODIN does not want DKMV to own:

- ODIN’s UI
- ODIN’s recipe library UX
- ODIN’s local workspace management
- ODIN’s canvas/node model

## 2. Terminology Mapping

| ODIN Term | DKMV Term | Meaning |
|-----------|-----------|---------|
| Recipe | Component | Reusable workflow definition |
| Run | Component execution | One execution instance of a recipe/component |
| Step | Task YAML file | Ordered execution unit inside a component |
| Workspace | Local repo/worktree checkout | The local source checkout the user is working in |
| Review point | Pause / human review | User decision gate before continuing |
| Artifact | Persisted run or step output | Durable output that survives cleanup |
| Runtime readiness | Preflight / operational readiness | Whether execution can start now |
| Capability report | Structural feature support | What the runtime surface supports in principle |
| Retained sandbox | Kept-alive container or equivalent retained execution environment | Used for post-run inspection and debugging |

## 3. Executive Summary

The current DKMV embedded runtime implementation is a good first pass, but it is not yet complete enough for ODIN’s intended integration model.

The most important remaining gaps are:

1. durable stop/cancel semantics
2. faithful live and replayable event history
3. richer recipe/component/task introspection
4. artifact provenance and step-output fidelity
5. retained sandbox inspection and live runtime telemetry
6. stronger local workspace snapshot semantics and source provenance

These are not ODIN-specific polish requests. They are core requirements for any serious host that wants to embed DKMV as a reliable runtime rather than as a subprocess wrapper.

## 4. What This Follow-Up Covers

This PRD requests improvements in six areas:

1. **Run cancellation and terminal state durability**
2. **Event fidelity, replay, and reconnect correctness**
3. **Structured introspection depth for components and tasks**
4. **Artifact and step-output provenance**
5. **Retained sandbox inspection and runtime telemetry**
6. **Local workspace snapshot semantics and provenance**

## 5. Non-Goals

This follow-up PRD does not ask DKMV to:

- implement ODIN’s UI
- implement ODIN-specific task panels, graphs, or canvas nodes
- own ODIN’s recipe authoring or local recipe overrides
- support arbitrary host persistence schemas
- support direct mutation of a host’s live worktree by default
- remove the containerized execution model

This document is about making the public embedded runtime complete and reliable, not moving ODIN product logic into DKMV.

## 6. Gap Review and Required Behavior

### 6.1 Gap A: Durable Stop / Cancel Semantics

#### Current gap

The current runtime surface exposes a public stop API, but the non-force path is not meaningfully wired into execution control, and force-cancel does not appear to guarantee a durable terminal run record.

This creates a serious recovery problem for hosts:

- a run may be cancelled in memory
- but persisted run history may still look like it is running
- after host restart, the host cannot reliably know whether the run completed, failed, or was cancelled

#### Why this matters

Hosts need run history to be durable and authoritative, not only in-process.

Without durable stop/cancel semantics:

- reconnect logic is unreliable
- dashboards show stale running runs
- queue/load accounting is wrong
- run cleanup and retention policies are harder to apply safely
- hosts must invent their own reconciliation logic

#### Required behavior

DKMV must provide a public run-control contract where:

- `stop` and `cancel` semantics are explicit
- the public run-state model is explicit
- every terminal stop path results in a persisted terminal run state
- a cancelled run is distinguishable from a failed run
- a cooperative stop is distinguishable from an immediate force-cancel
- hosts can determine whether cancellation was requested, acknowledged, and finalized

#### Good solution characteristics

A good solution must:

- define clear cancellation states and transitions
- write a terminal record for cancelled runs even during abrupt cancellation paths
- preserve partial outputs/events produced before cancellation
- guarantee that later `list_runs()` and `get_run()` calls reflect the terminal state
- work correctly after host restart

#### Acceptance criteria

- Cancelling a run always yields a durable persisted terminal state.
- Force-cancelled runs do not remain indefinitely listed as `running`.
- Hosts can distinguish `cancelled`, `failed`, `timed_out`, and normal completion.
- The public API documents the stable run states and allowed terminal transitions.
- Replay/history remains available for partially completed cancelled runs.

### 6.2 Gap B: Event Fidelity, Replay, and Reconnect Correctness

#### Current gap

The current runtime exposes live events and replay, but the event model is not yet faithful enough for a robust host UI.

Key issues:

- streamed agent events are not reliably tied to the active task/step context
- replay reconstructs timestamps instead of preserving the original event time
- the public replay contract is closer to “read the log again” than “replay a stable event history”

#### Why this matters

ODIN wants to show:

- live run progress
- step-by-step execution context
- per-step logs and outputs
- reconnect after app restart
- exact historical replay

Other embedding hosts need the same properties for dashboards, observability, and auditability.

#### Required behavior

DKMV must treat event history as a first-class public runtime surface.

The event system must support:

- a documented, stable event schema
- documented event type taxonomy and required fields
- stable sequence numbers
- stable original timestamps
- stable step-instance identity for every event associated with a concrete execution step
- explicit task/step context for every event that belongs to a step
- lifecycle events and stream events under one coherent event model
- replay from a cursor, offset, or equivalent checkpoint
- reconnect after host process restart
- observer delivery semantics that are documented for embedding hosts

#### Good solution characteristics

A good solution must:

- preserve original event timestamps
- preserve original run/task/step association
- preserve a stable identifier for the specific execution instance of a step, including repeated and expanded steps
- let a host reconstruct exactly what happened and when
- avoid forcing hosts to infer context by looking at surrounding events
- support replay from a known point without reprocessing the entire run history
- define what hosts can expect from observer delivery under load, including error isolation and any buffering/backpressure behavior

#### Acceptance criteria

- Every event has durable sequence and original timestamp fields.
- The public runtime documents the event schema, event type taxonomy, and required fields for host consumers.
- Step-associated stream events can be attributed to a specific task/step without host inference.
- Repeated, expanded, or resumed steps expose a stable step-instance identifier that hosts can use across events and artifacts.
- Replay returns the original event metadata, not reconstructed timestamps.
- Hosts can resume from a cursor/offset and only receive missing events.
- Replay behavior is documented for completed, failed, cancelled, and still-running runs.

### 6.3 Gap C: Introspection Depth for Components and Tasks

#### Current gap

The current introspection API exposes useful metadata, but it is still too shallow for ODIN and similar hosts to build rich recipe inspection UIs without parsing files themselves.

Hosts still need more than:

- counts
- booleans
- source paths
- top-level metadata

They also need the structured content of the recipe definition itself.

#### Why this matters

ODIN’s planned UX requires users to:

- inspect a recipe before running it
- read the recipe overview
- inspect component-level defaults
- inspect each ordered step
- read actual prompt content
- read actual instructions content
- understand how the component will execute

If DKMV’s public introspection surface is too shallow, ODIN still has to parse component/task files itself, which defeats the goal of a clean public runtime boundary.

#### Required behavior

DKMV must provide a structured introspection surface rich enough for a host to render:

- component metadata
- manifest structure
- ordered task refs
- per-task prompt and instructions content
- source references
- rendered and raw forms where relevant
- execution-plan preview with manifest defaults applied

#### Good solution characteristics

A good solution must:

- expose structured component and task detail, not only summary metadata
- preserve execution order
- make manifest-level and task-level inheritance/defaults understandable
- support both built-in and local custom components
- remain read-only

#### Acceptance criteria

- A host can inspect a component and render its actual ordered structure without reparsing files manually.
- A host can inspect each task’s prompt and instructions content through the public API.
- A host can show raw source references and structured parsed content.
- The execution-plan preview remains aligned with the rich introspection surface.

### 6.4 Gap D: Artifact and Step-Output Provenance

#### Current gap

DKMV now persists more run artifacts, which is the right direction, but the public artifact contract is still too lossy for strong host integration.

Important missing fidelity includes:

- stable provenance from artifact to producing step
- preservation of the original output path inside the sandbox/workspace
- collision-safe storage for same-basename outputs from different steps or directories
- clearer distinction between run-level artifacts, step-level artifacts, logs, prompts, instructions, and structured outputs

#### Why this matters

ODIN wants to show:

- step outputs even if temporary files inside `.agent` are later cleaned up
- JSON outputs produced by each step
- run outputs after completion
- what file came from what step
- what content was final vs intermediate

Other hosts will need similar artifact fidelity for debugging, audit, and result inspection.

#### Required behavior

DKMV must expose an artifact model that is:

- durable
- provenance-aware
- collision-safe
- content-addressable or otherwise stable enough for hosts to reference safely

The public artifact contract should support:

- listing artifacts
- artifact metadata
- artifact content access
- run-level vs step-level ownership
- stable step-instance ownership
- original relative path
- producing step/task
- content type
- timestamps
- digests or equivalent stable content identifiers

#### Good solution characteristics

A good solution must:

- not flatten distinct outputs into ambiguous basename-only artifacts
- let hosts map artifacts back to the producing step and original path
- preserve structured outputs even if the sandbox workspace later changes
- keep prompts, instructions, logs, and outputs separately identifiable
- support binary-safe and text-safe artifact access patterns

#### Acceptance criteria

- Two outputs with the same basename from different paths or steps do not collide.
- A host can determine which step produced a given artifact.
- A host can retrieve the original relative path for each persisted output.
- Persisted step outputs remain available after run completion and after sandbox cleanup.

### 6.5 Gap E: Retained Sandbox Inspection and Live Runtime Telemetry

#### Current gap

The current public runtime exposes aggregate historical stats, but richer sandbox inspection and live container/runtime stats remain effectively CLI-only behavior.

ODIN’s product direction requires:

- attach/reconnect to retained runs
- inspect retained execution environments
- show resource and runtime stats in a task stats component

The current public API does not yet provide that surface cleanly.

#### Why this matters

A serious embedding host needs more than historical counts.

Hosts need:

- whether a run still has a retained sandbox
- whether that sandbox is currently alive
- how to reconnect or inspect it
- runtime resource signals for active runs
- visibility into retained-but-stopped vs retained-and-running environments

#### Required behavior

DKMV must provide a public retained-inspection surface and a public live-telemetry surface.

This does not require DKMV to keep every container alive forever.

Instead, DKMV should expose:

- retention policy configuration
- retained sandbox metadata
- whether retained state is still attachable
- live runtime/container stats when available
- terminal inspection metadata when only persisted artifacts remain
- a post-run final workspace snapshot or export surface when deep filesystem inspection is needed after the live container is gone

#### Good solution characteristics

A good solution must:

- separate historical aggregate stats from live runtime stats
- avoid making the CLI the only path to attach or inspect
- allow hosts to determine whether a run is attachable, inspectable via snapshot, or artifact-only
- support explicit retention policies such as destroy, TTL, or manual cleanup
- give hosts a supported way to inspect the final run filesystem state even when direct container attach is no longer possible

#### Acceptance criteria

- Hosts can determine whether a run still has an attachable retained execution environment.
- Hosts can query live runtime stats for active or retained-running runs.
- Hosts can distinguish:
  - no retained environment
  - retained but stopped environment
  - retained and attachable environment
- Hosts can access or request a final workspace snapshot/export for runs that are no longer live-attachable but still require filesystem inspection.
- The public API exposes the information needed to build a stats dashboard without CLI scraping.

### 6.6 Gap F: Local Workspace Snapshot Semantics and Source Provenance

#### Current gap

The current `LOCAL_SNAPSHOT` mode is the correct direction, but the public contract is still underspecified for worktree-heavy hosts like ODIN.

DKMV needs a clearer public story for:

- what exactly is included in the snapshot
- whether uncommitted changes are included
- how worktrees are handled
- what provenance is recorded for the source state
- how the host later explains what source the run was based on

#### Why this matters

ODIN’s most important execution model is:

- the user is in a specific local repo/worktree
- the user may have committed and uncommitted changes
- the run should start from that local state
- the original host worktree should remain untouched

This is one of the core reasons ODIN asked for an embedded runtime API in the first place.

#### Required behavior

DKMV must define the execution-source semantics for local workspace runs explicitly.

The public contract must specify:

- what counts as a valid local snapshot source
- what is included when uncommitted changes are enabled
- what happens for worktrees
- what happens for untracked files
- what source provenance is recorded for the run

#### Good solution characteristics

A good solution must:

- preserve container isolation
- avoid bind-mounting the live workspace by default
- preserve the user’s live workspace from mutation
- record enough provenance for the host to explain the source:
  - source type
  - source path
  - branch
  - HEAD revision if available
  - dirty state
  - whether uncommitted state was included

#### Acceptance criteria

- The public API clearly defines local snapshot behavior for normal repos and Git worktrees.
- The runtime can tell the host whether uncommitted and untracked local state was included.
- Hosts can retrieve durable source provenance from run detail after the run is complete.
- The host does not need to infer local snapshot behavior by reading internal Git implementation details.

## 7. Cross-Cutting Requirements

### 7.1 Multi-Run Isolation and Scale

The resulting runtime must continue to support:

- multiple runs in parallel
- multiple projects and workspaces
- multiple repos and worktrees
- isolated run state, artifacts, and retained environments

This follow-up does not ask for a new scheduler, but the public API should be designed so that concurrency does not force hosts to guess or infer isolation boundaries.

In practice, hosts that embed DKMV also need a public load/throughput contract. The runtime should expose enough information for hosts to understand:

- active run count
- queued or pending run count, if queueing exists
- whether a new run can be admitted now
- whether a run was rejected, deferred, or queued due to capacity
- runtime-level resource signals relevant to safe admission

This does not require a specific scheduling architecture. It does require that hosts not be forced to infer capacity or overload risk indirectly.

### 7.2 Host-Agnostic Design

The solution must remain:

- ODIN-agnostic
- usable from desktop apps, services, dashboards, and other orchestration layers
- consistent with DKMV as a standalone CLI and package

### 7.3 Additive Evolution

The follow-up should be implemented additively where possible.

Hosts should not be forced to adopt unstable internals or rewrite against the runtime again immediately after integrating the first public API.

## 8. Evaluation Criteria

The follow-up should be considered complete when:

- cancellation and terminal-state persistence are durable and well-defined
- event replay is faithful enough for host-grade run viewers and reconnect flows
- component/task introspection can support a rich recipe-detail UI without manual file parsing
- artifact provenance is strong enough for step-level output browsing
- retained sandbox inspection and live runtime stats are part of the public runtime surface
- local snapshot behavior and provenance are explicit and documented
- post-run final workspace inspection is possible without relying solely on live container attach
- runtime load/admission behavior is explicit enough for hosts to scale safely

## 9. Suggested Validation Scenarios

DKMV should validate the follow-up against scenarios like:

1. Start a run, then cooperatively stop it, then restart the host process and confirm the run is durably cancelled.
2. Force-cancel a run mid-stream and confirm replay/history still shows a correct terminal record.
3. Run a component with multiple tasks and confirm every streamed event can be attributed to the correct step.
4. Replay a run and confirm the original event timestamps and sequence are preserved.
5. Inspect a built-in component and confirm prompt/instructions/source content is available through the public API.
6. Run two steps that produce the same basename in different paths and confirm artifacts do not collide.
7. Retain a sandbox after completion and confirm a host can detect that it is still attachable.
8. Query live runtime stats for an active retained container without scraping the CLI.
9. Run from a local Git worktree with uncommitted changes and confirm the run records source provenance correctly.
10. Run multiple tasks across multiple repos/workspaces and confirm histories, artifacts, and retained environments remain isolated.
11. Replay events for a `for_each` or resumed component run and confirm the host can distinguish step instances without relying only on task names.
12. Inspect a completed run after its live container is gone and confirm the host can still access a supported final workspace snapshot/export.
13. Exercise multiple simultaneous runs until the runtime reaches its intended capacity boundary and confirm hosts can observe admission/load behavior explicitly.

## 10. External Design Inputs

This follow-up is aligned with established runtime design patterns:

- Temporal emphasizes durable event history and explicit cancellation semantics.  
  Source: https://docs.temporal.io

- Prefect emphasizes explicit run states, orchestration state transitions, and events as first-class runtime surfaces.  
  Source: https://docs.prefect.io

- Dagster emphasizes structured materializations and metadata-rich outputs rather than opaque output files.  
  Source: https://docs.dagster.io

- Docker storage guidance reinforces that durable inspection should not rely only on ephemeral writable container layers.  
  Sources:
  - https://docs.docker.com/engine/storage/volumes/
  - https://docs.docker.com/engine/storage/bind-mounts/

These references inform the design goals, but this PRD intentionally does not prescribe exact DKMV implementation details.

## 11. Recommended Outcome

ODIN recommends that DKMV treat this follow-up as:

- a completion pass on the public embedded runtime API
- not a re-architecture of DKMV
- not an ODIN-specific customization request

If these follow-up gaps are addressed well, ODIN should have enough public runtime surface to integrate DKMV cleanly without resorting to:

- CLI scraping
- internal-signature checks
- ad hoc host-side reconciliation
- host-side recipe parsing for rich inspection
- host-specific patch layers around cancellation, replay, and retained inspection

## 12. Self-Review Checklist

Before this follow-up is considered final, the DKMV team should verify that:

- each gap in Section 6 is addressed explicitly
- the resulting public API remains host-agnostic
- no required behavior depends on CLI-only commands
- the runtime remains safe for local-workspace hosts
- the public API is strong enough for reconnect, replay, retained inspection, and step-level artifact browsing
