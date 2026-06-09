/**
 * Runs history table (FR-06-4/5) — ported from `history.jsx RunsHistory`'s table.
 *
 * Columns (FR-06-4): **Run** (id, mono, truncated), **Issue** (`#num title`),
 * **Workflow** ({@link WfChip}), **Agent** ({@link AgentChip}), **Status**
 * ({@link StateBadge} — icon+label), **Cost** (mono `$x.xx`, "—" for Codex —
 * INV-8), **Turns**, **Duration**, **Started**, and a trailing **PR** badge /
 * chevron cell. Sortable headers (`id/status/cost/turns/dur/started`) call back
 * `onSort`; a row click opens the **read-only finished-run view** (`onOpenRun`).
 *
 * Sorting + filtering are owned by the parent {@link History} screen (it holds the
 * sort + filter state and the filtered/sorted rows); this component is the pure
 * render of those rows + the sortable `Th` headers, so a render test can assert a
 * sort toggles the order and a filter narrows the rows (AC-5).
 *
 * **INV-8.** A Codex run's `cost_usd` is `null` → the cell renders **"—"**, never
 * `$0.00`. **INV-14.** No hex literals — all color is token-driven; status is the
 * {@link StateBadge} (icon + label), never color alone.
 */
import { AgentChip, WfChip } from "./chips";
import { ChevRightIcon, ChevDownIcon, PrIcon } from "./icons";
import StateBadge from "./StateBadge";
import type { RunSummary } from "../api/history";

/** The columns a run history page can be sorted on (FR-06-4). */
export type SortKey = "id" | "status" | "cost" | "turns" | "dur" | "started";
export type SortDir = "asc" | "desc";
export interface SortState {
  key: SortKey;
  dir: SortDir;
}

export interface RunsTableProps {
  /** The already-filtered + sorted page rows (parent owns the state). */
  rows: RunSummary[];
  /** Total rows before filtering (for the "{shown} of {total}" caption — parent). */
  sort: SortState;
  /** Toggle/​set the sort key (header click). */
  onSort: (key: SortKey) => void;
  /** Open a run's read-only finished view (row click). */
  onOpenRun: (id: string) => void;
}

/** `{m}m {ss}s` / `{h}h {m}m` duration (matches `history.jsx fmtDur`). */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

/** Truncate a long run id (the table keeps it on one line). */
function shortId(id: string): string {
  return id.length > 30 ? `${id.slice(0, 30)}…` : id;
}

/** A sortable / static header cell. */
function Th({
  children,
  sortKey,
  sort,
  onSort,
  align,
}: {
  children?: React.ReactNode;
  sortKey?: SortKey;
  sort?: SortState;
  onSort?: (key: SortKey) => void;
  align?: "right";
}) {
  const sortable = sortKey != null && onSort != null;
  const active = sortable && sort?.key === sortKey;
  return (
    <th
      className={`runs-th${active ? " is-active" : ""}`}
      data-align={align}
      onClick={sortable ? () => onSort(sortKey) : undefined}
      data-sortable={sortable ? "true" : undefined}
      aria-sort={active ? (sort?.dir === "asc" ? "ascending" : "descending") : undefined}
    >
      <span className="runs-th-inner">
        {children}
        {active && (
          <ChevDownIcon
            size={12}
            className={`runs-th-chev${sort?.dir === "asc" ? " is-asc" : ""}`}
          />
        )}
      </span>
    </th>
  );
}

export default function RunsTable({ rows, sort, onSort, onOpenRun }: RunsTableProps) {
  return (
    <div className="card runs-table-card">
      <div className="runs-table-scroll">
        <table className="runs-table">
          <thead>
            <tr>
              <Th sortKey="id" sort={sort} onSort={onSort}>
                Run
              </Th>
              <Th>Issue</Th>
              <Th>Workflow</Th>
              <Th>Agent</Th>
              <Th sortKey="status" sort={sort} onSort={onSort}>
                Status
              </Th>
              <Th sortKey="cost" sort={sort} onSort={onSort} align="right">
                Cost
              </Th>
              <Th sortKey="turns" sort={sort} onSort={onSort} align="right">
                Turns
              </Th>
              <Th sortKey="dur" sort={sort} onSort={onSort} align="right">
                Duration
              </Th>
              <Th sortKey="started" sort={sort} onSort={onSort}>
                Started
              </Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {rows.map((run) => (
              <tr
                key={run.id}
                className="runs-row"
                onClick={() => onOpenRun(run.id)}
                tabIndex={0}
                role="link"
                onKeyDown={(e) => {
                  if (e.key === "Enter") onOpenRun(run.id);
                }}
              >
                <td className="runs-cell runs-cell-id">
                  <span className="mono runs-id">{shortId(run.id)}</span>
                </td>
                <td className="runs-cell runs-cell-issue">
                  <div className="runs-issue">
                    {run.issue_num != null && (
                      <span className="mono runs-issue-num">#{run.issue_num}</span>
                    )}
                    <span className="runs-issue-title">{run.issue_title ?? ""}</span>
                  </div>
                </td>
                <td className="runs-cell">
                  {run.workflow_id && <WfChip workflowId={run.workflow_id} />}
                </td>
                <td className="runs-cell">
                  <AgentChip agent={run.agent ?? "auto"} />
                </td>
                <td className="runs-cell">
                  <StateBadge status={run.status ?? "queued"} />
                </td>
                <td className="runs-cell runs-cell-num">
                  <span className="mono runs-cost">
                    {run.cost_usd == null ? "—" : `$${run.cost_usd.toFixed(2)}`}
                  </span>
                </td>
                <td className="runs-cell runs-cell-num">
                  <span className="mono runs-dim">{run.turns}</span>
                </td>
                <td className="runs-cell runs-cell-num">
                  <span className="mono runs-dim">{formatDuration(run.duration_s)}</span>
                </td>
                <td className="runs-cell">
                  <span className="mono runs-started">
                    {run.started_at ? run.started_at.slice(5) : "—"}
                  </span>
                </td>
                <td className="runs-cell runs-cell-pr">
                  {run.pr_num != null ? (
                    <span className="badge badge-soft runs-pr">
                      <PrIcon size={11} />#{run.pr_num}
                    </span>
                  ) : (
                    <ChevRightIcon size={15} className="runs-chev" />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
