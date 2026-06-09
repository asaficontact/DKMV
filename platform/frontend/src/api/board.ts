/**
 * Board API surface (Screen 02, FR-02). Thin typed wrappers over the generic
 * {@link apiGet}/{@link apiPost} client:
 *
 *   - `GET  /repos/{repo}/issues`              — the board list (slice 1.2).
 *   - `GET  /repos/{repo}/board/aggregate`     — poll-driven strip/chip counters (slice 1.5).
 *   - `POST /issues/{repo}/{num}/agent-state`  — the Backlog↔Queued drag (slice 1.3).
 *
 * Everything here is **poll-driven** — there is no `EventSource` in the board /
 * chrome (AC-20); only the single run view (Phase 2) holds an SSE stream.
 */
import { apiGet, apiPost } from "./client";

/** A board issue row (the §5.3.1-derived list shape; `data.jsx ISSUES`). */
export interface BoardIssue {
  num: number;
  title: string;
  labels: string[];
  /** The derived board column (§5.3.1): backlog|queued|in_progress|needs_you|in_review|done. */
  state: BoardState;
  workflow_id: string | null;
  agent: string | null;
  pr_num: number | null;
  run_status: string | null;
  /** Live mini-meter fields (present only while a run is live — Phase 2 populates). */
  live_cost?: number | null;
  live_turns?: number | null;
  progress?: number | null;
  assignee?: string | null;
}

/** The six §5.3.1 board states, in left→right column order. */
export type BoardState =
  | "backlog"
  | "queued"
  | "in_progress"
  | "needs_you"
  | "in_review"
  | "done";

/** The `GET /repos/{repo}/issues` envelope. */
export interface BoardListResponse {
  items: BoardIssue[];
  next_cursor: string | null;
}

/** The `GET /repos/{repo}/board/aggregate` counters (FR-02-4, AC-17). */
export interface BoardAggregate {
  repo: string;
  in_progress: number;
  needs_you: number;
  /** Excludes $0-cost Codex runs (FR-06-1a / INV-8). */
  spent_today: number;
  /** Counts every run's tokens, Codex included (FR-06-1a). */
  tokens_today: number;
}

/** The Backlog↔Queued drag target (FR-02-3). */
export type AgentStateTarget = "queued" | "none";

/** The `POST /issues/{repo}/{num}/agent-state` response. */
export interface AgentStateResponse {
  repo: string;
  num: number;
  agent_label: string | null;
  labels: string[];
}

function encodeRepo(slug: string): string {
  // The slug is "org/name"; encode each segment so the "/" survives as a path
  // separator (the backend routes on /{owner}/{name}).
  return slug
    .split("/")
    .map((s) => encodeURIComponent(s))
    .join("/");
}

/** Fetch the board list for a repo (slice 1.2 — `GET /repos/{repo}/issues`). */
export function listBoardIssues(slug: string): Promise<BoardListResponse> {
  return apiGet<BoardListResponse>(`/repos/${encodeRepo(slug)}/issues`);
}

/** Fetch the poll-driven aggregate counters (slice 1.5 — `GET …/board/aggregate`). */
export function getBoardAggregate(slug: string): Promise<BoardAggregate> {
  return apiGet<BoardAggregate>(`/repos/${encodeRepo(slug)}/board/aggregate`);
}

/**
 * Drag an issue Backlog↔Queued (slice 1.3 — `POST …/agent-state`).
 *
 * `target: "queued"` sets `agent:queued` (→ Queued); `target: "none"` clears it
 * (→ Backlog). The backend routes the replace-all `PUT .../labels` through the
 * serialized write-queue (INV-11). No token ever rides a URL (INV-2).
 */
export function setAgentState(
  slug: string,
  num: number,
  target: AgentStateTarget,
): Promise<AgentStateResponse> {
  return apiPost<AgentStateResponse>(`/issues/${encodeRepo(slug)}/${num}/agent-state`, {
    target,
  });
}
