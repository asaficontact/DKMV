# DKMV Public Embedded Runtime API PRD

Date: 2026-03-17  
Owner: ODIN  
Audience: DKMV maintainers, ODIN maintainers, future DKMV embedding consumers

## 0. ODIN Context for the DKMV Team

ODIN is a local-first desktop development environment built around:

- a real local repository or worktree as the user’s active workspace
- a sidecar process that integrates external systems
- a canvas-based UI for long-running work surfaces
- multiple concurrent projects, repositories, and workspaces

ODIN wants to embed DKMV as the execution engine for automation workflows, while keeping DKMV independent as a standalone package and CLI.

The important host-side reality is:

- ODIN users work against **real local repositories and worktrees**
- ODIN users may have **uncommitted local changes**
- ODIN needs to show **live run progress, review points, outputs, history, and debugging context**
- ODIN needs to support **multiple concurrent runs across multiple projects/workspaces**
- ODIN intends to let users **copy built-in DKMV recipes locally, customize those copies, and create new recipes**

ODIN does **not** want DKMV to own ODIN’s UI, local recipe library, or host persistence model.

### 0.1 Terminology Mapping

The DKMV team should be aware of ODIN’s terminology, since the host-side UI does not expose DKMV internals directly.

| ODIN User-Facing Term | DKMV Internal Concept | Meaning |
|-----------------------|-----------------------|---------|
| Recipe | Built-in component or component template | Reusable workflow definition |
| Run | Component/task execution instance | One execution of a recipe/component |
| Step | DKMV task YAML file inside a component | Ordered execution unit within a recipe |
| Workspace | Local repo/worktree checkout | The source checkout the user is actively working in |
| Artifact | Persisted output/result/log from a run or step | Structured result that survives cleanup |
| Review point | Pause / human-in-the-loop gate | User decision required before continuing |
| Runtime readiness | Operational ability to execute now | Docker/image/auth/resources available |
| Capability report | Structural embedding support | Whether this DKMV version supports the host contract |

### 0.2 How ODIN Expects to Use DKMV

ODIN’s target model is:

1. browse and inspect recipes
2. choose a recipe and configure inputs
3. select an execution source based on the current repo/worktree context
4. launch the run in an isolated sandbox/container
5. observe live structured events
6. interact with review points
7. inspect run outputs, logs, and artifacts
8. optionally inspect a retained sandbox or restored post-run snapshot
9. reopen historical runs after app restart or reconnect

This PRD requests the DKMV runtime surfaces needed to support that model in a host-agnostic way.

## 1. Executive Summary

DKMV has reached the point where it should expose a first-class, public embedding API for hosts that want to run DKMV components programmatically instead of through the CLI alone.

ODIN is the first concrete host driving this need, but the requirement is broader than ODIN. Any desktop app, backend service, orchestration layer, or internal developer portal that wants to integrate DKMV needs the same core capabilities:

- load and inspect a component definition from disk
- launch and observe a component run programmatically
- receive structured lifecycle and stream events without scraping terminal output
- participate in human review/pause flows
- manage run state, artifacts, replay, and cancellation through a stable host-facing contract
- execute against host-relevant source material such as local workspaces, not only remote clones

Today, DKMV already contains most of the runtime building blocks:

- `ComponentRunner`
- `TaskRunner`
- `SandboxManager`
- `RunManager`
- `TaskLoader`
- `StreamParser`
- `on_pause` support

However, these pieces are still optimized for DKMV’s CLI and internal composition model, not for library consumers embedding DKMV as a subsystem.

This PRD requests a public, versioned, Odin-agnostic embedded runtime API for DKMV. The goal is to make DKMV a cleanly embeddable engine while preserving its independence as a standalone package and CLI.

## 2. What We Are Creating

We are requesting that DKMV provide a public embedded runtime API with eight major surfaces:

1. **Runtime Execution API**
   - Programmatically start, observe, pause, resume, stop, inspect, and rerun component/task runs.

2. **Execution Source API**
   - Let hosts choose how a run is seeded: remote clone, clean local checkout, local workspace snapshot, or equivalent host-defined source modes.

3. **Structured Event / Observer API**
   - Deliver machine-readable lifecycle and stream events to hosts in real time and make them replayable.

4. **Run History / Recovery API**
   - Let hosts list runs, inspect historical runs, replay persisted events, and recover state after restart or disconnect.

5. **Introspection / Validation API**
   - Load and validate component/task definitions from disk and return structured metadata for UI and automation consumers.

6. **Artifacts / Retention / Inspection API**
   - Persist step outputs and run artifacts, expose their metadata/content, and support retained sandbox or snapshot inspection flows.

7. **Operational Readiness / Telemetry API**
   - Expose machine-readable readiness, preflight, queue, and runtime stats for hosts.

8. **Embedding-Friendly Host Contract**
   - Let hosts provide configuration, credentials, logging, output sinks, and review handling without depending on CLI-oriented control flow or terminal scraping.

This is **not** a request to move ODIN’s recipe authoring, recipe storage, or project-specific workflow semantics into DKMV.

## 3. Why We Are Creating It

### 3.1 User Problem

End users want rich workflow automation integrated into local-first applications like ODIN. They need to:

- browse reusable recipes
- inspect recipe/task definitions before running them
- launch runs with project-specific inputs and workspace context
- observe execution in real time
- interact with review gates
- inspect artifacts, outputs, logs, and post-run state
- reopen historical runs later

These users should not need to think about whether DKMV is being invoked through a CLI or embedded in an application.

### 3.2 Product Problem

Without a public embedding API:

- hosts must reach into DKMV internals
- hosts may parse YAML or run artifacts themselves instead of using DKMV contracts
- hosts invent ad hoc compatibility checks against internal signatures
- hosts invent their own replay/recovery logic
- hosts may couple themselves to terminal or filesystem implementation details
- UI integrations become brittle across DKMV releases
- each host re-solves the same problems in slightly different ways

This reduces DKMV’s reusability and raises integration cost for every downstream consumer.

### 3.3 Technical Problem

In ODIN’s current implementation:

- DKMV is importable and usable as a package
- ODIN can materialize component files locally
- ODIN can browse built-in recipe definitions
- ODIN can persist local task/run metadata

But the integration is not architecturally clean yet because:

- ODIN currently checks internal runner signatures instead of consuming a public capability contract
- ODIN currently parses built-in recipe files for UI detail because DKMV does not yet expose a public structured introspection surface for component/task content
- DKMV runner constructors still assume a Rich `Console`, which is fine for CLI use but is not ideal as the only embedding story
- DKMV runtime events exist internally, but there is no stable host-facing observer/event API
- execution source semantics are not yet explicit for local workspaces/worktrees
- replay, recovery, telemetry, and retained inspection are not yet public runtime concepts

This is the right moment to define an explicit public boundary.

## 4. Current State Review

### 4.1 What DKMV Already Supports Well

Current DKMV code already provides:

- component execution from a component directory
- task execution inside a sandbox
- agent stream parsing
- run artifact persistence
- run output directories and result files
- human pause/review handling via `on_pause`
- reusable loaders for component/task definitions
- internal run/event persistence through `RunManager`

Relevant current DKMV modules:

- `dkmv/tasks/component.py`
- `dkmv/tasks/runner.py`
- `dkmv/tasks/loader.py`
- `dkmv/core/runner.py`
- `dkmv/core/sandbox.py`
- `dkmv/core/stream.py`
- `dkmv/tasks/pause.py`

### 4.2 Where DKMV Is Still CLI-Oriented

The current public-feeling runtime surface is still shaped around CLI composition:

- constructors require concrete runtime collaborators
- Rich console is a required constructor dependency
- event streaming is handled inside runner internals rather than surfaced through a stable observer interface
- there is no single host entry point like `EmbeddedRuntime`
- hosts must understand internal runner topology to embed DKMV correctly
- run persistence is available internally, but not yet as a clear host-facing replay/recovery contract

### 4.3 ODIN’s Current Workaround

ODIN currently:

- depends on `dkmv` as a Python package
- copies built-in recipes into project-local component directories
- parses recipe definitions for UI display
- creates local run metadata and local task/run persistence in its sidecar
- gates execution using a host-defined capability check

This works as a temporary bridge, but it is not the right long-term integration model.

### 4.4 Most Important Current Gap

The key gap is **not** “DKMV cannot run as a library.”  
The key gap is that DKMV does not yet expose a **stable public embedding contract** for hosts that need:

- structured event delivery
- runtime lifecycle control
- metadata introspection
- host-managed review handling
- clean capability discovery
- explicit execution source semantics
- replay and recovery
- artifact retention and post-run inspection

## 5. External Research and Best-Practice Inputs

This request is consistent with common patterns used by mature workflow and orchestration systems:

- **Celery signals** demonstrate the value of a decoupled notification surface for task lifecycle changes.  
  Source: [Celery Signals](https://docs.celeryq.dev/en/v4.3.0/userguide/signals.html)

- **Prefect events** demonstrate the value of a structured event model for run-state observation and automation.  
  Source: [Prefect Events](https://docs.prefect.io/v3/concepts/events)

- **Docker bind mounts** demonstrate why direct host-path sharing should not be the default for isolated workflow execution.  
  Source: [Docker Bind Mounts](https://docs.docker.com/engine/storage/bind-mounts/)

- **Docker volumes** demonstrate that durable state should live outside transient container layers when later inspection is required.  
  Source: [Docker Volumes](https://docs.docker.com/engine/storage/volumes/)

- **Rich Console API** demonstrates that Rich is best treated as a host-provided presentation object, not an application architecture boundary.  
  Source: [Rich Console API](https://rich.readthedocs.io/en/latest/console.html)

- **Python library logging guidance** reinforces that libraries should integrate cleanly into host applications without forcing UI/output assumptions.  
  Source: [Python Logging HOWTO](https://docs.python.org/3.9/howto/logging.html)

### 5.1 Best-Practice Conclusions

The best public design for DKMV is:

- event-driven, not terminal-scraped
- observer/callback based, not UI-specific
- additive on top of current internals
- explicit about lifecycle, execution-source semantics, and capability/readiness discovery
- filesystem-friendly, since components live on disk
- artifact-first for durable inspection, not “keep every container alive forever”
- usable in async environments without forcing CLI execution patterns

## 6. Product Principles

### P1. DKMV Must Remain Standalone

DKMV must stay usable as a standalone package and CLI. The embedded runtime API must complement the CLI, not replace it.

### P2. Public API, Not Internal Reach-In

Hosts should not inspect internal signatures or instantiate internal collaborators by reverse-engineering DKMV internals.

### P3. Host-Agnostic by Design

The API must not depend on ODIN concepts like sidebars, nodes, tasks tabs, or desktop workflows.

### P4. Structured Over Implicit

Run state, events, task metadata, review points, outputs, artifacts, and readiness must be exposed through structured data models, not inferred from console output or file scraping.

### P5. File-System Native

DKMV should continue to treat component directories on disk as the unit of execution, enabling built-ins, host-local copies, and custom components to all run through the same engine.

### P6. Isolation by Default

Hosts must be able to run multiple concurrent executions across multiple projects/workspaces without shared mutable state or accidental interference.

### P7. Artifacts Over Ephemeral State

Important run outputs must survive container teardown through explicit artifact persistence and retrieval contracts.

### P8. Additive Evolution

This should be an additive API layer built on top of current runner internals, minimizing disruption to DKMV’s CLI and existing users.

## 7. Goals and Non-Goals

### 7.1 Goals

The embedded runtime API must allow a host to:

- validate that DKMV is embeddable in the current environment
- validate that DKMV is operationally ready to execute **right now**
- inspect component/task definitions programmatically
- inspect resolved execution plans where variables and `for_each` expansion affect step order
- execute a component or task from a local filesystem path
- choose the execution source semantics for the run
- receive structured run and stream events while a run is executing
- replay events and recover host state after reconnect or restart
- handle pause/review interactions programmatically
- inspect run results, step outputs, artifacts, and logs after execution
- optionally retain and inspect a completed sandbox or exported run snapshot
- stop or cancel an in-flight run
- observe runtime telemetry and resource usage
- consume the API without requiring terminal/CLI scraping
- use the same runtime for built-in components and host-local customized components
- support multiple concurrent runs across multiple projects/workspaces without cross-run interference

### 7.2 Non-Goals

This PRD does **not** request that DKMV:

- implement ODIN-specific UI behavior
- own host-side recipe libraries or recipe editing UX
- provide a browser UI
- store application-specific project metadata for hosts
- implement host-specific persistence layers
- absorb ODIN’s local override model for built-in recipes
- make container retention the default for all runs

### 7.3 Explicit Boundary

DKMV should own:

- execution
- lifecycle
- pause/review
- sandboxing
- stream event production
- component/task validation and introspection
- readiness/preflight reporting
- run history/replay primitives
- artifact persistence and retrieval

ODIN or any host should own:

- recipe browsing UI
- local recipe copies and overrides
- user-authored recipe management
- run presentation UI
- app-specific persistence and navigation
- choosing the default host UX around retained inspection

## 8. Core Concepts

### 8.1 Component

A directory on disk containing a `component.yaml` and referenced task files. A component may be:

- a built-in DKMV component
- a host-local copy of a built-in component
- a host-authored custom component

### 8.2 Embedded Runtime

A public DKMV object or entry point that a host can create and use to:

- inspect components
- execute components/tasks
- observe lifecycle
- control runs
- query readiness
- query history and artifacts

### 8.3 Run Handle

A host-facing object representing an in-flight or completed run. It should provide:

- stable run identity
- current state
- control methods where applicable
- access to artifact and result locations
- access to replay and inspection helpers where applicable

### 8.4 Execution Source

A host-facing description of where the run’s working code state comes from.

Minimum supported conceptual modes:

- remote clone
- clean local checkout
- local workspace snapshot
- local workspace snapshot including uncommitted changes
- implementation-defined advanced modes such as bind mount, if supported

The exact implementation may vary, but the public contract must make source semantics explicit.

### 8.5 Observer / Event Sink

A host-provided callback or interface that receives structured runtime events.

### 8.6 Capability Report

A host-facing description of what the current DKMV version structurally supports for embedding. This replaces host-side reflection against internal signatures.

### 8.7 Preflight / Readiness Report

A host-facing description of whether the runtime can execute **now**, including operational blockers such as Docker, images, auth, or resource constraints.

### 8.8 Run Artifact

A durable output captured during or after a run that remains available independently of whether the sandbox is still alive.

### 8.9 Retained Sandbox

An optional retained execution environment that remains inspectable after completion for debugging or review, subject to retention policy.

## 9. Proposed Public Runtime Surface

### 9.1 Required High-Level API

DKMV should expose a documented public entry surface such as:

- `EmbeddedRuntime`
- or `RuntimeClient`
- or `EmbeddedComponentRunner`

The exact name is implementation-defined, but it must be clearly documented as the supported embedding surface.

### 9.2 Runtime Creation Requirements

The host must be able to create the runtime with:

- configuration object(s)
- optional filesystem/output directory configuration
- optional logging/output integration
- optional observer / event sink
- optional pause/review handler
- optional retention policy defaults

The host must **not** be required to construct low-level internal collaborators manually unless that is the documented public factory path.

### 9.3 Execution Entry Points

The runtime must support:

- execute component from path
- execute task definition from path or loaded definition
- rerun/restart where supported
- start from a specific task within a component where supported
- execute with an explicit execution source contract

The execution entry points must accept host-provided:

- repo path / repo URL / branch inputs as needed by DKMV
- variable overrides
- runtime configuration overrides
- context paths/files
- adapter selection/model overrides where supported
- execution source mode
- retention policy override where supported

### 9.4 Local Workspace Execution Semantics

This is a required capability for hosts like ODIN.

The API must let a host express whether the run should start from:

- the last committed state of a local checkout
- a snapshot of the current local workspace
- a snapshot of the current local workspace including uncommitted changes

The API must document:

- whether uncommitted host changes are included
- whether the source is copied, archived, cloned, or mounted
- whether host files can be modified directly
- how source provenance is recorded

Preferred default guidance for local-first hosts:

- use an **isolated snapshot** of the local workspace/worktree
- do **not** require the host to auto-commit local WIP as a prerequisite
- do **not** require bind-mounted host mutation as the default

### 9.5 Control Entry Points

The runtime should provide host-facing controls for:

- stop/cancel run
- inspect current run state
- retrieve or enumerate artifacts
- retrieve final result
- resume from a host-handled pause decision
- attach to a retained live sandbox where supported
- release or clean up retained resources where supported

If stop/cancel semantics differ by run state, those rules must be documented.

## 10. Run State Model Requirements

### 10.1 Canonical State Taxonomy

The embedded runtime must define a canonical state model that hosts can safely depend on.

Minimum required concepts:

- created
- blocked
- bootstrap pending
- queued
- running
- pause requested
- paused
- stopping
- stopped
- completed
- failed
- cancelled

The exact public labels may vary, but the semantic states must be documented.

### 10.2 Transition Contract

The runtime must document valid transitions between states, including:

- what conditions cause a run to become blocked
- what distinguishes blocked vs queued vs paused
- what state a stop/cancel request produces
- what state a retained completed run remains in

Hosts need this for UI state machines, retries, and recovery.

## 11. Run History, Replay, and Recovery Requirements

### 11.1 Run History

The runtime must expose public methods to:

- list runs
- filter runs by component/project/source as supported
- fetch run detail by id
- enumerate artifacts for a historical run

### 11.2 Event Replay

The runtime must expose a replay mechanism for historical or partially consumed run events.

Minimum replay features:

- replay by run id
- replay from sequence/offset/cursor
- deterministic ordering
- indication of whether replay is complete

### 11.3 Host Recovery

The runtime contract must support host restart and reconnect flows, including:

- reconnecting to a currently active run
- rebuilding host state from replayed events
- inspecting completed historical runs without a live observer

## 12. Introspection and Validation Requirements

### 12.1 Public Component Introspection

DKMV should expose a public read-only API that returns structured component metadata for a component directory:

- component name
- description
- agent and model defaults
- shared inputs
- ordered task references
- per-task overrides from manifest
- raw source path references
- source origin metadata where available

### 12.2 Public Task Introspection

DKMV should expose structured task metadata for each task file:

- task name
- description
- instructions
- prompt
- outputs
- review configuration
- commit/push flags
- model/agent settings
- source path

### 12.3 Resolved Execution Preview

DKMV should provide a public way to preview the resolved execution plan after:

- variable injection
- manifest defaults
- `for_each` expansion
- start-task offsets where applicable

Hosts need this for accurate UI preview and validation of what will actually run.

### 12.4 Validation API

DKMV should provide a public validation API for:

- validating a component directory
- validating task definitions
- reporting structured validation errors

Hosts need this for recipe browsing, local recipe editing, and safe execution preparation.

### 12.5 Source Fidelity Requirement

The introspection API must preserve source fidelity well enough that a host can:

- display what the component will do
- show the execution order
- show task definitions and prompts
- distinguish built-in defaults from host-local edits

## 13. Event and Observer Requirements

### 13.1 Structured Event Model

DKMV should expose a structured event stream for embedded hosts.

Minimum event classes:

- runtime started
- preflight completed
- component run started
- task started
- task progress / agent stream event
- step output captured
- task completed
- task failed
- pause requested
- pause decision applied
- artifact saved
- component completed
- component failed
- run stopped/cancelled
- retained sandbox released or expired

### 13.2 Event Format Requirements

Every event should include:

- stable event type
- timestamp
- sequence or cursor
- run id
- component name or identifier
- task identifier where relevant
- payload object with event-specific fields

The payload should be machine-readable and stable enough for hosts to render without parsing console text.

### 13.3 Raw vs Normalized Events

Hosts need both:

- **normalized lifecycle events** for state machines and UI
- **optional raw agent events** for advanced debugging and rich activity views

The API should define whether raw events are best-effort, adapter-specific, or versioned separately from normalized lifecycle events.

### 13.4 Observer Behavior

The observer API should:

- be async-friendly
- allow hosts to subscribe per run
- avoid coupling hosts to internal Rich rendering behavior
- define how observer failures are handled

Preferred rule:

- observer failures must not crash or corrupt the run by default
- hosts may opt into strict behavior if desired

### 13.5 Backpressure and Volume

The API must document:

- expected event rate characteristics
- whether events are delivered inline or buffered
- whether event delivery can be throttled/coalesced
- what happens when a host cannot keep up

This is important for GUI hosts and multi-run service hosts.

## 14. Review / Pause Requirements

### 14.1 Public Pause Contract

DKMV already supports pause handling internally via `on_pause`. This should become part of the public embedding contract.

### 14.2 Required Pause Surface

The host must receive:

- pause request id
- task name / task id
- pause title
- prompt
- options
- relevant context outputs

The host must be able to respond with:

- decision / selected option(s)
- optional structured answers
- optional skip/continue directives where supported

### 14.3 Deterministic Resume

Resume behavior must be deterministic and documented. Hosts should not need to guess how a pause response alters execution flow.

## 15. Artifacts, Outputs, and Post-Run Inspection Requirements

### 15.1 Step Output Capture

This is a required capability.

If a step produces declared outputs, the embedded runtime must support capturing them as durable artifacts even if:

- the working directory is later cleaned up
- temporary files are removed during later steps
- the sandbox/container is later destroyed

### 15.2 Artifact Model

The runtime must provide, at minimum:

- artifact id
- producing run id
- producing step/task id where relevant
- artifact kind/type
- path/origin metadata
- timestamps
- content metadata such as size and content type where possible

### 15.3 Artifact Access

The runtime must let hosts:

- list artifacts for a run
- get artifact metadata
- read or stream artifact content

Filesystem paths alone are not sufficient as the only public contract for all embedding hosts.

### 15.4 Final Workspace Snapshot / Inspection Bundle

The runtime should support a durable post-run inspection surface such as:

- exported workspace snapshot
- retained volume/workspace reference
- run bundle containing artifacts, prompts, logs, and final file state metadata

This is a more scalable foundation than keeping all completed containers alive forever.

## 16. Retention and Inspection Requirements

### 16.1 Retention Policy

The runtime should expose retention modes such as:

- destroy on completion
- retain for TTL
- retain until manual cleanup

### 16.2 Live Inspection

When a sandbox is retained and still alive, the runtime should support host-facing reattachment or inspection of that retained execution context.

### 16.3 Historical Inspection

When a sandbox is no longer alive, the runtime should still support historical inspection through persisted artifacts, run bundle data, and workspace snapshot metadata.

## 17. Console, Logging, and Output Requirements

### 17.1 Console Requirement

The embedded runtime must not require terminal scraping or terminal-centric presentation as the only useful host integration path.

This does **not** mean Rich must be removed from DKMV.

The actual requirement is:

- the runtime must support host-friendly output integration
- hosts must not need a visible CLI console to embed DKMV successfully

Acceptable solutions may include:

- optional console injection
- a documented quiet/default console behavior
- a host-provided output sink abstraction
- a runtime facade that hides console handling internally

### 17.2 Logging Requirement

DKMV should expose library-friendly logging behavior consistent with Python library best practices:

- logs go through logging infrastructure
- hosts can attach their own handlers
- embedded runs do not require terminal rendering to be useful

### 17.3 Public Runtime Outputs

The runtime should document which outputs are public and durable, including:

- artifact paths
- prompt files
- run logs
- stream logs
- final result metadata
- run bundles / retained snapshot metadata where supported

## 18. Operational Readiness and Telemetry Requirements

### 18.1 Capability Report

Hosts should be able to ask DKMV what it supports structurally instead of inspecting internal signatures.

The capability report should indicate, at minimum:

- embedded runtime available
- event observer support available
- pause callback support available
- stop/cancel support available
- validation/introspection support available
- replay/history support available
- retention/inspection support available
- telemetry support available

### 18.2 Preflight / Readiness Report

Hosts also need a separate operational readiness report answering whether a run can start now.

Minimum readiness checks should cover, where applicable:

- required package/runtime present
- Docker available
- sandbox image/bootstrap state
- auth/credentials ready
- adapter/model prerequisites satisfied
- memory/resource availability
- host policy blockers

Capability and readiness are different concepts and must be exposed separately.

### 18.3 Runtime Telemetry / Stats

The runtime should expose host-consumable telemetry such as:

- active runs
- queued runs
- retained sandboxes
- queue depth
- per-run duration and cost summary
- resource usage signals where available
- bootstrap/setup state

This supports stats dashboards in hosts like ODIN without making DKMV UI-specific.

## 19. Concurrency and Isolation Requirements

### 19.1 Multi-Run Isolation

The runtime must be safe for:

- multiple projects
- multiple repos
- multiple workspaces/worktrees
- multiple branches
- multiple concurrent runs

### 19.2 Namespace Requirements

Runs, artifacts, logs, retained sandboxes, and replay state must be namespaced so hosts do not see collisions or cross-run contamination.

### 19.3 Shared State Constraints

Any shared state such as image caches or common runtime caches must be clearly documented. Execution workspaces themselves must remain isolated per run unless the host explicitly opts into a shared mode.

## 20. Host Integration Requirements for ODIN and Other Platforms

### 20.1 Run Any Local Component Directory

This is critical.

Hosts must be able to run any valid component directory from disk, including:

- built-in DKMV components
- a host-local copy of a built-in component
- a user-customized fork of a built-in component
- a host-created custom component

This is the primary requirement that enables ODIN’s future recipe editing model without pushing host-specific recipe ownership into DKMV.

### 20.2 Stable Introspection for Local Copies

The same introspection API must work for:

- DKMV built-ins
- copied local component directories
- customized local components

### 20.3 No Host-Specific Persistence Coupling

DKMV should not assume the host’s project DB model, UI structure, or local metadata format.

### 20.4 Async and Service Embedding

The public runtime should be usable from:

- desktop sidecars
- FastAPI/Starlette services
- worker daemons
- test harnesses

## 21. Future-Facing Requirements

The API should be designed to support, without redesign:

- host-managed recipe libraries
- user-edited local recipe copies
- richer live execution UIs
- replay of run events
- remote or multi-tenant hosts
- more than one embedding consumer
- retained inspection and debugging workflows
- metrics/ops dashboards

Future hosts should not need ODIN-specific affordances to use the runtime correctly.

## 22. Phased Delivery Recommendation

### Phase 1: Public Read-Only Introspection + Capability and Readiness Reports

Deliver:

- public introspection API
- validation API
- resolved execution preview
- public capability report
- public operational readiness/preflight report
- documentation of current embedded runtime constraints

This immediately removes host-side YAML parsing and signature reflection.

### Phase 2: Public Embedded Execution API

Deliver:

- public runtime entry point
- documented execution methods
- explicit execution source contract
- pause/review public contract
- host-friendly output handling

### Phase 3: Public Observer / Event / Replay API

Deliver:

- normalized lifecycle events
- optional raw stream event forwarding
- host observer registration
- replay/history APIs
- documented delivery semantics

### Phase 4: Artifacts, Retention, and Operational Telemetry

Deliver:

- step artifact capture
- artifact metadata/content APIs
- retention policy support
- retained inspection helpers
- telemetry/stats APIs
- capability/version maturity docs

## 23. Risks and Mitigations

### Risk 1: DKMV exposes internals prematurely

Mitigation:

- define a narrow public runtime facade
- keep lower-level collaborators internal unless clearly documented

### Risk 2: ODIN-specific needs leak into DKMV

Mitigation:

- phrase requirements around hosts, not ODIN UI
- keep recipe authoring/storage out of DKMV scope

### Risk 3: Event API becomes adapter-specific and unstable

Mitigation:

- define normalized lifecycle events as the primary contract
- treat raw adapter events as optional secondary output

### Risk 4: Container retention becomes the default and harms scalability

Mitigation:

- make retention policy explicit
- prefer artifacts/run bundles for durable inspection
- keep live retained sandboxes optional

### Risk 5: Execution source behavior is ambiguous and unsafe

Mitigation:

- define source modes explicitly
- document whether uncommitted host changes are included
- avoid bind-mounted host mutation as the default

### Risk 6: Hosts still need ad hoc readiness layers

Mitigation:

- separate structural capability discovery from operational preflight/readiness

## 24. Validation Requirements

### 24.1 DKMV Validation

The DKMV team should validate that:

- a host can create the runtime without CLI entry points
- a host can inspect built-in and local component directories through a public API
- a host can preview a resolved execution plan
- a host can execute a component run using explicit source semantics
- a host can receive structured events and replay them later
- a host can handle a pause and resume the run
- a host can stop a run
- a host can retrieve results, artifacts, and step outputs after completion
- a host can inspect a retained run or persisted run bundle according to retention policy
- the runtime behaves correctly under concurrent multi-run load

### 24.2 Compatibility Validation

The DKMV team should validate that:

- existing CLI behavior remains intact
- current built-in components still execute correctly
- public embedded APIs do not require ODIN-specific assumptions

### 24.3 Host Validation

ODIN should validate that:

- recipe browsing uses DKMV introspection, not host-side parsing
- local copied/customized recipes run through the same public runtime
- live run UI can subscribe to structured runtime events
- historical runs can be reopened after restart
- review points are fully host-driven through the public pause contract
- step outputs remain available after sandbox cleanup
- stats/telemetry views can be built from the public runtime telemetry surface

## 25. Acceptance Criteria

The request should be considered complete when DKMV provides a documented public embedding story with the following properties:

1. A host can programmatically inspect a component/task definition from disk without parsing YAML manually.
2. A host can preview the resolved execution plan for a run.
3. A host can start a component run through a documented public API with explicit source semantics.
4. A host can receive structured lifecycle events while the run is active.
5. A host can replay prior events and recover state after disconnect or restart.
6. A host can participate in pause/review flows programmatically.
7. A host can stop or otherwise control a run through a documented contract.
8. A host can access results, step outputs, and artifacts through documented runtime outputs.
9. A host can distinguish capability discovery from operational readiness.
10. A host can support retained inspection/debugging without keeping all containers alive by default.
11. A host does not need to reflect on internal signatures to determine compatibility.
12. The API remains DKMV-agnostic and host-agnostic, not ODIN-specific.

## 26. Out of Scope for This PRD

The following are intentionally out of scope:

- ODIN-specific UI nodes, panels, or task tabs
- host-specific recipe editors
- project-local recipe storage formats
- synchronized editing of built-in recipes in the DKMV package itself
- DKMV cloud services or remote APIs

## 27. Final Recommendation

The right long-term fix is:

- **not** for ODIN to keep inferring DKMV compatibility from internal signatures
- **not** for DKMV to absorb ODIN’s recipe-management UX
- **but** for DKMV to expose a clean, public embedded runtime API with introspection, execution, source semantics, observation, replay, retention, telemetry, and control surfaces

This gives ODIN what it needs now and in the future, while also making DKMV substantially more valuable as a standalone automation engine for any host that wants to embed it.

## 28. Self-Evaluation and Gap Check

This PRD was reviewed against the following questions:

1. **Does it solve only today’s ODIN blocker?**  
   No. It covers current ODIN execution needs and future embedding use cases.

2. **Does it push ODIN-specific product decisions into DKMV?**  
   No. It keeps recipe browsing/editing UX and local override semantics in the host.

3. **Does it ask for implementation details prematurely?**  
   No. It specifies requirements and validation criteria, not exact class names or code structure.

4. **Does it cover the major missing embedding dimensions?**  
   Yes. It now covers introspection, execution, source semantics, replay/recovery, events, review handling, control, outputs, readiness, telemetry, retention, and concurrency.

5. **Does it preserve DKMV’s standalone identity?**  
   Yes. The API is framed as a host-agnostic runtime surface, not an ODIN-specific feature set.

Residual open design decisions intentionally left to DKMV:

- exact public class/function names
- sync vs async wrapper shape
- whether observer delivery is callback-based, interface-based, or queue-based
- how best to expose run handles and replay helpers
- how retained inspection is represented internally

Those are implementation choices for the DKMV team, provided they satisfy the requirements above.
