/**
 * Meters row (FR-04-2, §8.3) — ported from `run.jsx`'s meter strip.
 *
 * Renders **elapsed** (`{m}m {ss}s`), **cost** (`$x.xx`, accent when the run is
 * live), **tokens (in · out)**, **turns**, and an **overall progress** bar with a
 * percentage. All numbers are mono + tabular (`tnum`) so they don't jitter as they
 * tick.
 *
 * **INV-7 (binding).** The cost shown is the **segment-sum** value the backend
 * computed (`RunDetailResponse.cost_usd`) — NOT a raw per-task `cost_usd` field.
 * So it climbs across stage boundaries toward the run total and never resets.
 *
 * **INV-8 (binding).** A Codex run's cost is **"—" (not `$0.00`)** and is excluded
 * from spend — driven by `costExcluded` (the run's cost is unpriced), distinct
 * from a Claude run that genuinely cost `$0` so far. Tokens still render for Codex.
 *
 * **INV-14.** No hex literals — every color is a token (`--st-running` accent when
 * live, surface/text vars otherwise); state is conveyed by the labelled meter, not
 * color alone.
 */
import { BoltIcon, ClockIcon, CoinIcon } from "./icons";

export interface MetersRowProps {
  /** Whether the run is live (running) — accents the cost + animates progress. */
  live: boolean;
  /** Elapsed seconds (the live view ticks this client-side between fetches). */
  elapsedSeconds: number;
  /** The SEGMENT-SUM cost (INV-7), or null for a Codex run → render "—" (INV-8). */
  costUsd: number | null;
  /** True when the run's cost is excluded from spend (Codex) → force "—". */
  costExcluded?: boolean;
  tokensIn: number;
  tokensOut: number;
  turns: number;
  /** Overall progress 0..1 (done stages / total). */
  progress: number;
  /** Terminal status so the bar colors done/failed distinctly (icon+label elsewhere). */
  status?: string;
}

/** `{m}m {ss}s` elapsed clock (matches `run.jsx fmtClock`). */
export function formatClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(safe / 60);
  const s = safe % 60;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

/** Group-of-3 thousands separator for token/turn counts (`tnum` mono). */
export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

/** `$x.xx`, or **"—"** when the cost is excluded/unknown (Codex — INV-8). */
export function formatCost(costUsd: number | null, costExcluded?: boolean): string {
  if (costExcluded || costUsd == null) return "—";
  return `$${costUsd.toFixed(2)}`;
}

export default function MetersRow({
  live,
  elapsedSeconds,
  costUsd,
  costExcluded,
  tokensIn,
  tokensOut,
  turns,
  progress,
  status,
}: MetersRowProps) {
  const pct = Math.round(Math.min(1, Math.max(0, progress)) * 100);
  const barClass =
    status === "failed"
      ? "meter-bar-fill is-failed"
      : status === "completed"
        ? "meter-bar-fill is-done"
        : "meter-bar-fill is-running";

  return (
    <div className="meters-row" role="group" aria-label="Run meters">
      <Meter Icon={ClockIcon} label="elapsed">
        <span className="mono tnum">{formatClock(elapsedSeconds)}</span>
      </Meter>
      <Meter Icon={CoinIcon} label="cost" accent={live && !costExcluded}>
        <span className="mono tnum meter-cost" data-live={live ? "true" : "false"}>
          {formatCost(costUsd, costExcluded)}
        </span>
      </Meter>
      <Meter Icon={BoltIcon} label="tokens (in · out)">
        <span className="mono tnum">
          {formatCount(tokensIn)} · {formatCount(tokensOut)}
        </span>
      </Meter>
      <Meter Icon={BoltIcon} label="turns">
        <span className="mono tnum">{formatCount(turns)}</span>
      </Meter>

      <div className="meter-progress">
        <div className="meter-progress-head">
          <span className="cap">overall progress</span>
          <span className="mono tnum meter-progress-pct">{pct}%</span>
        </div>
        <div
          className="meter-bar"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div className={barClass} style={{ width: `${pct}%` }}>
            {live && <span className="meter-bar-shine" aria-hidden />}
          </div>
        </div>
      </div>
    </div>
  );
}

/** One labelled meter cell (icon + value + caption). */
function Meter({
  Icon,
  label,
  accent,
  children,
}: {
  Icon: (p: { size?: number }) => JSX.Element;
  label: string;
  accent?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={`meter${accent ? " is-accent" : ""}`}>
      <div className="meter-head">
        <Icon size={13} />
        <span className="cap">{label}</span>
      </div>
      <div className="meter-value">{children}</div>
    </div>
  );
}
