/**
 * Keyboard-operable Backlog↔Queued "drag" for the board (AC-10, FR-02-3,
 * NFR-A11Y-1 / INV-14, DESIGN_FIDELITY §8).
 *
 * The board's pointer drag (HTML5 drag-and-drop) is unreachable by keyboard, so
 * this primitive gives the **same** Backlog↔Queued move a keyboard affordance: a
 * focused, draggable card responds to a move key (Space/Enter to pick up + move,
 * or the bracket/arrow shortcut) by invoking the SAME `onMoveColumn` callback the
 * pointer drop uses — there is exactly ONE move path (the `POST
 * /issues/{num}/agent-state` the column already wires). The run-driven columns are
 * not keyboard-movable (they reject drops too).
 *
 * This is additive: the board passes `onMoveColumn`, and the card spreads
 * {@link keyboardDragProps} onto its `<article>`. No copy is changed and no color
 * literal is introduced (the focus ring comes from the `--accent-ring` token).
 */
import type { KeyboardEvent } from "react";

/** The two board columns a card can be keyboard-moved between (mirrors FR-02-3). */
export type DraggableColumn = "backlog" | "queued";

/** Is `state` one of the two keyboard-movable (draggable) columns? */
export function isKeyboardMovable(state: string): state is DraggableColumn {
  return state === "backlog" || state === "queued";
}

/** The other draggable column — the target a Backlog↔Queued move lands in. */
export function otherColumn(state: DraggableColumn): DraggableColumn {
  return state === "backlog" ? "queued" : "backlog";
}

/**
 * The keyboard shortcuts that trigger a Backlog↔Queued move on a focused card:
 *  - `]` / `ArrowRight` — move toward Queued (Backlog → Queued);
 *  - `[` / `ArrowLeft`  — move toward Backlog (Queued → Backlog);
 *  - `Enter` / `Space`  — toggle to the other column (a simple pick-up-and-drop).
 *
 * A move that would be a no-op (already in the target column) is ignored. The
 * handler calls `onMoveColumn(target)` — the same callback the pointer drop uses —
 * so there is a single move path (INV-11's `set_agent_state` replace-all underneath).
 */
export function handleKeyboardDrag(
  event: KeyboardEvent,
  state: string,
  onMoveColumn: (target: DraggableColumn) => void,
): boolean {
  if (!isKeyboardMovable(state)) return false;
  const key = event.key;
  let target: DraggableColumn | null = null;
  if (key === "]" || key === "ArrowRight") target = "queued";
  else if (key === "[" || key === "ArrowLeft") target = "backlog";
  else if (key === "Enter" || key === " " || key === "Spacebar") target = otherColumn(state);
  else return false;
  if (target === state) {
    // Already in the target column → no-op, but still consume the key so the
    // browser doesn't scroll on Space.
    event.preventDefault();
    return true;
  }
  event.preventDefault();
  onMoveColumn(target);
  return true;
}

export interface KeyboardDragProps {
  /** The card is in the keyboard tab order so it can receive the move keys. */
  tabIndex: number;
  /** Announce the move affordance to AT (so it is not a silent key trap). */
  "aria-keyshortcuts": string;
  /** The keydown handler that performs the Backlog↔Queued move. */
  onKeyDown: (event: KeyboardEvent) => void;
}

/**
 * Build the props a draggable card spreads onto its element to become
 * keyboard-movable. `tabIndex` lets the roving-tabindex hook override it (pass the
 * hook's `tabIndexFor(i)` so only the active card is in the tab order); it
 * defaults to `0` for a standalone card.
 */
export function keyboardDragProps(
  state: string,
  onMoveColumn: (target: DraggableColumn) => void,
  tabIndex = 0,
): KeyboardDragProps | Record<string, never> {
  if (!isKeyboardMovable(state)) return {};
  return {
    tabIndex,
    "aria-keyshortcuts": "ArrowLeft ArrowRight Enter Space",
    onKeyDown: (event: KeyboardEvent) => handleKeyboardDrag(event, state, onMoveColumn),
  };
}
