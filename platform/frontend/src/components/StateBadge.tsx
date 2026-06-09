/**
 * Shared state badge — **icon + text label, never color alone** (AC-19, INV-14,
 * §7.3 / NFR-A11Y-1). Ported from `components.jsx StateBadge` + the `.state.s-*`
 * palette in `styles.css` (tokens.css). One palette everywhere: board card,
 * sidebar live chip, and (later) run header + history row.
 *
 * The dot pulses on `running`/`paused` (the `.state.s-running`/`.s-paused`
 * keyframes), but the *meaning* is always carried by the icon **and** the text —
 * a colorblind operator reads "Running" / "Needs you", not just a hue.
 */
import type { ComponentType } from "react";

import {
  BoltIcon,
  CheckIcon,
  ClockIcon,
  PauseIcon,
  PrIcon,
  XIcon,
} from "./icons";

/**
 * Engine/board status → one of the seven palette buckets (`components.jsx
 * STATE_OF`). Board column ids + engine `RunStatus` both map here so the same
 * badge renders for an issue card and a run row.
 */
export const STATE_OF: Record<string, StatePalette> = {
  // board column ids
  backlog: "queued",
  queued: "queued",
  progress: "running",
  in_progress: "running",
  needsyou: "paused",
  needs_you: "paused",
  review: "review",
  in_review: "review",
  done: "done",
  // engine RunStatus
  pending: "cancel",
  running: "running",
  paused: "paused",
  stopping: "running",
  completed: "done",
  failed: "failed",
  cancelled: "cancel",
  interrupted: "cancel",
  timed_out: "failed",
};

/** The seven semantic palette buckets (`--st-*` in tokens.css). */
export type StatePalette =
  | "queued"
  | "running"
  | "paused"
  | "review"
  | "done"
  | "failed"
  | "cancel";

/** Human label per status (`components.jsx STATE_LABEL`). */
const STATE_LABEL: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  paused: "Needs you",
  review: "In review",
  done: "Done",
  failed: "Failed",
  cancel: "Cancelled",
  completed: "Completed",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
  timed_out: "Timed out",
  pending: "Pending",
};

/** Icon per palette bucket — so state is conveyed by shape, not color (INV-14). */
const ICON_OF: Record<StatePalette, ComponentType<{ size?: number }>> = {
  queued: ClockIcon,
  running: BoltIcon,
  paused: PauseIcon,
  review: PrIcon,
  done: CheckIcon,
  failed: XIcon,
  cancel: XIcon,
};

export interface StateBadgeProps {
  /** A board column id or an engine `RunStatus`. */
  status: string;
  /** Override the default label text (else derived from `status`). */
  label?: string;
}

/**
 * Render the palette dot (pulses on running/paused via CSS) + the status icon +
 * the text label. The icon carries `data-testid="state-icon"` and the text is a
 * real text node so a render test can assert **both** are present (AC-19).
 */
export default function StateBadge({ status, label }: StateBadgeProps) {
  const palette = STATE_OF[status] ?? "queued";
  const Icon = ICON_OF[palette];
  const text = label ?? STATE_LABEL[status] ?? STATE_LABEL[palette];
  return (
    <span className={`state s-${palette}`}>
      <span className="dot" aria-hidden />
      <span className="state-ico" data-testid="state-icon" aria-hidden>
        <Icon size={13} />
      </span>
      <span className="state-label">{text}</span>
    </span>
  );
}
