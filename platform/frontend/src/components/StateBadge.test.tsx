/**
 * StateBadge render tests (AC-19 / INV-14 / §7.3).
 *
 * The badge must convey state by **icon + text label**, never color alone — so a
 * render asserts BOTH an icon element AND a readable text label are present, and
 * that the correct `s-*` palette class is applied per status. The same component
 * is reused for the board card and the sidebar chip (one palette everywhere).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import StateBadge from "./StateBadge";

describe("StateBadge", () => {
  it("renders an icon element AND a text label (never color alone)", () => {
    const { container } = render(<StateBadge status="running" />);
    // icon element present
    expect(screen.getByTestId("state-icon")).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeInTheDocument();
    // readable text label present (not just a colored dot)
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("maps board/engine statuses to the correct palette class", () => {
    const cases: [string, string][] = [
      ["in_progress", "s-running"],
      ["needs_you", "s-paused"],
      ["paused", "s-paused"],
      ["in_review", "s-review"],
      ["done", "s-done"],
      ["failed", "s-failed"],
      ["queued", "s-queued"],
    ];
    for (const [status, cls] of cases) {
      const { container, unmount } = render(<StateBadge status={status} />);
      expect(container.querySelector(`.state.${cls}`)).toBeInTheDocument();
      unmount();
    }
  });

  it("accepts an explicit label override", () => {
    render(<StateBadge status="paused" label="Needs you" />);
    expect(screen.getByText("Needs you")).toBeInTheDocument();
  });

  // AC-6 (INV-14, binding): the history status palette mapping.
  it("maps timed_out → failed palette with a 'Timed out' label + icon", () => {
    const { container } = render(<StateBadge status="timed_out" />);
    expect(container.querySelector(".state.s-failed")).toBeInTheDocument();
    expect(screen.getByText("Timed out")).toBeInTheDocument();
    // icon + label, never color alone
    expect(screen.getByTestId("state-icon")).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("maps interrupted (platform-only) → cancel palette with an 'Interrupted' label + icon", () => {
    const { container } = render(<StateBadge status="interrupted" />);
    expect(container.querySelector(".state.s-cancel")).toBeInTheDocument();
    expect(screen.getByText("Interrupted")).toBeInTheDocument();
    expect(screen.getByTestId("state-icon")).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});
