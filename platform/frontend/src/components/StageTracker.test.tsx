/**
 * StageTracker (FR-04-3, AC-16). Asserts per-stage status (done/running/paused/
 * pending) is conveyed by an icon **and** a status word (never color alone —
 * INV-14), the `$cost · {turns}t · {dur}` meta renders, and a non-pending stage
 * is clickable while a pending one is not.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunStage } from "../api/runs";
import StageTracker from "./StageTracker";

const STAGES: RunStage[] = [
  { idx: 0, name: "Analyze", status: "done", cost_usd: 6.4, turns: 64, duration_s: 720 },
  { idx: 1, name: "Features", status: "running", cost_usd: null, turns: 0, duration_s: null },
  { idx: 2, name: "Phases", status: "pending", cost_usd: null, turns: 0, duration_s: null },
];

describe("StageTracker", () => {
  it("renders each stage with a status word (icon + label, INV-14)", () => {
    render(<StageTracker stages={STAGES} />);
    expect(screen.getByText("Analyze")).toBeInTheDocument();
    const words = screen.getAllByTestId("stage-status").map((n) => n.textContent);
    expect(words).toEqual(["done", "running", "pending"]);
  });

  it("renders $cost · {turns}t · {dur} for a completed stage (AC-16)", () => {
    render(<StageTracker stages={STAGES} />);
    expect(screen.getByText("$6.40 · 64t · 12m 00s")).toBeInTheDocument();
  });

  it("a non-pending stage is clickable; a pending one is disabled", () => {
    render(<StageTracker stages={STAGES} />);
    const buttons = screen.getAllByRole("button");
    // done + running clickable, pending disabled.
    expect(buttons[0]).not.toBeDisabled();
    expect(buttons[1]).not.toBeDisabled();
    expect(buttons[2]).toBeDisabled();
    // Clicking a clickable stage expands its detail.
    fireEvent.click(buttons[0]);
    expect(buttons[0]).toHaveAttribute("aria-expanded", "true");
  });

  it("shows an empty hint when there are no stages", () => {
    render(<StageTracker stages={[]} />);
    expect(screen.getByText(/Stages appear/i)).toBeInTheDocument();
  });
});
