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
import { type DraggableColumn, useRovingTabIndex } from "../a11y";
import {
  type BoardColumn,
  COLUMNS,
  groupByColumn,
  isCostExcludedAgent,
} from "../components/board-model";
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

  // The single Backlog↔Queued move path (FR-02-3 / INV-11 `set_agent_state`),
  // shared by the pointer drop AND the keyboard-drag (AC-10) so there is exactly
  // one place that posts the agent-state change + does the optimistic restate.
  const moveIssue = useCallback(
    async (issue: BoardIssue, column: DraggableColumn) => {
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

  // Drag Backlog↔Queued → POST agent-state, then optimistically restate (FR-02-3).
  const onDropTo = useCallback(
    (column: BoardState) => {
      const issue = dragged.current;
      dragged.current = null;
      if (!issue) return;
      if (column !== "backlog" && column !== "queued") return; // run-driven columns reject drops
      void moveIssue(issue, column);
    },
    [moveIssue],
  );

  // Keyboard-operable Backlog↔Queued move (AC-10) — the card's key handler calls
  // this with the target column; it routes through the SAME `moveIssue` path.
  const onMoveColumn = useCallback(
    (issue: BoardIssue, target: DraggableColumn) => {
      void moveIssue(issue, target);
    },
    [moveIssue],
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
            {COLUMNS.map((col) => (
              <BoardColumnView
                key={col.id}
                col={col}
                cards={buckets.get(col.id) ?? []}
                repoSlug={repoSlug}
                onOpenIssue={openIssue}
                onMoveColumn={onMoveColumn}
                onDropTo={onDropTo}
                onDragPickup={(i) => {
                  dragged.current = i;
                }}
                onDragRelease={() => {
                  dragged.current = null;
                }}
              />
            ))}
          </div>
        )}
    </AppLayout>
  );
}

interface BoardColumnViewProps {
  col: BoardColumn;
  cards: BoardIssue[];
  repoSlug: string;
  onOpenIssue: (issue: BoardIssue) => void;
  onMoveColumn: (issue: BoardIssue, target: DraggableColumn) => void;
  onDropTo: (column: BoardState) => void;
  onDragPickup: (issue: BoardIssue) => void;
  onDragRelease: () => void;
}

/**
 * One board column + its cards. Extracted from {@link Board} so each column can own
 * a {@link useRovingTabIndex} group (a hook can't run inside a `.map`): the cards
 * form a roving-tabindex list so Arrow keys move focus between them and exactly one
 * card is in the tab order (AC-10). Draggable columns also wire the pointer
 * drag/drop; the keyboard move routes through the SAME `onMoveColumn` callback.
 */
function BoardColumnView({
  col,
  cards,
  repoSlug,
  onOpenIssue,
  onMoveColumn,
  onDropTo,
  onDragPickup,
  onDragRelease,
}: BoardColumnViewProps) {
  const liveCost = col.id === "in_progress" ? sumLiveCost(cards) : null;
  const roving = useRovingTabIndex(cards.length);
  return (
    <section
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
      onDrop={col.draggable ? () => onDropTo(col.id) : undefined}
      data-droppable={col.draggable ? "true" : "false"}
    >
      <header className="column-head">
        <span className="column-title">{col.title}</span>
        <span className="column-count mono">{cards.length}</span>
        {liveCost != null && (
          <span className="cap column-cost mono">${liveCost.toFixed(2)}</span>
        )}
      </header>
      <div className="column-cards" ref={roving.containerRef} onKeyDown={roving.onKeyDown}>
        {cards.map((issue, i) => (
          <IssueCard
            key={issue.num}
            issue={issue}
            githubUrl={`https://github.com/${repoSlug}/issues/${issue.num}`}
            onOpenIssue={onOpenIssue}
            onMoveColumn={col.draggable ? onMoveColumn : undefined}
            tabIndex={roving.tabIndexFor(i)}
            onFocusCard={() => roving.setActive(i)}
            onDragStart={onDragPickup}
            onDragEnd={onDragRelease}
          />
        ))}
        {cards.length === 0 && <p className="cap column-hint">{col.hint}</p>}
      </div>
    </section>
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
