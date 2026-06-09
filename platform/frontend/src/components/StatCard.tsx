/**
 * Aggregate stat card (FR-06-1) — ported from `history.jsx StatCard`.
 *
 * One of the five cards on the Runs history screen (Total runs / Success rate /
 * Total spend / Tokens / Agent-hours). An optional `accentVar` tints the icon
 * chip + the big value (Success rate → `--st-done`, Total spend → `--accent`); the
 * default is the neutral `--text-3`. An optional `sub` line sits under the value
 * (e.g. "{n} completed").
 *
 * **INV-14.** No hex literals — the accent is a **token variable name**
 * (`"var(--accent)"` / `"var(--st-done)"`), and the icon-chip tint is a
 * `color-mix` of that token. State/meaning is carried by the icon + the label,
 * never color alone. Numbers use the mono/`tnum` class (§7.5).
 */
import type { ComponentType } from "react";

export interface StatCardProps {
  /** The card's leading icon (token-colored via `currentColor`). */
  Icon: ComponentType<{ size?: number }>;
  /** The card label (e.g. "Total runs"). */
  label: string;
  /** The big mono value (already formatted: `"42"`, `"86%"`, `"$128.40"`, `"1.2k"`). */
  value: string;
  /** A token color variable name to tint the icon + value (default neutral). */
  accentVar?: string;
  /** Optional sub-line under the value. */
  sub?: string;
}

export default function StatCard({ Icon, label, value, accentVar, sub }: StatCardProps) {
  // The accent is always a token *variable name* — never a hex literal (INV-14).
  const accent = accentVar ?? "var(--text-3)";
  return (
    <div className="card stat-card">
      <div className="stat-card-head">
        <span
          className="stat-card-ico"
          style={{
            // color-mix over the token var (resolves at render; no hex here).
            background: `color-mix(in oklab, ${accent} 14%, transparent)`,
            color: accent,
          }}
          aria-hidden
        >
          <Icon size={15} />
        </span>
        <span className="cap stat-card-label">{label}</span>
      </div>
      <div className="mono stat-card-value" style={{ color: accent }}>
        {value}
      </div>
      {sub && <div className="cap stat-card-sub">{sub}</div>}
    </div>
  );
}
