/**
 * Daily spend chart (FR-06-1 / FR-06-1a) — ported from `history.jsx SpendChart`.
 *
 * Renders the Codex-excluded daily spend **series the backend already computed**
 * (`GET /stats.spend_series`) as a bar chart with a total label. The **last bar
 * uses `--accent`**; earlier bars use `color-mix(--accent 45% --surface-3)`
 * (DESIGN_FIDELITY §8). Each bar's height is proportional to the day's spend.
 *
 * **INV-8 / FR-06-1a (binding).** The series is the backend's Codex-**excluded**
 * segment-sum spend — this component never sums a run list or fabricates a Codex
 * `$0` value. A small footnote — **"excludes Codex (cost not reported)"** — makes
 * the exclusion explicit so the operator isn't surprised the spend total is below
 * the visible Codex-run count (the data.jsx Codex `cost` mocks are illustrative
 * only and MUST NOT drive this math).
 *
 * **INV-14.** No hex literals — every color is a token var / `color-mix` of one.
 */
import { ChartIcon } from "./icons";
import type { SpendPoint } from "../api/history";

export interface SpendChartProps {
  /** The Codex-excluded daily spend series from `GET /stats` (oldest-first). */
  series: SpendPoint[];
}

export default function SpendChart({ series }: SpendChartProps) {
  const total = series.reduce((acc, point) => acc + point.usd, 0);
  // Avoid a divide-by-zero on an all-zero / empty series (flat baseline bars).
  const max = series.reduce((acc, point) => Math.max(acc, point.usd), 0) || 1;

  return (
    <div className="card spend-chart">
      <div className="spend-chart-head">
        <span className="cap spend-chart-title">
          <ChartIcon size={14} />
          Spend over time
        </span>
        <span className="mono spend-chart-total">${total.toFixed(2)}</span>
      </div>

      <div className="spend-chart-bars">
        {series.length === 0 ? (
          <span className="cap spend-chart-empty">No spend yet</span>
        ) : (
          series.map((point, i) => {
            const isLast = i === series.length - 1;
            const heightPx = (point.usd / max) * 46 + 6;
            return (
              <div className="spend-chart-col" key={point.date}>
                <div
                  className="spend-chart-bar"
                  data-last={isLast ? "true" : undefined}
                  title={`$${point.usd.toFixed(2)}`}
                  style={{ height: `${heightPx}px` }}
                />
                <span className="mono spend-chart-day">{point.date.slice(5)}</span>
              </div>
            );
          })
        )}
      </div>

      {/* FR-06-1a — make the Codex exclusion explicit (greppable footnote). */}
      <p className="cap spend-chart-foot">excludes Codex (cost not reported)</p>
    </div>
  );
}
