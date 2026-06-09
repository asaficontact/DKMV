/**
 * Stage tracker (FR-04-3, AC-16) — the workflow stepper ported from `run.jsx
 * StageTracker`.
 *
 * One step per workflow stage with a per-stage status — **done ✓ / running ● /
 * paused ⏸ / pending ○** — conveyed by **icon + label**, never color alone
 * (INV-14 / NFR-A11Y-1). A non-pending stage shows `${cost} · {turns}t · {dur}`
 * and is **clickable** to expand its detail; a pending stage is inert.
 *
 * Data is the §8.9 `stages: RunStage[]` array (`{idx, name, status, cost_usd,
 * turns, duration_s}`). All color comes from the `--st-*` state tokens; the
 * running/paused dots pulse (the shared `pulse-dot` keyframe).
 */
import { useState } from "react";

import type { RunStage } from "../api/runs";
import { CheckIcon, PauseIcon } from "./icons";

export interface StageTrackerProps {
  stages: RunStage[];
}

type StageStatus = "done" | "running" | "paused" | "pending" | "failed";

function normStatus(status: string): StageStatus {
  const s = status.toLowerCase();
  if (s === "done" || s === "completed") return "done";
  if (s === "running") return "running";
  if (s === "paused") return "paused";
  if (s === "failed") return "failed";
  return "pending";
}

/** `{m}m {ss}s` from seconds, or null when no duration yet. */
function formatDur(seconds: number | null): string | null {
  if (seconds == null) return null;
  const safe = Math.max(0, Math.floor(seconds));
  const m = Math.floor(safe / 60);
  const s = safe % 60;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

/** The status sub-line per stage (`$x.xx · {turns}t · {dur}`). */
function stageMeta(stage: RunStage): string | null {
  const dur = formatDur(stage.duration_s);
  if (stage.cost_usd == null && stage.turns === 0 && dur == null) return null;
  const parts: string[] = [];
  if (stage.cost_usd != null) parts.push(`$${stage.cost_usd.toFixed(2)}`);
  parts.push(`${stage.turns}t`);
  if (dur) parts.push(dur);
  return parts.join(" · ");
}

/** The status word (icon's text companion — state is never color-only, INV-14). */
const STATUS_WORD: Record<StageStatus, string> = {
  done: "done",
  running: "running",
  paused: "paused",
  pending: "pending",
  failed: "failed",
};

export default function StageTracker({ stages }: StageTrackerProps) {
  const [open, setOpen] = useState<number | null>(null);

  if (stages.length === 0) {
    return (
      <div className="stage-tracker stage-tracker-empty">
        <span className="cap">Stages appear as the run progresses…</span>
      </div>
    );
  }

  return (
    <div className="stage-tracker" role="list" aria-label="Run stages">
      {stages.map((stage, i) => {
        const status = normStatus(stage.status);
        const clickable = status !== "pending";
        const meta = stageMeta(stage);
        const expanded = open === i;
        return (
          <div className="stage-step" role="listitem" key={stage.idx}>
            <button
              type="button"
              className={`stage-node s-${status}${expanded ? " is-open" : ""}`}
              disabled={!clickable}
              aria-expanded={clickable ? expanded : undefined}
              onClick={() => clickable && setOpen(expanded ? null : i)}
            >
              <span className={`stage-dot s-${status}`} aria-hidden>
                <StageIcon status={status} />
              </span>
              <span className="stage-text">
                <span className="stage-name">{stage.name || `Stage ${stage.idx + 1}`}</span>
                {/* The status word — icon + label, so state never relies on color (INV-14). */}
                <span className="cap stage-status" data-testid="stage-status">
                  {STATUS_WORD[status]}
                </span>
                {meta && <span className="mono cap stage-meta">{meta}</span>}
              </span>
            </button>
            {i < stages.length - 1 && <span className="stage-connector" aria-hidden />}
            {expanded && meta && (
              <div className="stage-detail card fade-in">
                <span className="mono cap">{meta}</span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** The per-status glyph (done ✓ / running ● / paused ⏸ / pending ○). */
function StageIcon({ status }: { status: StageStatus }) {
  if (status === "done") return <CheckIcon size={12} />;
  if (status === "paused") return <PauseIcon size={11} />;
  if (status === "running") return <span className="stage-glyph-running" aria-hidden />;
  if (status === "failed") return <span className="stage-glyph-failed" aria-hidden>!</span>;
  return <span className="stage-glyph-pending" aria-hidden />;
}
