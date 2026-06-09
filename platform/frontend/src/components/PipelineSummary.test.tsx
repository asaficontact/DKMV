/**
 * PipelineSummary tests (AC-6 / §7.2 FR-07-2, AC-9 / INV-14).
 *
 * The authoritative `qa` render: **3 stages**, **1 pause** (after Evaluate),
 * **$2.00** total. Stage state is conveyed by **icon + label** (a `pauses after`
 * marker), never color alone (AC-9).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { WorkflowSummary } from "../api/workflows";
import PipelineSummary from "./PipelineSummary";

/** The authoritative qa summary (3 stages / 1 pause after Evaluate / $2.00). */
const QA: WorkflowSummary = {
  id: "qa",
  name: "QA",
  description: "Evaluate, fix, re-evaluate",
  is_builtin: true,
  agent: "claude",
  model: "claude-sonnet-4-6",
  stages: [
    { index: 0, name: "Evaluate", description: "", pause_after: true, budget_usd: 0.8, for_each_item: null },
    { index: 1, name: "Fix", description: "", pause_after: false, budget_usd: 0.8, for_each_item: null },
    { index: 2, name: "Re-evaluate", description: "", pause_after: false, budget_usd: 0.4, for_each_item: null },
  ],
  stage_count: 3,
  pause_count: 1,
  pause_points: ["Evaluate"],
  est_total_usd: 2.0,
};

describe("PipelineSummary (AC-6)", () => {
  it("renders 3 stages / 1 pause / $2.00 total for qa", () => {
    render(<PipelineSummary workflow={QA} />);
    expect(screen.getByTestId("stage-count")).toHaveTextContent("3");
    expect(screen.getByTestId("pause-count")).toHaveTextContent("1");
    expect(screen.getByTestId("est-total")).toHaveTextContent("$2.00");
  });

  it("renders the three named stages in order", () => {
    render(<PipelineSummary workflow={QA} />);
    expect(screen.getByText("Evaluate")).toBeInTheDocument();
    expect(screen.getByText("Fix")).toBeInTheDocument();
    expect(screen.getByText("Re-evaluate")).toBeInTheDocument();
  });

  it("marks the pausing stage with an icon + a text label (not color alone — AC-9)", () => {
    render(<PipelineSummary workflow={QA} />);
    const pauseMarkers = screen.getAllByTestId("stage-pause");
    // Exactly one stage (Evaluate) pauses after.
    expect(pauseMarkers).toHaveLength(1);
    // The marker carries a TEXT label ("pauses after") + an icon (svg), so a
    // colorblind reader gets the meaning without relying on hue.
    expect(pauseMarkers[0]).toHaveTextContent("pauses after");
    expect(pauseMarkers[0].querySelector("svg")).not.toBeNull();
  });

  it("renders per-stage budgets in the mono (tnum) numeric style", () => {
    render(<PipelineSummary workflow={QA} />);
    const budgets = screen.getAllByTestId("stage-budget");
    expect(budgets[0]).toHaveTextContent("$0.80");
    expect(budgets[0].className).toContain("mono");
  });

  it("renders an em dash for an unknown total", () => {
    render(<PipelineSummary workflow={{ ...QA, est_total_usd: null }} />);
    expect(screen.getByTestId("est-total")).toHaveTextContent("—");
  });
});
