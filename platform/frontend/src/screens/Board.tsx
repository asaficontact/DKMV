/**
 * Screen 02 — Board (HOME) (FR-02, §5.3.1). The control plane: GitHub issues as
 * cards in **six columns** keyed by `agent:*` state (Backlog · Queued · In
 * Progress · Needs You · In Review · Done), with the global chrome (Sidebar +
 * TopBar) wrapped around it.
 *
 * **Poll-driven, never SSE (AC-20).** The board list, the aggregate strip, and
 * the sidebar live chip all refresh on a **poll cadence** (the TopBar "last
 * synced" indicator) via plain `fetch`. No server-sent-events stream is opened
 * anywhere in this file or the chrome — the single open run view is the only SSE
 * holder (Phase 2).
 *
 * **Drag (FR-02-3 / AC-16).** Cards are draggable **only** between Backlog and
 * Queued; dropping onto the other column posts `POST /issues/{num}/agent-state`
 * (`target: "queued"` to enter Queued, `target: "none"` to return to Backlog) →
 * the `set_agent_state` replace-all primitive (INV-11). The other four columns
 * are run-driven and reject drops.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import "./board.css";
import {
  type BoardAggregate,
  type BoardIssue,
  type BoardState,
  getBoardAggregate,
  listBoardIssues,
  setAgentState,
} from "../api/board";
import { COLUMNS, groupByColumn, isCostExcludedAgent } from "../components/board-model";
import AggregateStrip from "../components/AggregateStrip";
import FilterBar, { applyFilters, EMPTY_FILTERS, type BoardFilters } from "../components/FilterBar";
import IssueCard from "../components/IssueCard";
import AppLayout from "../chrome/AppLayout";

/** Poll cadence for the board + aggregate (FR-NAV-2 "last synced"). */
const POLL_MS = 10_000;

type LoadPhase = "syncing" | "ready" | "error";

export interface BoardProps {
  /** The connected repo slug ("org/name"). */
  repoSlug: string;
}

export default function Board({ repoSlug }: BoardProps) {
  const navigate = useNavigate();
  const [issues, setIssues] = useState<BoardIssue[]>([]);
  const [aggregate, setAggregate] = useState<BoardAggregate | null>(null);
  const [phase, setPhase] = useState<LoadPhase>("syncing");
  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(null);
  const [nowTick, setNowTick] = useState(() => Date.now());
  const [refreshing, setRefreshing] = useState(false);
  const [filters, setFilters] = useState<BoardFilters>(EMPTY_FILTERS);
  const dragged = useRef<BoardIssue | null>(null);

  const poll = useCallback(
    async (manual: boolean) => {
      if (manual) setRefreshing(true);
      try {
        const [list, agg] = await Promise.all([
          listBoardIssues(repoSlug),
          getBoardAggregate(repoSlug),
        ]);
        setIssues(list.items);
        setAggregate(agg);
        setLastSyncedAt(Date.now());
        setPhase("ready");
      } catch {
        // Keep the last good board on a transient poll error; only the very
        // first load surfaces the error state.
        setPhase((prev) => (prev === "syncing" ? "error" : prev));
      } finally {
        if (manual) setRefreshing(false);
      }
    },
    [repoSlug],
  );

  // Initial load + the poll loop (poll-driven; no SSE — AC-20).
  useEffect(() => {
    void poll(false);
    const id = setInterval(() => void poll(false), POLL_MS);
    return () => clearInterval(id);
  }, [poll]);

  // A 1s tick so "last synced Ns ago" counts up between polls.
  useEffect(() => {
    const id = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const lastSyncedSeconds =
    lastSyncedAt == null ? null : Math.max(0, Math.floor((nowTick - lastSyncedAt) / 1000));

  const filtered = useMemo(() => applyFilters(issues, filters), [issues, filters]);
  const buckets = useMemo(() => groupByColumn(filtered), [filtered]);

  const filterOptions = useMemo(() => deriveFilterOptions(issues), [issues]);

  // Drag Backlog↔Queued → POST agent-state, then optimistically restate (FR-02-3).
  const onDropTo = useCallback(
    async (column: BoardState) => {
      const issue = dragged.current;
      dragged.current = null;
      if (!issue) return;
      if (column !== "backlog" && column !== "queued") return; // run-driven columns reject drops
      if (issue.state === column) return;
      const target = column === "queued" ? "queued" : "none";
      // Optimistic move so the card snaps immediately; reconcile on the next poll.
      setIssues((prev) =>
        prev.map((it) => (it.num === issue.num ? { ...it, state: column } : it)),
      );
      try {
        await setAgentState(repoSlug, issue.num, target);
      } catch {
        // Revert on failure; the next poll is the source of truth.
        setIssues((prev) =>
          prev.map((it) => (it.num === issue.num ? { ...it, state: issue.state } : it)),
        );
      }
    },
    [repoSlug],
  );

  // Open the issue-detail / launch screen (Screen 03 — slice 2.2). The actual
  // dispatch happens there via the run panel, never from the board.
  const openIssue = useCallback(
    (issue: BoardIssue) => {
      const [owner, name] = repoSlug.split("/");
      navigate(
        `/issues/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/${issue.num}`,
      );
    },
    [navigate, repoSlug],
  );

  const isEmpty = phase === "ready" && issues.length === 0;

  return (
    <AppLayout
      repoSlug={repoSlug}
      title={`${repoSlug} · Board`}
      aggregate={aggregate}
      lastSyncedSeconds={lastSyncedSeconds}
      onRefresh={() => void poll(true)}
      refreshing={refreshing}
    >
      <div className="board-toolbar">
          <FilterBar
            filters={filters}
            onChange={setFilters}
            labels={filterOptions.labels}
            workflows={filterOptions.workflows}
            agents={filterOptions.agents}
          />
          <AggregateStrip aggregate={aggregate} />
        </div>

        {phase === "syncing" && <SyncingState />}
        {phase === "error" && <ErrorState onRetry={() => void poll(true)} />}
        {isEmpty && <EmptyState />}

        {phase === "ready" && issues.length > 0 && (
          <div className="board-columns" role="list">
            {COLUMNS.map((col) => {
              const cards = buckets.get(col.id) ?? [];
              const liveCost = col.id === "in_progress" ? sumLiveCost(cards) : null;
              return (
                <section
                  key={col.id}
                  className={`board-column col-${col.id}`}
                  role="listitem"
                  aria-label={col.title}
                  onDragOver={
                    col.draggable
                      ? (e) => {
                          e.preventDefault();
                          if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
                        }
                      : undefined
                  }
                  onDrop={col.draggable ? () => void onDropTo(col.id) : undefined}
                  data-droppable={col.draggable ? "true" : "false"}
                >
                  <header className="column-head">
                    <span className="column-title">{col.title}</span>
                    <span className="column-count mono">{cards.length}</span>
                    {liveCost != null && (
                      <span className="cap column-cost mono">${liveCost.toFixed(2)}</span>
                    )}
                  </header>
                  <div className="column-cards">
                    {cards.map((issue) => (
                      <IssueCard
                        key={issue.num}
                        issue={issue}
                        githubUrl={`https://github.com/${repoSlug}/issues/${issue.num}`}
                        onOpenIssue={openIssue}
                        onDragStart={(i) => {
                          dragged.current = i;
                        }}
                        onDragEnd={() => {
                          dragged.current = null;
                        }}
                      />
                    ))}
                    {cards.length === 0 && <p className="cap column-hint">{col.hint}</p>}
                  </div>
                </section>
              );
            })}
          </div>
        )}
    </AppLayout>
  );
}

/** Sum the live cost across running cards (the In-Progress header figure). */
function sumLiveCost(cards: readonly BoardIssue[]): number {
  return cards.reduce((acc, c) => {
    // Codex contributes $0 to the spend figure (INV-8 / FR-06-1a).
    if (isCostExcludedAgent(c.agent)) return acc;
    return acc + (c.live_cost ?? 0);
  }, 0);
}

function deriveFilterOptions(issues: readonly BoardIssue[]) {
  const labels = new Set<string>();
  const workflows = new Set<string>();
  const agents = new Set<string>();
  for (const issue of issues) {
    issue.labels.forEach((l) => labels.add(l));
    if (issue.workflow_id) workflows.add(issue.workflow_id);
    if (issue.agent) agents.add(issue.agent);
  }
  return {
    labels: [...labels].sort(),
    workflows: [...workflows].sort(),
    agents: [...agents].sort(),
  };
}

/** Syncing state (FR-02-6) — the brief import-in-progress shimmer. */
function SyncingState() {
  return (
    <div className="board-state board-syncing">
      <div className="run-bar board-syncing-bar" />
      <p className="cap">Importing your issues…</p>
    </div>
  );
}

/** Empty state (FR-02-6) — friendly, with the verbatim AC-18 copy. */
function EmptyState() {
  return (
    <div className="board-state board-empty">
      <h2 className="board-empty-title">No issues yet</h2>
      <p className="board-empty-copy">Create an issue on GitHub or import to get started.</p>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="board-state board-error" role="alert">
      <h2 className="board-empty-title">Couldn’t load the board</h2>
      <p className="cap">We hit a snag reaching the control plane.</p>
      <button type="button" className="btn btn-soft" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}
