/**
 * Focus-management primitives for the keyboard-accessibility pass (AC-10,
 * NFR-A11Y-1 / INV-14, DESIGN_FIDELITY §8).
 *
 * These are **additive** helpers the existing screens opt into — they add focus
 * order + a roving-tabindex pattern without rewriting any component's markup or
 * copy (so 5.2's run-panel copy is untouched). No color literals live here (a
 * focus *ring* is sourced from the `--accent-ring` / `--accent-soft` tokens in
 * `tokens.css`, never a hardcoded hex — INV-14).
 *
 * Surface:
 *  - {@link FOCUSABLE_SELECTOR} — the selector for natively-focusable descendants.
 *  - {@link getFocusable} — collect the visible, focusable elements in a container.
 *  - {@link useRovingTabIndex} — a roving-tabindex hook for a 1-D list (board
 *    column cards / a radio-group of decision options): exactly one item is in the
 *    tab order at a time; Arrow keys move focus between items (WAI-ARIA pattern).
 *  - {@link moveFocus} — focus the element at an index, clamped to the list.
 */
import { useCallback, useEffect, useRef, useState } from "react";

/** CSS selector matching the natively keyboard-focusable elements in a subtree. */
export const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
  '[role="button"]:not([aria-disabled="true"])',
].join(",");

/**
 * Collect the visible, focusable descendants of `container` in DOM order.
 * Elements hidden via `display:none` (offsetParent === null) are skipped so the
 * tab order matches what a sighted+keyboard user actually sees.
 */
export function getFocusable(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  const nodes = Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  );
  return nodes.filter((el) => el.offsetParent !== null || el === document.activeElement);
}

/** Focus the element at `index`, clamped to `[0, items.length - 1]`. */
export function moveFocus(items: readonly HTMLElement[], index: number): number {
  if (items.length === 0) return -1;
  const clamped = Math.max(0, Math.min(items.length - 1, index));
  items[clamped]?.focus();
  return clamped;
}

/** The keys the roving-tabindex hook treats as "move to next / previous". */
const NEXT_KEYS = new Set(["ArrowDown", "ArrowRight"]);
const PREV_KEYS = new Set(["ArrowUp", "ArrowLeft"]);

export interface RovingTabIndex {
  /** The active item index (the one item with `tabIndex=0`). */
  activeIndex: number;
  /** `tabIndex` for the item at `index` (0 for the active one, -1 otherwise). */
  tabIndexFor: (index: number) => 0 | -1;
  /** Mark `index` active (e.g. on focus/click) without moving DOM focus. */
  setActive: (index: number) => void;
  /** Keydown handler: Arrow keys move the roving focus; Home/End jump to ends. */
  onKeyDown: (event: React.KeyboardEvent) => void;
  /** Ref to attach to the container whose focusable children are the roving list. */
  containerRef: React.RefObject<HTMLDivElement>;
}

/**
 * Roving-tabindex over a 1-D list of `count` items (WAI-ARIA composite-widget
 * keyboard pattern). Exactly one item carries `tabIndex=0`; Arrow keys move the
 * roving focus to the next/previous focusable child of the container, Home/End
 * jump to the first/last. The hook owns only focus *movement* — the caller still
 * renders the items and wires `tabIndex={tabIndexFor(i)}` + `onFocus={() =>
 * setActive(i)}`. Wrapping is off (clamped) so Arrow-up at the top is a no-op
 * rather than wrapping to the bottom (matches the board's top-to-bottom card flow).
 */
export function useRovingTabIndex(count: number): RovingTabIndex {
  const containerRef = useRef<HTMLDivElement>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  // Clamp the active index if the list shrinks under it (cards drained/added).
  useEffect(() => {
    setActiveIndex((i) => (count === 0 ? 0 : Math.min(i, count - 1)));
  }, [count]);

  const setActive = useCallback((index: number) => {
    setActiveIndex(Math.max(0, index));
  }, []);

  const tabIndexFor = useCallback(
    (index: number): 0 | -1 => (index === activeIndex ? 0 : -1),
    [activeIndex],
  );

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      const items = getFocusable(containerRef.current);
      if (items.length === 0) return;
      const currentDom = items.indexOf(document.activeElement as HTMLElement);
      const current = currentDom >= 0 ? currentDom : activeIndex;
      let next = current;
      if (NEXT_KEYS.has(event.key)) next = current + 1;
      else if (PREV_KEYS.has(event.key)) next = current - 1;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = items.length - 1;
      else return;
      event.preventDefault();
      const moved = moveFocus(items, next);
      if (moved >= 0) setActiveIndex(moved);
    },
    [activeIndex],
  );

  return { activeIndex, tabIndexFor, setActive, onKeyDown, containerRef };
}
