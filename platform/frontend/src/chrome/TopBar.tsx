/**
 * Global top bar (FR-NAV-2). Breadcrumb / page title on the left; on the right a
 * **Refresh** affordance with a "last synced 12s ago" indicator (the board/chip
 * **poll** for updates — FR-NAV-2, not SSE), a **theme** control (dark default
 * mode toggle + the six-skin picker, FR-NAV-3 / AC-13), and the GitHub account
 * avatar.
 *
 * All color is token-driven (INV-14); the skin swatches reference `--skin-accent-*`
 * vars from tokens.css. The theme toggle defaults to **dark** and persists via
 * `useTheme` → `theme.ts` (`dkmv-mode`/`dkmv-skin`).
 */
import { useEffect, useRef, useState } from "react";

import { SKINS, type Skin } from "../app/theme";
import { useTheme } from "../app/useTheme";
import { GitHubIcon, MoonIcon, RefreshIcon, SunIcon } from "../components/icons";

const SKIN_LABEL: Record<Skin, string> = {
  indigo: "Indigo",
  ember: "Ember",
  evergreen: "Evergreen",
  graphite: "Graphite",
  plum: "Plum",
  rose: "Rose",
};

export interface TopBarProps {
  /** The page title / breadcrumb (e.g. the repo slug + "Board"). */
  title: string;
  /** Seconds since the last successful poll (for "last synced Ns ago"). */
  lastSyncedSeconds: number | null;
  /** Trigger a manual refresh (re-poll the board + aggregate). */
  onRefresh: () => void;
  /** Whether a refresh is in flight (spins the icon, disables the button). */
  refreshing?: boolean;
}

function syncedLabel(seconds: number | null): string {
  if (seconds == null) return "syncing…";
  if (seconds < 5) return "synced just now";
  if (seconds < 60) return `last synced ${seconds}s ago`;
  const mins = Math.floor(seconds / 60);
  return `last synced ${mins}m ago`;
}

export default function TopBar({ title, lastSyncedSeconds, onRefresh, refreshing }: TopBarProps) {
  const { mode, skin, toggleMode, setSkin } = useTheme();

  return (
    <header className="topbar">
      <div className="topbar-title">
        <span className="topbar-breadcrumb">{title}</span>
      </div>

      <div className="topbar-actions">
        <div className="topbar-sync">
          <button
            type="button"
            className="btn btn-ghost btn-icon"
            onClick={onRefresh}
            disabled={refreshing}
            aria-label="Refresh board"
            title="Refresh"
          >
            <RefreshIcon size={16} className={refreshing ? "spin" : undefined} />
          </button>
          <span className="cap" role="status" aria-live="polite">
            {syncedLabel(lastSyncedSeconds)}
          </span>
        </div>

        <SkinPicker skin={skin} mode={mode} onPick={setSkin} />

        <button
          type="button"
          className="btn btn-soft btn-icon"
          onClick={toggleMode}
          aria-label={mode === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          title={mode === "dark" ? "Light mode" : "Dark mode"}
        >
          {mode === "dark" ? <SunIcon size={16} /> : <MoonIcon size={16} />}
        </button>

        <span className="topbar-avatar" aria-label="GitHub account" title="GitHub account">
          <GitHubIcon size={18} />
        </span>
      </div>
    </header>
  );
}

/** The six-skin theme picker (components.jsx ThemePicker), token-swatched. */
function SkinPicker({
  skin,
  mode,
  onPick,
}: {
  skin: Skin;
  mode: string;
  onPick: (skin: Skin) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="skin-picker" ref={ref}>
      <button
        type="button"
        className="btn btn-soft skin-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        title="Theme"
      >
        <span className="skin-swatch" style={{ background: `var(--skin-accent-${skin})` }} aria-hidden />
        <span className="skin-name">{SKIN_LABEL[skin]}</span>
      </button>
      {open && (
        <div className="skin-pop card fade-in" role="menu">
          <div className="cap skin-pop-head">Theme · {mode}</div>
          <div className="skin-grid">
            {SKINS.map((s) => (
              <button
                key={s}
                type="button"
                role="menuitemradio"
                aria-checked={s === skin}
                className={`skin-option${s === skin ? " is-active" : ""}`}
                onClick={() => {
                  onPick(s);
                  setOpen(false);
                }}
              >
                <span
                  className="skin-swatch-lg"
                  style={{ background: `var(--skin-accent-${s})` }}
                  aria-hidden
                />
                <span className="skin-option-name">{SKIN_LABEL[s]}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
