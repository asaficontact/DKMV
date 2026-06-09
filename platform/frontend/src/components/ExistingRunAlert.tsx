/**
 * Existing-run alert card (FR-03-1, FR-03-4, AC-7). When the issue already has an
 * active run, this card surfaces it above the body with the run id and a CTA to
 * the live run:
 *
 *   - **paused** variant — amber, "This run is paused and needs your decision",
 *     **Review decision** (the issue is in the "Needs You" column).
 *   - **running** variant — blue, "A run is in progress for this issue",
 *     **Watch live**.
 *
 * State is conveyed by **icon + label**, not color alone (NFR-A11Y-1): the amber
 * variant shows the pause glyph, the blue variant the bolt. All color is
 * token-driven through the `existing-run-alert` / `is-paused` classes (INV-14).
 */
import type { ActiveRun } from "../api/runs";
import { ArrowRightIcon, BoltIcon, PauseIcon } from "./icons";

export interface ExistingRunAlertProps {
  /** The issue's active-run block from `GET /issues/{num}` (§5.4). */
  activeRun: ActiveRun;
  /** Navigate to the live run (the live-run view is slice 2.4; routed by id). */
  onOpen: (runId: string | null | undefined) => void;
}

/** True iff the active run is paused (the amber/Review-decision variant). */
function isPaused(status: string | null): boolean {
  return (status ?? "").toLowerCase() === "paused";
}

export default function ExistingRunAlert({ activeRun, onOpen }: ExistingRunAlertProps) {
  const paused = isPaused(activeRun.status);
  const runId = activeRun.run_id ?? null;
  const Icon = paused ? PauseIcon : BoltIcon;
  const title = paused
    ? "This run is paused and needs your decision"
    : "A run is in progress for this issue";
  const cta = paused ? "Review decision" : "Watch live";

  return (
    <div
      className={`card existing-run-alert${paused ? " is-paused" : " is-running"}`}
      role="status"
      data-variant={paused ? "paused" : "running"}
    >
      <span className="existing-run-icon" aria-hidden>
        <Icon size={18} />
      </span>
      <div className="existing-run-body">
        <div className="existing-run-title">{title}</div>
        {runId && <div className="cap mono existing-run-id">{runId}</div>}
      </div>
      <button type="button" className="btn btn-soft existing-run-cta" onClick={() => onOpen(runId)}>
        {cta}
        <ArrowRightIcon size={15} />
      </button>
    </div>
  );
}
