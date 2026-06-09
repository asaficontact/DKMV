/**
 * Board column model (§5.3.1 / `data.jsx COLUMNS`) — the six columns left→right,
 * each keyed by its derived `agent:*` board state. The order here is
 * **authoritative** (AC-15 asserts the rendered titles/order match this).
 */
import type { BoardIssue, BoardState } from "../api/board";

export interface BoardColumn {
  /** The §5.3.1 derived `state` value this column holds. */
  id: BoardState;
  /** Column header title (exact §5.3.1 / `COLUMNS` text). */
  title: string;
  /** A one-line hint shown under empty columns (from `COLUMNS.hint`). */
  hint: string;
  /** Only Backlog and Queued accept user drags (FR-02-3 / AC-16). */
  draggable: boolean;
}

/** The six columns, left→right, in `data.jsx COLUMNS` order (§5.3.1). */
export const COLUMNS: readonly BoardColumn[] = [
  { id: "backlog", title: "Backlog", hint: "no agent label", draggable: true },
  { id: "queued", title: "Queued", hint: "ready to run", draggable: true },
  { id: "in_progress", title: "In Progress", hint: "a run is live", draggable: false },
  { id: "needs_you", title: "Needs You", hint: "paused for a decision", draggable: false },
  { id: "in_review", title: "In Review", hint: "PR open", draggable: false },
  { id: "done", title: "Done", hint: "merged", draggable: false },
] as const;

/** Group a flat issue list into per-column buckets, preserving input order. */
export function groupByColumn(issues: readonly BoardIssue[]): Map<BoardState, BoardIssue[]> {
  const buckets = new Map<BoardState, BoardIssue[]>();
  for (const col of COLUMNS) buckets.set(col.id, []);
  for (const issue of issues) {
    const bucket = buckets.get(issue.state);
    if (bucket) bucket.push(issue);
    else buckets.get("backlog")?.push(issue); // defensive: unknown state → Backlog
  }
  return buckets;
}

/** Whether a card may be dragged out of / into the given column (FR-02-3). */
export function isDraggableColumn(state: BoardState): boolean {
  return state === "backlog" || state === "queued";
}
