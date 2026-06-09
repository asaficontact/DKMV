/**
 * Global left sidebar (FR-NAV-1). Top: a **project switcher** (repo name +
 * avatar). A global **"+ New run"** button. Primary nav: **Board / Runs /
 * Workflows / Settings**. Bottom: a **live-status chip** —
 * "{running} running · ${spent} · {needs_you} needs you" — that uses an **amber
 * dot + count when paused** (a run needs the operator), reusing the shared
 * `StateBadge` palette (AC-19).
 *
 * **Route-aware nav (3.2 — the recorded 2.4 nit).** The current screen is passed
 * as `activeNav`; the matching nav item highlights (`is-active` + `aria-current`).
 * **Board**, **Runs** (Phase 3), and **Workflows** (Phase 4) are live nav targets —
 * clicking navigates via the router (carrying the connected `?repo=` so the chrome
 * stays scoped). **Settings** remains a disabled placeholder (a later screen).
 * The chip is **poll-driven** (AC-20) — it reads the aggregate the parent polls.
 */
import { useInRouterContext, useNavigate } from "react-router-dom";

import { Avatar } from "../components/chips";
import { BoardIcon, FlowIcon, PlusIcon, RunsIcon, SettingsIcon } from "../components/icons";
import StateBadge from "../components/StateBadge";
import type { BoardAggregate } from "../api/board";

/** The four primary nav targets (the `activeNav` discriminant). */
export type NavId = "board" | "runs" | "workflows" | "settings";

export interface SidebarProps {
  /** The connected project slug ("org/name"); shown in the switcher. */
  repoSlug: string;
  /** Poll-driven aggregate for the live-status chip (null while loading). */
  aggregate: BoardAggregate | null;
  /** The current screen's nav id (highlighted). Defaults to `board`. */
  activeNav?: NavId;
}

interface NavItem {
  id: NavId;
  label: string;
  Icon: (p: { size?: number }) => JSX.Element;
  /** A live (clickable) nav target; disabled placeholders set this false. */
  enabled: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { id: "board", label: "Board", Icon: BoardIcon, enabled: true },
  { id: "runs", label: "Runs", Icon: RunsIcon, enabled: true },
  { id: "workflows", label: "Workflows", Icon: FlowIcon, enabled: true },
  { id: "settings", label: "Settings", Icon: SettingsIcon, enabled: false },
];

export default function Sidebar({ repoSlug, aggregate, activeNav = "board" }: SidebarProps) {
  const [org, name] = repoSlug.includes("/") ? repoSlug.split("/") : ["", repoSlug];
  const initials = (name || repoSlug).slice(0, 2).toUpperCase();

  // `useNavigate` throws outside a `<Router>` (the production chrome always mounts
  // under `<BrowserRouter>`, but a standalone screen render in some unit tests has
  // no router). `useInRouterContext` is a single, **unconditional** hook (called
  // every render, rules-of-hooks safe) that selects which nav variant to render:
  // the route-aware `RouterNav` (which calls `useNavigate` unconditionally within
  // itself, only ever mounted under a Router) or the inert `InertNav` (standalone).
  const inRouter = useInRouterContext();

  return (
    <nav className="sidebar" aria-label="Primary">
      <button type="button" className="project-switcher" title="Switch project">
        <Avatar initials={initials} size={28} />
        <span className="project-meta">
          <span className="project-name">{name || repoSlug}</span>
          {org && <span className="cap project-org">{org}</span>}
        </span>
      </button>

      <button
        type="button"
        className="btn btn-primary new-run-btn"
        disabled
        title="Launching a run is Phase 2"
      >
        <PlusIcon size={15} />
        New run
      </button>

      {inRouter ? (
        <RouterNav repoSlug={repoSlug} activeNav={activeNav} />
      ) : (
        <InertNav activeNav={activeNav} />
      )}

      <div className="sidebar-foot">
        <LiveStatusChip aggregate={aggregate} />
      </div>
    </nav>
  );
}

/** The shared nav `<ul>` markup — a single source for the router-aware + inert variants. */
function NavList({ activeNav, go }: { activeNav: NavId; go: (id: NavId) => void }) {
  return (
    <ul className="sidebar-nav">
      {NAV_ITEMS.map(({ id, label, Icon, enabled }) => {
        const active = id === activeNav;
        return (
          <li key={id}>
            <button
              type="button"
              className={`nav-item${active ? " is-active" : ""}`}
              aria-current={active ? "page" : undefined}
              disabled={!enabled}
              onClick={enabled ? () => go(id) : undefined}
              title={enabled ? label : `${label} (coming soon)`}
            >
              <Icon size={17} />
              <span>{label}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The route-aware nav. **Only rendered under a `<Router>`**, so `useNavigate` is
 * called **unconditionally** here (rules-of-hooks safe) — never guarded behind a
 * `useInRouterContext` branch in the same component. Clicking a live nav item
 * navigates, carrying the connected `?repo=` so the destination stays scoped.
 */
function RouterNav({ repoSlug, activeNav }: { repoSlug: string; activeNav: NavId }) {
  const navigate = useNavigate();
  const repoQuery = repoSlug ? `?repo=${encodeURIComponent(repoSlug)}` : "";
  const go = (id: NavId) => {
    if (id === "board") navigate(`/board${repoQuery}`);
    else if (id === "runs") navigate(`/runs${repoQuery}`);
    else if (id === "workflows") navigate(`/workflows${repoQuery}`);
  };
  return <NavList activeNav={activeNav} go={go} />;
}

/**
 * The inert nav variant for a **standalone** (no-Router) render — some unit tests
 * mount a screen without a `<BrowserRouter>`. It calls **no** router hook, so it
 * never throws; live nav items render as inert (a no-op `go`) rather than crash.
 */
function InertNav({ activeNav }: { activeNav: NavId }) {
  const go = () => {};
  return <NavList activeNav={activeNav} go={go} />;
}

/**
 * The bottom live-status chip (FR-NAV-1). Shows running count + spend + a
 * needs-you count; when any run is **paused** ("needs you"), it surfaces the
 * amber `paused` StateBadge (icon + label, never color alone — AC-19) so a
 * waiting decision is unmissable.
 */
function LiveStatusChip({ aggregate }: { aggregate: BoardAggregate | null }) {
  if (!aggregate) {
    return <span className="skel chip-skel" aria-hidden />;
  }
  const { in_progress, needs_you, spent_today } = aggregate;
  const paused = needs_you > 0;
  return (
    <button type="button" className="live-chip" title="Jump to active work">
      <StateBadge status={paused ? "paused" : "running"} label={paused ? "Needs you" : "Running"} />
      <span className="cap live-chip-meta">
        <span className="mono">{in_progress}</span> running
        {" · "}
        <span className="mono">${spent_today.toFixed(2)}</span>
        {paused && (
          <>
            {" · "}
            <span className="mono live-chip-needs">{needs_you}</span> needs you
          </>
        )}
      </span>
    </button>
  );
}
