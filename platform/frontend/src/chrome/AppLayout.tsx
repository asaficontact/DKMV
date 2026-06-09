/**
 * Global chrome wrapper (FR-NAV-1/2) — the `Sidebar + TopBar + main` shell every
 * top-level screen sits inside.
 *
 * **Why this exists (recorded 1.5/2.2 friction).** Board, IssueDetail and now
 * LiveRun all hand-composed `<div class="app-shell"><Sidebar/><div
 * class="app-main"><TopBar/>…` verbatim. Extracting it into one `<AppLayout>`
 * removes that duplication: each screen passes its `title`, the poll-driven
 * `aggregate` for the sidebar live chip, an `onRefresh`, and its body as
 * `children`. The layout owns the `.app-shell` grid + `.app-main` column so the
 * three screens can never drift apart structurally.
 *
 * Pure composition — no color literals (INV-14); all styling is the ported
 * `board.css` / tokens classes.
 */
import type { ReactNode } from "react";

import SkipLink, { MAIN_CONTENT_ID } from "../a11y/SkipLink";
import type { BoardAggregate } from "../api/board";
import Sidebar, { type NavId } from "./Sidebar";
import TopBar from "./TopBar";

import "../screens/board.css";

export interface AppLayoutProps {
  /** The connected repo slug ("owner/name") shown in the sidebar switcher. */
  repoSlug: string;
  /** The page title / breadcrumb for the top bar. */
  title: string;
  /** Which sidebar nav item is the current screen (highlighted + `aria-current`).
   *  Defaults to `board` (the recorded 2.4 nit: the nav is now route-aware). */
  activeNav?: NavId;
  /** Poll-driven aggregate for the sidebar live chip (null while loading / N/A). */
  aggregate?: BoardAggregate | null;
  /** Seconds since the last successful poll, or null (the live run has no poll). */
  lastSyncedSeconds?: number | null;
  /** Manual refresh trigger (re-poll / reload the screen's data). */
  onRefresh?: () => void;
  /** Whether a refresh is in flight (spins the top-bar icon). */
  refreshing?: boolean;
  /** The screen body rendered inside `.app-main`, below the top bar. */
  children: ReactNode;
}

/**
 * Render the `Sidebar + TopBar + main` chrome around a screen's `children`.
 * `onRefresh` defaults to a no-op so a screen with no poll (the live run streams
 * over SSE) can still render the chrome without a refresh affordance doing
 * anything.
 */
export default function AppLayout({
  repoSlug,
  title,
  activeNav = "board",
  aggregate = null,
  lastSyncedSeconds = null,
  onRefresh,
  refreshing,
  children,
}: AppLayoutProps) {
  return (
    <div className="app-shell">
      {/* WCAG 2.4.1 bypass-blocks: the first focusable element jumps a keyboard
          user past the chrome to the screen body (AC-10). */}
      <SkipLink />
      <Sidebar repoSlug={repoSlug} aggregate={aggregate} activeNav={activeNav} />
      <div className="app-main">
        <TopBar
          title={title}
          lastSyncedSeconds={lastSyncedSeconds}
          onRefresh={onRefresh ?? (() => {})}
          refreshing={refreshing}
        />
        {/* The skip-link target landmark: programmatically focusable
            (tabIndex=-1) so the link can move focus here (AC-10). */}
        <main id={MAIN_CONTENT_ID} tabIndex={-1} className="app-main-content">
          {children}
        </main>
      </div>
    </div>
  );
}
