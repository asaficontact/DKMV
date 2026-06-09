/**
 * Board issue card (FR-02-2). Number + title; up to ~2 GitHub label pills
 * (colored from the `--lbl-*` token map, §7.4); a workflow chip + agent chip when
 * assigned; a **live mini-meter** (turn count + running cost + a thin progress
 * bar with the running pulse) when a run is live; an assignee avatar; and a "⋯"
 * menu (Assign workflow, Run, Open on GitHub, Stop).
 *
 * **Phase boundary.** Run / Stop are **disabled placeholders** here — dispatch is
 * Phase 2 (OUT of scope). "Needs You" cards get amber treatment + a **Review
 * decision** button whose CTA target is also Phase 2 (disabled placeholder).
 *
 * Drag: Backlog↔Queued cards are `draggable`; the column wires the actual
 * `dragstart`/`drop` (FR-02-3). All color is token-driven (INV-14).
 */
import { useEffect, useRef, useState } from "react";

import type { BoardIssue } from "../api/board";
import { isDraggableColumn } from "./board-model";
import { AgentChip, Avatar, GhLabel, WfChip } from "./chips";
import { DotsIcon, ExtIcon, FlowIcon, PlayIcon, StopIcon } from "./icons";

const MAX_LABELS = 2;

export interface IssueCardProps {
  issue: BoardIssue;
  /** GitHub web URL for "Open on GitHub" (built from the repo slug + number). */
  githubUrl?: string;
  /** Begin a Backlog↔Queued drag (the column owns the drop side). */
  onDragStart?: (issue: BoardIssue) => void;
  onDragEnd?: () => void;
}

export default function IssueCard({ issue, githubUrl, onDragStart, onDragEnd }: IssueCardProps) {
  const draggable = isDraggableColumn(issue.state);
  const running = issue.state === "in_progress";
  const needsYou = issue.state === "needs_you";

  return (
    <article
      className={`issue-card${needsYou ? " is-needsyou" : ""}`}
      draggable={draggable}
      onDragStart={
        draggable
          ? (e) => {
              // `dataTransfer` is always present in a real browser drag; jsdom's
              // synthetic event omits it, so guard before touching it.
              if (e.dataTransfer) {
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", String(issue.num));
              }
              onDragStart?.(issue);
            }
          : undefined
      }
      onDragEnd={draggable ? onDragEnd : undefined}
      data-state={issue.state}
      data-num={issue.num}
    >
      <header className="issue-card-top">
        <span className="issue-num mono">#{issue.num}</span>
        <CardMenu issue={issue} githubUrl={githubUrl} />
      </header>

      <h3 className="issue-title">{issue.title}</h3>

      {issue.labels.length > 0 && (
        <div className="issue-labels">
          {issue.labels.slice(0, MAX_LABELS).map((name) => (
            <GhLabel key={name} name={name} />
          ))}
          {issue.labels.length > MAX_LABELS && (
            <span className="cap">+{issue.labels.length - MAX_LABELS}</span>
          )}
        </div>
      )}

      {(issue.workflow_id || issue.agent) && (
        <div className="issue-chips">
          {issue.workflow_id && <WfChip workflowId={issue.workflow_id} />}
          {issue.agent && <AgentChip agent={issue.agent} />}
        </div>
      )}

      {running && <LiveMiniMeter issue={issue} />}

      {needsYou && (
        <button
          type="button"
          className="btn btn-soft btn-sm review-cta"
          disabled
          title="Review decision opens the run view (Phase 2)"
        >
          Review decision
        </button>
      )}

      <footer className="issue-card-foot">
        {issue.assignee && <Avatar initials={issue.assignee} size={22} />}
      </footer>
    </article>
  );
}

/** The thin live meter (turn count + running cost + pulsing progress bar). */
function LiveMiniMeter({ issue }: { issue: BoardIssue }) {
  const turns = issue.live_turns ?? 0;
  const cost = issue.live_cost;
  const progress = Math.max(0, Math.min(1, issue.progress ?? 0));
  // Codex reports $0 cost → render "—" not "$0.00" (INV-8 / FR-06-1a).
  const isCodex = (issue.agent ?? "").toLowerCase() === "codex";
  const costText = isCodex || cost == null ? "—" : `$${cost.toFixed(2)}`;
  return (
    <div className="mini-meter">
      <div className="mini-meter-row">
        <span className="mono mini-meter-turns">{turns}t</span>
        <span className="mono mini-meter-cost">{costText}</span>
      </div>
      <div
        className="run-bar mini-meter-bar"
        role="progressbar"
        aria-valuenow={Math.round(progress * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      />
    </div>
  );
}

/** The "⋯" card menu — Run/Stop are disabled placeholders in Phase 1. */
function CardMenu({ issue, githubUrl }: { issue: BoardIssue; githubUrl?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="card-menu" ref={ref}>
      <button
        type="button"
        className="btn btn-ghost btn-icon"
        aria-label={`Actions for issue ${issue.num}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        <DotsIcon size={16} />
      </button>
      {open && (
        <div className="card-menu-pop card fade-in" role="menu">
          <button type="button" className="card-menu-item" role="menuitem" disabled>
            <FlowIcon size={15} />
            Assign workflow
          </button>
          <button
            type="button"
            className="card-menu-item"
            role="menuitem"
            disabled
            title="Launching runs is Phase 2"
          >
            <PlayIcon size={15} />
            Run
          </button>
          {githubUrl && (
            <a
              className="card-menu-item"
              role="menuitem"
              href={githubUrl}
              target="_blank"
              rel="noreferrer"
            >
              <ExtIcon size={15} />
              Open on GitHub
            </a>
          )}
          <button
            type="button"
            className="card-menu-item is-danger"
            role="menuitem"
            disabled
            title="Stopping a run is Phase 2"
          >
            <StopIcon size={15} />
            Stop
          </button>
        </div>
      )}
    </div>
  );
}
