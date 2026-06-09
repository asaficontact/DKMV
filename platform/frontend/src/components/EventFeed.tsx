/**
 * Event feed (FR-04-4, AC-14) — the live auto-scrolling stream ported from
 * `run.jsx`'s feed, with a **Friendly | Raw** toggle and a search filter.
 *
 * **Friendly** derives a `kind / icon / text / tool` from the outer event's
 * `event_type` + `data` and renders a human row.
 *
 * **Raw (AC-14, binding)** renders the **inner `RuntimeEvent.data` dict** — the
 * `{type, subtype, content, tool_name?, total_cost_usd?, num_turns}` JSON line per
 * §6.4 — **not** the outer wrapper. The Raw `<pre>` carries
 * `data-testid="raw-line"` so a render test can assert its keys match the inner
 * shape.
 *
 * **Auto-scroll** pins to the newest event while the run is live; a search box
 * filters by the friendly text / inner content. All color is token-driven
 * (INV-14) — the per-kind hue is a `--st-*` var on the row, never a hex literal.
 */
import { useEffect, useMemo, useRef } from "react";

import type { RuntimeEvent } from "../api/sse";
import { CheckIcon, SearchIcon, SparkleIcon } from "./icons";

export interface EventFeedProps {
  events: RuntimeEvent[];
  /** Friendly (false) vs Raw (true) view. */
  raw: boolean;
  onRawChange: (raw: boolean) => void;
  /** Search query filtering the visible rows. */
  query: string;
  onQueryChange: (q: string) => void;
  /** Auto-scroll to the newest event (true while the run is live). */
  live: boolean;
}

type FriendlyKind = "system" | "assistant" | "tool" | "ok" | "error" | "decision" | "result";

/** Map an outer `event_type` to a friendly kind bucket (for the `--st-*` hue). */
function friendlyKind(event: RuntimeEvent): FriendlyKind {
  const t = (event.event_type || event.data.type || "").toLowerCase();
  if (t.includes("error") || t === "task_failed") return "error";
  if (t === "result" || t === "task_completed") return "result";
  if (t.includes("decision") || t.includes("pause")) return "decision";
  if (t.includes("tool")) return "tool";
  if (t === "assistant") return "assistant";
  if (t === "user" || t === "tool_result") return "ok";
  return "system";
}

/** The human one-liner for a friendly row (`content` or a derived summary). */
function friendlyText(event: RuntimeEvent): string {
  if (event.content) return event.content;
  const inner = event.data;
  if (typeof inner.content === "string" && inner.content) return inner.content;
  return event.event_type || inner.type || "event";
}

/** The tool name badge, when the inner line carries one. */
function toolName(event: RuntimeEvent): string | null {
  const tn = event.data.tool_name;
  return typeof tn === "string" && tn ? tn : null;
}

/** `mm:ss` timestamp tag from the event sequence/turns (mono). */
function rowTime(event: RuntimeEvent): string {
  const t = event.timestamp ? new Date(event.timestamp) : null;
  if (t && !Number.isNaN(t.getTime())) {
    const mm = String(t.getMinutes()).padStart(2, "0");
    const ss = String(t.getSeconds()).padStart(2, "0");
    return `${mm}:${ss}`;
  }
  return `#${event.sequence}`;
}

/**
 * The inner `RuntimeEvent.data` dict the Raw line renders (AC-14). Picks exactly
 * the §6.4 inner keys (`type/subtype/content/tool_name?/total_cost_usd?/num_turns`)
 * so the Raw view is the inner agent line, not the outer wrapper.
 */
export function rawInnerLine(event: RuntimeEvent): Record<string, unknown> {
  const d = event.data;
  const line: Record<string, unknown> = {
    type: d.type ?? event.event_type,
    subtype: d.subtype ?? null,
    content: d.content ?? event.content ?? "",
    num_turns: d.num_turns ?? event.turns,
  };
  if (d.tool_name != null) line.tool_name = d.tool_name;
  if (d.total_cost_usd != null) line.total_cost_usd = d.total_cost_usd;
  return line;
}

export default function EventFeed({
  events,
  raw,
  onRawChange,
  query,
  onQueryChange,
  live,
}: EventFeedProps) {
  const feedRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return events;
    return events.filter((e) => {
      const hay = `${friendlyText(e)} ${e.event_type} ${JSON.stringify(e.data)}`.toLowerCase();
      return hay.includes(q);
    });
  }, [events, query]);

  // Auto-scroll to the newest event while live.
  useEffect(() => {
    if (live && feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [filtered, live]);

  return (
    <div className="event-feed">
      <div className="event-feed-head">
        <h3 className="event-feed-title">
          Event stream
          {live && <span className="event-live-dot" aria-hidden />}
        </h3>
        <div className="event-search">
          <SearchIcon size={13} />
          <input
            className="input event-search-input"
            placeholder="Filter events…"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            aria-label="Filter events"
          />
        </div>
        <div className="event-toggle" role="tablist" aria-label="Event view">
          <button
            type="button"
            role="tab"
            aria-selected={!raw}
            className={`event-toggle-btn${!raw ? " is-active" : ""}`}
            onClick={() => onRawChange(false)}
          >
            <SparkleIcon size={13} /> Friendly
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={raw}
            className={`event-toggle-btn${raw ? " is-active" : ""}`}
            onClick={() => onRawChange(true)}
          >
            <CheckIcon size={13} /> Raw
          </button>
        </div>
      </div>

      <div className={`event-feed-body${raw ? " is-raw" : ""}`} ref={feedRef}>
        {filtered.length === 0 && <p className="cap event-empty">No events yet.</p>}
        {raw
          ? filtered.map((e) => (
              <pre className="event-raw-line" data-testid="raw-line" key={`${e.id}-${e.sequence}`}>
                {JSON.stringify(rawInnerLine(e))}
              </pre>
            ))
          : filtered.map((e) => {
              const kind = friendlyKind(e);
              const tool = toolName(e);
              return (
                <div className={`event-row kind-${kind}`} key={`${e.id}-${e.sequence}`}>
                  <span className="mono event-time">{rowTime(e)}</span>
                  <span className="event-text">{friendlyText(e)}</span>
                  {tool && <span className="mono badge badge-soft event-tool">{tool}</span>}
                </div>
              );
            })}
      </div>
    </div>
  );
}
