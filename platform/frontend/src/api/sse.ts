/**
 * Live-run SSE consumer (slice 2.4, §8.3 / §6.4) — the EventSource client behind
 * the live run view.
 *
 * **INV-2 (binding).** Auth rides the HttpOnly `SameSite=Strict` cookie the
 * backend sets on connect; we open the stream with `withCredentials: true` so the
 * browser sends it. The token is **NEVER** placed in the URL/query — a `?token=`
 * would leak the loopback control-plane credential into proxy logs and the
 * append-only `events` table (a permanent leak). The connect path is just
 * `GET /api/v1/runs/{id}/events`; no token, ever.
 *
 * **Reconnect / replay.** The browser's native `EventSource` automatically
 * reconnects and replays `Last-Event-ID` (the last SSE message `id`, which IS the
 * `events.id` cursor — §8.3). We do NOT pass a `lastEventId` query param (that
 * would put cursor state in the URL and fight the native header); the backend
 * reads the `Last-Event-ID` request header the browser sends on reconnect and
 * resumes the durable backlog after it. Each parsed message carries its `id` so a
 * consumer can dedup if it also rehydrated from `GET /runs/{id}` state.
 *
 * The message body is the **outer** `RuntimeEvent` (§6.4): `sequence, timestamp,
 * run_id, task_name, task_index, event_type, data{}, content, cost_usd, turns`.
 * The Raw event-feed toggle renders the **inner** `data` dict (AC-14).
 */
import { API_BASE, openEventStream } from "./client";

/** The inner agent line the engine streams (`RuntimeEvent.data`, §6.4). The Raw
 * feed toggle renders exactly this dict (`type/subtype/content/tool_name?/num_turns`). */
export interface RuntimeEventData {
  type?: string;
  subtype?: string;
  content?: string;
  tool_name?: string | null;
  num_turns?: number;
  total_cost_usd?: number;
  [key: string]: unknown;
}

/** The outer `RuntimeEvent` the SSE body carries (§6.4). */
export interface RuntimeEvent {
  /** The monotonic `events.id` (the SSE message id / `Last-Event-ID` cursor). */
  id: number;
  sequence: number;
  timestamp: string;
  run_id: string;
  task_name: string;
  task_index: number;
  event_type: string;
  /** The inner agent line the Raw toggle renders (AC-14). */
  data: RuntimeEventData;
  content: string;
  /** Cumulative-per-task cost; the live meter is the segment-sum, not this field. */
  cost_usd: number;
  turns: number;
}

/** Handlers a {@link subscribeRunEvents} caller supplies. */
export interface RunStreamHandlers {
  /** One parsed `RuntimeEvent` (id = the SSE message id = the `events.id` cursor). */
  onEvent: (event: RuntimeEvent) => void;
  /** The stream opened (first connect or a reconnect). */
  onOpen?: () => void;
  /** A transport error; `EventSource` will auto-reconnect (replaying Last-Event-ID). */
  onError?: (err: Event) => void;
}

/** The path for a run's SSE stream — NO token, NO cursor query (INV-2). */
export function runEventsPath(runId: string): string {
  return `/runs/${encodeURIComponent(runId)}/events`;
}

/**
 * Open the live SSE stream for a run and dispatch parsed `RuntimeEvent`s.
 *
 * Returns an unsubscribe function that closes the `EventSource`. Auth is the
 * HttpOnly cookie (`withCredentials`), never a URL token (INV-2). On reconnect the
 * browser replays `Last-Event-ID` automatically (§8.3); a malformed message is
 * skipped rather than tearing down the stream.
 */
export function subscribeRunEvents(runId: string, handlers: RunStreamHandlers): () => void {
  const source = openEventStream(runEventsPath(runId));

  if (handlers.onOpen) {
    source.onopen = () => handlers.onOpen?.();
  }
  source.onerror = (err) => handlers.onError?.(err);
  source.onmessage = (msg: MessageEvent<string>) => {
    const parsed = parseEvent(msg);
    if (parsed) handlers.onEvent(parsed);
  };

  return () => source.close();
}

/**
 * Parse one SSE `MessageEvent` into a {@link RuntimeEvent}, folding the message
 * `id` (the `events.id` cursor) onto the parsed body. Returns `null` for a
 * malformed body so the stream survives a single bad frame.
 */
export function parseEvent(msg: MessageEvent<string>): RuntimeEvent | null {
  let body: Partial<RuntimeEvent>;
  try {
    body = JSON.parse(msg.data) as Partial<RuntimeEvent>;
  } catch {
    return null;
  }
  const id = msg.lastEventId ? Number.parseInt(msg.lastEventId, 10) : (body.sequence ?? 0);
  return {
    id: Number.isFinite(id) ? id : 0,
    sequence: body.sequence ?? 0,
    timestamp: body.timestamp ?? "",
    run_id: body.run_id ?? "",
    task_name: body.task_name ?? "",
    task_index: body.task_index ?? -1,
    event_type: body.event_type ?? "message",
    data: (body.data as RuntimeEventData | undefined) ?? {},
    content: body.content ?? "",
    cost_usd: body.cost_usd ?? 0,
    turns: body.turns ?? 0,
  };
}

/** The full stream URL (for diagnostics/tests) — asserts NO token is present. */
export function runEventsUrl(runId: string): string {
  return `${API_BASE}${runEventsPath(runId)}`;
}
