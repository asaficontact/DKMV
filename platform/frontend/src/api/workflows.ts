/**
 * Workflows viewer API surface (Screen 07 / F12 — §5.8 FR-07-1v, §6.2, §7.2).
 * Thin typed wrappers over the generic {@link apiGet} client for the **read-only**
 * Workflows viewer (slice 4.2):
 *
 *   - `GET /workflows`        — every built-in + registered component's pipeline
 *     summary ({@link WorkflowSummary}) for the level-1 list.
 *   - `GET /workflows/{id}`   — one component's summary **plus** the read-only
 *     `component.yaml` + task YAML text ({@link WorkflowDetail}) for the
 *     "compiles to YAML" peek.
 *
 * **Read-only (ADR-P010, AC-2).** There is no write client here — no `POST`/`PUT`
 * `/workflows`, no edit/save call. The viewer only reads component definitions
 * already present on the local disk via the in-process engine. Authoring is v1.1.
 *
 * **INV-1 / INV-2.** Plain authed JSON over {@link apiGet} (the loopback token
 * rides the `Authorization` header; never a `?token=` query string).
 *
 * The summary shape is shared with the run-panel workflow picker, so
 * {@link WorkflowSummary} / {@link WorkflowStage} are re-exported from `./runs`
 * (one source of truth — the `GET /workflows` list entry).
 */
import { apiGet } from "./client";
import type { WorkflowStage, WorkflowSummary } from "./runs";

export type { WorkflowStage, WorkflowSummary } from "./runs";

/**
 * One read-only YAML document for the "compiles to YAML" peek (slice 4.1
 * `WorkflowYaml`). `filename` is the on-disk basename (`component.yaml` or a task
 * `*.yaml`); `content` is its verbatim text. Rendered read-only — there is no
 * edit/save path in v1 (ADR-P010).
 */
export interface WorkflowYaml {
  filename: string;
  content: string;
}

/**
 * `GET /workflows/{id}` payload (slice 4.1 `WorkflowDetail`): the pipeline summary
 * plus the read-only `component.yaml` + task YAML documents.
 */
export interface WorkflowDetail {
  summary: WorkflowSummary;
  /** The component manifest text (`component.yaml`/`.yml`), or null when absent. */
  component_yaml: WorkflowYaml | null;
  /** The task `*.yaml` documents, in on-disk task order. */
  task_yaml: WorkflowYaml[];
}

/** List every built-in + registered component's pipeline summary (`GET /workflows`). */
export function listWorkflows(): Promise<WorkflowSummary[]> {
  return apiGet<WorkflowSummary[]>("/workflows");
}

/**
 * Fetch one component's summary + read-only YAML (`GET /workflows/{id}`). An
 * unknown id surfaces as an {@link import("./client").ApiError} carrying
 * `workflow_not_found` (§8.9).
 */
export function getWorkflow(id: string): Promise<WorkflowDetail> {
  return apiGet<WorkflowDetail>(`/workflows/${encodeURIComponent(id)}`);
}
