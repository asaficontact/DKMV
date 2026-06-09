/**
 * Board filter bar (FR-02-5) — filter the board by **label / workflow / agent /
 * state**, plus a **"+ Run an issue"** primary action.
 *
 * **Phase boundary.** "+ Run an issue" routes to the issue-detail/launch screen
 * which is Phase 2; in Phase 1 it is a **disabled placeholder** (no dispatch —
 * OUT of scope). The filter selects are functional and drive the parent's
 * in-memory filtering of the polled board list (no extra fetch).
 */
import type { ChangeEvent } from "react";

import type { BoardIssue, BoardState } from "../api/board";
import { COLUMNS } from "./board-model";
import { FilterIcon, PlusIcon, SearchIcon } from "./icons";

export interface BoardFilters {
  text: string;
  label: string;
  workflow: string;
  agent: string;
  state: string;
}

export const EMPTY_FILTERS: BoardFilters = {
  text: "",
  label: "",
  workflow: "",
  agent: "",
  state: "",
};

export interface FilterBarProps {
  filters: BoardFilters;
  onChange: (next: BoardFilters) => void;
  /** Options derived from the loaded issues (so the selects only list real values). */
  labels: string[];
  workflows: string[];
  agents: string[];
}

const STATE_OPTIONS: { value: BoardState; label: string }[] = COLUMNS.map((c) => ({
  value: c.id,
  label: c.title,
}));

export default function FilterBar({
  filters,
  onChange,
  labels,
  workflows,
  agents,
}: FilterBarProps) {
  const set = (key: keyof BoardFilters) => (e: ChangeEvent<HTMLSelectElement | HTMLInputElement>) =>
    onChange({ ...filters, [key]: e.target.value });

  return (
    <div className="filter-bar">
      <label className="filter-search">
        <SearchIcon size={15} />
        <span className="visually-hidden">Search issues</span>
        <input
          className="input filter-search-input"
          type="search"
          placeholder="Search issues…"
          value={filters.text}
          onChange={set("text")}
        />
      </label>

      <span className="filter-icon" aria-hidden>
        <FilterIcon size={15} />
      </span>

      <select className="select filter-select" aria-label="Filter by label" value={filters.label} onChange={set("label")}>
        <option value="">All labels</option>
        {labels.map((l) => (
          <option key={l} value={l}>
            {l}
          </option>
        ))}
      </select>

      <select
        className="select filter-select"
        aria-label="Filter by workflow"
        value={filters.workflow}
        onChange={set("workflow")}
      >
        <option value="">All workflows</option>
        {workflows.map((w) => (
          <option key={w} value={w}>
            {w}
          </option>
        ))}
      </select>

      <select className="select filter-select" aria-label="Filter by agent" value={filters.agent} onChange={set("agent")}>
        <option value="">All agents</option>
        {agents.map((a) => (
          <option key={a} value={a}>
            {a}
          </option>
        ))}
      </select>

      <select className="select filter-select" aria-label="Filter by state" value={filters.state} onChange={set("state")}>
        <option value="">All states</option>
        {STATE_OPTIONS.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>

      <button
        type="button"
        className="btn btn-primary run-issue-cta"
        disabled
        title="Launching a run is Phase 2"
      >
        <PlusIcon size={15} />
        Run an issue
      </button>
    </div>
  );
}

/** Filter a board list in memory by the active filters (case-insensitive text). */
export function applyFilters(issues: readonly BoardIssue[], f: BoardFilters): BoardIssue[] {
  const text = f.text.trim().toLowerCase();
  return issues.filter((issue) => {
    if (text && !`#${issue.num} ${issue.title}`.toLowerCase().includes(text)) return false;
    if (f.label && !issue.labels.includes(f.label)) return false;
    if (f.workflow && issue.workflow_id !== f.workflow) return false;
    if (f.agent && issue.agent !== f.agent) return false;
    if (f.state && issue.state !== f.state) return false;
    return true;
  });
}
