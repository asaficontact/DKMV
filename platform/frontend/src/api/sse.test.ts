/**
 * Live-run SSE consumer tests (slice 2.4, INV-2 / AC-14).
 *
 * INV-2 (binding): the stream URL must carry **NO token** and **no query string**
 * — auth rides the HttpOnly cookie (`withCredentials`). We assert the constructed
 * EventSource URL and that `parseEvent` folds the SSE message id (the `events.id`
 * cursor) onto the parsed body.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE } from "./client";
import { parseEvent, runEventsPath, runEventsUrl, subscribeRunEvents } from "./sse";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("SSE URL (INV-2)", () => {
  it("the stream path/URL has no token and no query string", () => {
    expect(runEventsPath("abc")).toBe("/runs/abc/events");
    const url = runEventsUrl("abc");
    expect(url).toBe(`${API_BASE}/runs/abc/events`);
    expect(url).not.toContain("token=");
    expect(url).not.toContain("?");
  });

  it("subscribeRunEvents opens an EventSource with credentials, no token in URL", () => {
    const seen: { url: string; init?: EventSourceInit } = { url: "" };
    class FakeES {
      onmessage: ((e: MessageEvent<string>) => void) | null = null;
      onerror: ((e: Event) => void) | null = null;
      onopen: (() => void) | null = null;
      constructor(url: string, init?: EventSourceInit) {
        seen.url = url;
        seen.init = init;
      }
      close() {}
    }
    vi.stubGlobal("EventSource", FakeES as unknown as typeof EventSource);

    const unsubscribe = subscribeRunEvents("run-1", { onEvent: () => {} });
    expect(seen.url).toBe(`${API_BASE}/runs/run-1/events`);
    expect(seen.url).not.toContain("token=");
    expect(seen.init?.withCredentials).toBe(true);
    unsubscribe();
  });
});

describe("parseEvent", () => {
  it("folds the SSE message id (events.id cursor) onto the parsed body", () => {
    const msg = {
      data: JSON.stringify({
        sequence: 7,
        timestamp: "2026-06-08T12:00:00Z",
        run_id: "engine-id",
        task_name: "Analyze",
        task_index: 0,
        event_type: "task_completed",
        data: { type: "task_completed", num_turns: 12 },
        content: "",
        cost_usd: 3.2,
        turns: 12,
      }),
      lastEventId: "42",
    } as MessageEvent<string>;
    const parsed = parseEvent(msg);
    expect(parsed?.id).toBe(42); // the events.id cursor (Last-Event-ID)
    expect(parsed?.event_type).toBe("task_completed");
    expect(parsed?.data.num_turns).toBe(12);
  });

  it("returns null for a malformed body (stream survives a bad frame)", () => {
    const msg = { data: "not json", lastEventId: "1" } as MessageEvent<string>;
    expect(parseEvent(msg)).toBeNull();
  });
});
