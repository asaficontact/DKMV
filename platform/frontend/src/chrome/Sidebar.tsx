/**
 * Global left sidebar (FR-NAV-1). Top: a **project switcher** (repo name +
 * avatar). A global **"+ New run"** button. Primary nav: **Board / Runs /
 * Workflows / Settings**. Bottom: a **live-status chip** —
 * "{running} running · ${spent} · {needs_you} needs you" — that uses an **amber
 * dot + count when paused** (a run needs the operator), reusing the shared
 * `StateBadge` palette (AC-19).
 *
 * **Phase boundary.** "+ New run" routes to the Phase-2 launch screen → it is a
 * **disabled placeholder** here (no dispatch — OUT of scope). Runs / Workflows /
 * Settings nav targets are Phase 2/3 screens; in Phase 1 only **Board** is live,
 * the rest are disabled nav items. The chip is **poll-driven** (AC-20) — it reads
 * the aggregate the parent polls; no server-sent-events stream is opened here.
 */
import { Avatar } from "../components/chips";
import { BoardIcon, FlowIcon, PlusIcon, RunsIcon, SettingsIcon } from "../components/icons";
import StateBadge from "../components/StateBadge";
import type { BoardAggregate } from "../api/board";

export interface SidebarProps {
  /** The connected project slug ("org/name"); shown in the switcher. */
  repoSlug: string;
  /** Poll-driven aggregate for the live-status chip (null while loading). */
  aggregate: BoardAggregate | null;
}

const NAV_ITEMS = [
  { id: "board", label: "Board", Icon: BoardIcon, active: true },
  { id: "runs", label: "Runs", Icon: RunsIcon, active: false },
  { id: "workflows", label: "Workflows", Icon: FlowIcon, active: false },
  { id: "settings", label: "Settings", Icon: SettingsIcon, active: false },
] as const;

export default function Sidebar({ repoSlug, aggregate }: SidebarProps) {
  const [org, name] = repoSlug.includes("/") ? repoSlug.split("/") : ["", repoSlug];
  const initials = (name || repoSlug).slice(0, 2).toUpperCase();

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

      <ul className="sidebar-nav">
        {NAV_ITEMS.map(({ id, label, Icon, active }) => (
          <li key={id}>
            <button
              type="button"
              className={`nav-item${active ? " is-active" : ""}`}
              aria-current={active ? "page" : undefined}
              disabled={!active}
              title={active ? label : `${label} (Phase 2)`}
            >
              <Icon size={17} />
              <span>{label}</span>
            </button>
          </li>
        ))}
      </ul>

      <div className="sidebar-foot">
        <LiveStatusChip aggregate={aggregate} />
      </div>
    </nav>
  );
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
