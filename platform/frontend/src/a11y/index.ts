/**
 * Accessibility primitives (AC-10, NFR-A11Y-1 / INV-14, DESIGN_FIDELITY §8).
 *
 * Additive, token-only helpers the existing screens opt into — focus management +
 * a roving-tabindex hook (`focus`), the keyboard-operable Backlog↔Queued move
 * (`keyboard-drag`), and the skip link (`SkipLink`). None of these change any
 * component's copy or introduce a color literal.
 */
export {
  FOCUSABLE_SELECTOR,
  getFocusable,
  moveFocus,
  useRovingTabIndex,
  type RovingTabIndex,
} from "./focus";
export {
  handleKeyboardDrag,
  isKeyboardMovable,
  keyboardDragProps,
  otherColumn,
  type DraggableColumn,
  type KeyboardDragProps,
} from "./keyboard-drag";
export { default as SkipLink, MAIN_CONTENT_ID } from "./SkipLink";
