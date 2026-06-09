/**
 * EventFeed (FR-04-4, AC-14). The headline assertion: the **Raw** toggle renders
 * the **inner `RuntimeEvent.data` dict** (`type/subtype/content/tool_name?/
 * num_turns`, §6.4), NOT the outer wrapper (no `sequence`/`run_id`/`task_index`).
 * Also covers the Friendly view, the search filter, and the toggle.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RuntimeEvent } from "../api/sse";
import EventFeed, { rawInnerLine } from "./EventFeed";

function ev(overrides: Partial<RuntimeEvent>): RuntimeEvent {
  return {
    id: 1,
    sequence: 1,
    timestamp: "2026-06-08T12:00:05.000Z",
    run_id: "run-uuid",
    task_name: "Analyze",
    task_index: 0,
    event_type: "assistant",
    data: { type: "assistant", subtype: "text", content: "Reading the repo", num_turns: 4 },
    content: "Reading the repo",
    cost_usd: 1.2,
    turns: 4,
    ...overrides,
  };
}

describe("EventFeed Raw view (AC-14)", () => {
  it("rawInnerLine picks the INNER data keys, not the outer wrapper", () => {
    const line = rawInnerLine(
      ev({
        data: {
          type: "assistant",
          subtype: "tool_use",
          content: "ls -la",
          tool_name: "Bash",
          num_turns: 6,
        },
      }),
    );
    // Inner §6.4 keys present…
    expect(line).toMatchObject({
      type: "assistant",
      subtype: "tool_use",
      content: "ls -la",
      tool_name: "Bash",
      num_turns: 6,
    });
    // …and the OUTER wrapper keys are absent.
    expect(line).not.toHaveProperty("sequence");
    expect(line).not.toHaveProperty("run_id");
    expect(line).not.toHaveProperty("task_index");
  });

  it("Raw view renders the inner dict line (data-testid=raw-line)", () => {
    render(
      <EventFeed
        events={[ev({})]}
        raw
        onRawChange={() => {}}
        query=""
        onQueryChange={() => {}}
        live={false}
      />,
    );
    const line = screen.getByTestId("raw-line");
    const parsed = JSON.parse(line.textContent ?? "{}");
    expect(parsed.type).toBe("assistant");
    expect(parsed.subtype).toBe("text");
    expect(parsed).not.toHaveProperty("run_id");
  });
});

describe("EventFeed Friendly view + controls", () => {
  it("renders the friendly text for an event", () => {
    render(
      <EventFeed
        events={[ev({ content: "Reading the repo" })]}
        raw={false}
        onRawChange={() => {}}
        query=""
        onQueryChange={() => {}}
        live={false}
      />,
    );
    expect(screen.getByText("Reading the repo")).toBeInTheDocument();
  });

  it("filters events by the search query", () => {
    render(
      <EventFeed
        events={[ev({ content: "alpha" }), ev({ sequence: 2, content: "beta" })]}
        raw={false}
        onRawChange={() => {}}
        query="beta"
        onQueryChange={() => {}}
        live={false}
      />,
    );
    expect(screen.getByText("beta")).toBeInTheDocument();
    expect(screen.queryByText("alpha")).not.toBeInTheDocument();
  });

  it("the Raw toggle fires onRawChange", () => {
    const onRawChange = vi.fn();
    render(
      <EventFeed
        events={[ev({})]}
        raw={false}
        onRawChange={onRawChange}
        query=""
        onQueryChange={() => {}}
        live={false}
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: /Raw/ }));
    expect(onRawChange).toHaveBeenCalledWith(true);
  });
});
