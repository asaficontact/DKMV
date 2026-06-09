/**
 * Run-launch API surface (Screen 03, FR-03 / §8.4, §8.9). Thin typed wrappers
 * over the generic {@link apiGet}/{@link apiPost} client for the issue-detail +
 * "Run this issue" panel:
 *
 *   - `GET  /issues/{owner}/{name}/{num}` — the issue detail (markdown body,
 *     labels, author, comments, active-run block) (slice 2.1).
 *   - `GET  /workflows`                   — the workflow picker source (slice 4.1).
 *   - `POST /runs`                        — claim-lock launch → `{ run_id }` (slice 2.1).
 *   - `GET  /runs/{id}`                   — the §8.9 run-detail baseline.
 *
 * **No hardcoded model labels (FR-03-2 / §6.1 drift).** The model strings come
 * from the engine adapter defaults surfaced *through the API* — the workflow
 * summary carries `agent`/`model` for each component (Codex default `gpt-5.4`,
 * not the prototype's `gpt-5.1-codex`). We never inline a model constant here.
 *
 * **INV-2.** Nothing here ever places a token in a URL/query — the SSE stream
 * (Phase 2 live view) rides the HttpOnly cookie; these are plain authed JSON
 * requests via {@link apiGet}/{@link apiPost}.
 */
import { apiGet, apiPost } from "./client";
import type { AnswerBody, PauseRequest } from "../components/PauseCard";

/** A GitHub label on the issue detail (color is the GitHub hex, only for `--lc`). */
export interface IssueLabel {
  name: string;
  /** GitHub's 6-hex label color (no leading `#`), or null. Used as a CSS var. */
  color: string | null;
}

/** The issue author block (`{login, avatar}` or null). */
export interface IssueAuthor {
  login: string;
  avatar: string | null;
}

/** One comment in the thread (§5.4). */
export interface IssueComment {
  id: string | null;
  body: string;
  created_at: string | null;
  author: IssueAuthor | null;
}

/**
 * The issue's **active run** block (or null) the existing-run alert renders. The
 * run status drives the paused (amber/Review decision) vs running (blue/Watch
 * live) variant; `run_id` links to the live run (§5.4 / FR-03-1, FR-03-4).
 */
export interface ActiveRun {
  /** Platform UUID of the active run (addresses the live-run view). */
  run_id?: string | null;
  /** Engine `RunStatus` (`running`/`paused`/…); drives the alert variant. */
  status: string | null;
  pr_num: number | null;
}

/** The `GET /issues/{owner}/{name}/{num}` detail body (§5.4 / §8.9). */
export interface IssueDetailResponse {
  num: number;
  title: string;
  body: string;
  /** GitHub issue state (`open`/`closed`) — lowercased by the backend. */
  state: string;
  url: string | null;
  created_at: string | null;
  author: IssueAuthor | null;
  labels: IssueLabel[];
  comments: IssueComment[];
  active_run: ActiveRun | null;
}

/** One stage in a workflow's pipeline (`GET /workflows`, slice 4.1). */
export interface WorkflowStage {
  index: number;
  name: string;
  description: string;
  /** This stage pauses after for a HITL decision (the "pauses" badge source). */
  pause_after: boolean;
  budget_usd: number | null;
  for_each_item: string | null;
}

/**
 * One workflow summary from `GET /workflows` (slice 4.1, §6.2). The picker is
 * populated **from this list**, never a hardcoded constant (AC-6). `agent`/`model`
 * are the engine adapter defaults for the workflow (the §6.1 drift source).
 */
export interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  is_builtin: boolean;
  /** The workflow's default agent (`claude`/`codex`); `auto` resolves to this. */
  agent: string | null;
  /** The workflow's default model (engine adapter default — §6.1 drift note). */
  model: string | null;
  stages: WorkflowStage[];
  stage_count: number;
  pause_count: number;
  pause_points: string[];
  /** The authoritative est. total budget (component `max_budget_usd` or Σstages). */
  est_total_usd: number | null;
}

/** The `POST /runs` request body (§8.4). `agent` may be `auto`; the backend
 * resolves `auto → workflow.agent` and rejects Codex budget/turns (INV-8). */
export interface CreateRunRequest {
  issue_num: number;
  repo: string;
  workflow_id: string;
  /** `claude | codex | auto`. The UI sends the already-resolved agent (FR-03-3). */
  agent: string;
  branch: string;
  feature_name: string;
  model?: string | null;
  max_turns?: number | null;
  timeout_minutes?: number | null;
  max_budget_usd?: number | null;
  memory?: string | null;
  context?: string[];
  keep_alive?: boolean;
  start_task?: string | null;
}

/** The `POST /runs` `201` response — the **platform UUID** (§8.4). */
export interface CreateRunResponse {
  run_id: string;
}

/**
 * The `decision:{...}|null` PauseCard rehydration block from `GET /runs/{id}`
 * (slice 2.3, §8.3). When the run is paused this carries the open pause decision:
 * the `decision_id`, the `task_name`, the decision `status`, the UTC `timeout_at`,
 * and the engine-authored {@link PauseRequest} (`{task_name, questions, context}`)
 * the {@link PauseCard} renders. `null` when the run is not paused.
 *
 * This is the **rehydration source** (not the live push): if the SSE socket drops
 * mid-pause, the reconnect replay only reaches `pause_requested`, so the card is
 * sourced from this block on `GET /runs/{id}` rather than the live `decision` event.
 */
export interface RunDecision {
  decision_id: string;
  task_name: string | null;
  status: string | null;
  timeout_at: string | null;
  /** The engine `PauseRequest` payload the {@link PauseCard} renders (§6.1). */
  request: PauseRequest;
}

/** A stage row in the run detail (§8.9 `RunStage`). */
export interface RunStage {
  idx: number;
  name: string;
  status: string;
  cost_usd: number | null;
  turns: number;
  duration_s: number | null;
}

/** The `GET /runs/{id}` detail baseline (§8.9). */
export interface RunDetailResponse {
  id: string;
  engine_run_id: string | null;
  repo: string;
  issue: { num: number; title: string } | null;
  workflow_id: string | null;
  agent: string | null;
  model: string | null;
  status: string;
  branch: string;
  /** The segment-sum cost (INV-7). Codex → null/"—" (FR-06-1a). */
  cost_usd: number | null;
  /** True when the run's cost is excluded from spend (Codex) → render "—". */
  cost_excluded?: boolean;
  tokens_in: number;
  tokens_out: number;
  turns: number;
  duration_s: number | null;
  started_at: string | null;
  finished_at: string | null;
  pr: { num: number; title: string | null; checks: unknown } | null;
  error: string | null;
  stages: RunStage[];
  config: Record<string, unknown>;
  sandbox: { image: string; mem: string; vcpu: number; health: string };
  artifacts: { name: string; size?: number; live?: boolean }[];
  /** The open pause decision (PauseCard rehydration), or null when not paused. */
  decision?: RunDecision | null;
}

function encodeRepo(slug: string): string {
  // The slug is "owner/name"; encode each segment so the "/" survives as the
  // path separator (the backend routes on /issues/{owner}/{name}/{num}).
  return slug
    .split("/")
    .map((s) => encodeURIComponent(s))
    .join("/");
}

/** Fetch one issue's detail (slice 2.1 — `GET /issues/{owner}/{name}/{num}`). */
export function getIssueDetail(slug: string, num: number): Promise<IssueDetailResponse> {
  return apiGet<IssueDetailResponse>(`/issues/${encodeRepo(slug)}/${num}`);
}

/** Fetch the workflow picker source (slice 4.1 — `GET /workflows`). */
export function listWorkflows(): Promise<WorkflowSummary[]> {
  return apiGet<WorkflowSummary[]>("/workflows");
}

/**
 * Launch a run for an issue (slice 2.1 — `POST /runs`) → the platform UUID.
 *
 * The UI sends the **resolved** agent (`agent === "auto" ? workflow.agent : agent`,
 * FR-03-3); the backend re-validates (§8.10), claims the row (INV-5), starts the
 * engine, and returns `{ run_id }`. A Codex budget/turns body is rejected
 * `400 unsupported_for_agent` (INV-8) and surfaces as an {@link ApiError}.
 */
export function createRun(body: CreateRunRequest): Promise<CreateRunResponse> {
  return apiPost<CreateRunResponse>("/runs", body);
}

/** Fetch the §8.9 run-detail baseline (slice 2.1 — `GET /runs/{id}`). */
export function getRun(runId: string): Promise<RunDetailResponse> {
  return apiGet<RunDetailResponse>(`/runs/${encodeURIComponent(runId)}`);
}

/** The `POST /runs/{id}/stop` 202 body (§8.5). */
export interface StopRunResponse {
  run_id: string;
  status: string;
  /** True when a paused run was force-cancelled (R-7). */
  forced: boolean;
}

/**
 * Stop a running or paused run (slice 2.4 — `POST /runs/{id}/stop`, §8.5).
 *
 * A **paused** run is force-stopped server-side (`RunHandle.stop(force=True)` —
 * the engine checks the cancel only between tasks, so a cooperative stop never
 * fires at `await on_pause`); a running run stops cooperatively. The UI just calls
 * this — the force/cooperative choice is the backend's (driven by run status).
 */
export function stopRun(runId: string): Promise<StopRunResponse> {
  return apiPost<StopRunResponse>(`/runs/${encodeURIComponent(runId)}/stop`);
}

/** The `POST /runs/{id}/answer` 200 body (§8.5/§8.9). */
export interface AnswerRunResponse {
  /** `true` on the winning exactly-once transition (INV-9). */
  resolved: boolean;
}

/**
 * Resolve a run's open pause (slice 2.5 wiring — `POST /runs/{id}/answer`, §8.5).
 *
 * The {@link PauseCard}'s Approve/Ship/Abort actions post the chosen option
 * **value** (`{answers:{question_id: value}, skip_remaining}` — never the label,
 * §6.1). The backend resolves the pending decision **exactly once** (INV-9) and
 * resumes the engine; a double-submit / second tab / racing timeout surfaces as a
 * `409 pause_already_resolved` {@link ApiError}. A state-changing POST — it rides
 * the CSRF-safe {@link apiPost} (INV-1); no token is ever placed in a URL (INV-2).
 */
export function answerRun(runId: string, body: AnswerBody): Promise<AnswerRunResponse> {
  return apiPost<AnswerRunResponse>(`/runs/${encodeURIComponent(runId)}/answer`, body);
}

/** The `POST /runs/{id}/exec` 200 body — a one-shot command's stdout. */
export interface ExecRunResponse {
  run_id: string;
  output: string;
}

/**
 * Run ONE command in the run's container (slice 2.4 — `POST /runs/{id}/exec`).
 *
 * This is a **one-shot** exec (a single `docker exec`), NOT a PTY / interactive
 * terminal: one command in, captured stdout out. Surfaces a 409 when the
 * container is not running and a 400 when the command itself fails.
 */
export function execInRun(runId: string, command: string): Promise<ExecRunResponse> {
  return apiPost<ExecRunResponse>(`/runs/${encodeURIComponent(runId)}/exec`, { command });
}
