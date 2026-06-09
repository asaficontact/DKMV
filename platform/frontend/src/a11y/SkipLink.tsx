/**
 * "Skip to main content" link (AC-10, NFR-A11Y-1 / WCAG 2.4.1 bypass-blocks).
 *
 * The first focusable element on every screen: visually hidden until focused, it
 * lets a keyboard user jump past the Sidebar + TopBar straight to the screen body
 * instead of tabbing through the whole chrome on every page. Rendered by
 * {@link AppLayout} ahead of the chrome; the layout marks the screen body with the
 * matching `id` so the link target exists.
 *
 * Token-only styling (INV-14): the focused chip uses `--surface`/`--accent`/
 * `--accent-fg` via the `.skip-link` rule in `board.css` — no hardcoded hex here.
 */

/** The id of the main-content landmark the skip link focuses. */
export const MAIN_CONTENT_ID = "main-content";

export interface SkipLinkProps {
  /** The skip target id (defaults to {@link MAIN_CONTENT_ID}). */
  targetId?: string;
  /** Override the link text (defaults to "Skip to main content"). */
  label?: string;
}

/**
 * Render the skip link. On activation it focuses the target landmark (which
 * {@link AppLayout} renders with `tabIndex={-1}` so it is programmatically
 * focusable) and scrolls it into view, so the next Tab lands inside the screen body.
 */
export default function SkipLink({
  targetId = MAIN_CONTENT_ID,
  label = "Skip to main content",
}: SkipLinkProps) {
  return (
    <a
      className="skip-link"
      href={`#${targetId}`}
      onClick={(event) => {
        const target = document.getElementById(targetId);
        if (target) {
          event.preventDefault();
          target.focus();
          target.scrollIntoView();
        }
      }}
    >
      {label}
    </a>
  );
}
