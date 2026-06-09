/**
 * Retry-queue card (FR-06-3) — ported from `history.jsx RetryQueue`.
 *
 * A collapsible card (amber / `--st-paused` border + badges) listing the runs that
 * exhausted ≤3 retry attempts and are parked awaiting a manual **"Retry now"**.
 * Each row shows `#issue`, `attempt {attempt}/3 · due in {dueIn}`, and the last
 * error. The header carries a count badge and a chevron that rotates open/closed.
 *
 * **Retry now (FR-06-3).** The per-row action posts `POST /runs/{id}/retry` via
 * {@link retryRun} (the endpoint ships in slice 3.4 — INV-15; the call is wired
 * here so the card is functional the moment 3.4 lands). It is idempotent
 * server-side (a second click while a retry is pending is a no-op). On success we
 * call `onRetried` so the parent can re-poll the queue + stats.
 *
 * **INV-14.** No hex literals — the amber accent is the `--st-paused` token;
 * state is conveyed by the icon + the "attempt N/3" label, never color alone.
 */
import { useState } from "react";

import { ChevDownIcon, RetryIcon } from "./icons";
import { type RetryEntry, retryRun } from "../api/history";

export interface RetryQueueProps {
  /** The retry-queue rows from `GET /retry-queue` (empty until 3.4 populates it). */
  entries: RetryEntry[];
  /** Called after a successful "Retry now" so the parent can re-poll. */
  onRetried?: () => void;
}

export default function RetryQueue({ entries, onRetried }: RetryQueueProps) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);

  const onRetry = async (id: string) => {
    setPending(id);
    try {
      await retryRun(id);
      onRetried?.();
    } catch {
      // The next poll reflects reality; never throw out of a click handler.
    } finally {
      setPending(null);
    }
  };

  return (
    <div className="card retry-queue">
      <button
        type="button"
        className="retry-queue-head"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <RetryIcon size={15} />
        <span className="retry-queue-title">Retry queue</span>
        <span className="badge retry-queue-count">{entries.length}</span>
        <ChevDownIcon
          size={15}
          className={`retry-queue-chev${open ? " is-open" : ""}`}
        />
      </button>

      {open && (
        <div className="fade-in retry-queue-body">
          {entries.length === 0 ? (
            <p className="cap retry-queue-empty">No retries pending</p>
          ) : (
            entries.map((entry) => (
              <div className="retry-queue-row" key={entry.id}>
                <div className="retry-queue-row-top">
                  <span className="mono retry-queue-issue">#{entry.issue}</span>
                  <span className="badge retry-queue-attempt">
                    attempt {entry.attempt}/3 · due in {entry.dueIn}
                  </span>
                </div>
                <div className="cap retry-queue-error">{entry.lastError}</div>
                <button
                  type="button"
                  className="btn btn-soft btn-sm retry-queue-action"
                  onClick={() => void onRetry(entry.id)}
                  disabled={pending === entry.id}
                >
                  <RetryIcon size={13} />
                  {pending === entry.id ? "Retrying…" : "Retry now"}
                </button>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
