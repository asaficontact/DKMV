/**
 * API client primitive tests — the EventSource primitive (INV-2) + envelope
 * decoding (§8.9).
 *
 * INV-2: the SSE primitive must NOT carry a token in the URL/query — auth rides
 * the HttpOnly cookie (`withCredentials`). We assert the constructed URL has no
 * `token=` and that `withCredentials` is requested.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, API_BASE, apiGet, openEventStream } from "./client";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("openEventStream (INV-2)", () => {
  it("opens an EventSource with no token in the URL and credentials on", () => {
    const seen: { url: string; init?: EventSourceInit } = { url: "" };
    class FakeES {
      constructor(url: string, init?: EventSourceInit) {
        seen.url = url;
        seen.init = init;
      }
    }
    vi.stubGlobal("EventSource", FakeES as unknown as typeof EventSource);

    openEventStream("/runs/abc/events");

    expect(seen.url).toBe(`${API_BASE}/runs/abc/events`);
    expect(seen.url).not.toContain("token=");
    expect(seen.url).not.toContain("?");
    expect(seen.init?.withCredentials).toBe(true);
  });
});

describe("apiGet envelope decoding (§8.9)", () => {
  it("throws an ApiError carrying the machine code on a non-2xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: "forbidden", message: "nope" } }), {
          status: 403,
        }),
      ),
    );
    await expect(apiGet("/repos")).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
      code: "forbidden",
    });
  });

  it("returns the decoded body on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify([{ org: "a", name: "b" }]), { status: 200 })),
    );
    const repos = await apiGet<{ org: string }[]>("/repos");
    expect(repos[0].org).toBe("a");
  });

  it("ApiError exposes details", () => {
    const e = new ApiError(400, "validation_error", "bad", { field: "token" });
    expect(e.details).toEqual({ field: "token" });
  });
});
