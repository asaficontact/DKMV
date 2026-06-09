/**
 * Board aggregate strip (FR-02-4) — the compact, Symphony-style at-a-glance line:
 *
 *   "{in_progress} in progress · {needs_you} needs you ·
 *    ${spent_today} spent today · {tokens_today} tokens."
 *
 * **Poll-driven** (AC-20): the strip reads the `GET …/board/aggregate` counters
 * that the parent polls — there is **no** `EventSource` here. The backend already
 * applies the **Codex caveat** (FR-06-1a / INV-8): `spent_today` **excludes**
 * $0-cost Codex runs from the spend figure while their tokens still count in
 * `tokens_today`. We surface that with a small "excludes Codex (cost not
 * reported)" footnote so the figure is never silently wrong (the exclusion is
 * computed server-side in `app/api/board.py`).
 */
import type { BoardAggregate } from "../api/board";

export interface AggregateStripProps {
  aggregate: BoardAggregate | null;
}

function fmtTokens(n: number): string {
  return n.toLocaleString();
}

export default function AggregateStrip({ aggregate }: AggregateStripProps) {
  if (!aggregate) {
    return (
      <div className="aggregate-strip" aria-hidden>
        <span className="skel agg-skel" />
      </div>
    );
  }
  const { in_progress, needs_you, spent_today, tokens_today } = aggregate;
  return (
    <div className="aggregate-strip" role="status" aria-live="polite">
      <span className="agg-item">
        <span className="mono">{in_progress}</span> in progress
      </span>
      <span className="agg-sep" aria-hidden>
        ·
      </span>
      <span className="agg-item">
        <span className="mono">{needs_you}</span> needs you
      </span>
      <span className="agg-sep" aria-hidden>
        ·
      </span>
      <span className="agg-item">
        <span className="mono">${spent_today.toFixed(2)}</span> spent today
      </span>
      <span className="agg-sep" aria-hidden>
        ·
      </span>
      <span className="agg-item">
        <span className="mono">{fmtTokens(tokens_today)}</span> tokens
      </span>
      {/* Codex caveat (FR-06-1a / INV-8): spend excludes $0-cost Codex runs. */}
      <span className="cap agg-foot" title="Codex reports $0 cost — its spend is excluded, its tokens still count">
        excludes Codex (cost not reported)
      </span>
    </div>
  );
}
