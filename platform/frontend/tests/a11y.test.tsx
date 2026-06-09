/**
 * Accessibility render suite (AC-10, NFR-A11Y-1 / INV-14, DESIGN_FIDELITY §8).
 *
 * Two binding assertions for the slice-5.3 a11y pass:
 *
 *  1. **axe — no critical violations** over the key surfaces (a board card, the
 *     decision/pause card, and the run panel). We fail the test on a *critical* or
 *     *serious* impact (the "no critical violations" bar); contrast is included in
 *     the run so a token that fails AA would be flagged.
 *  2. **keyboard-only Backlog→Queued move** — a board card is moved from Backlog to
 *     Queued using only the keyboard (focus + Enter), asserting the SAME
 *     `onMoveColumn` path the pointer drop uses fires with the Queued target — no
 *     mouse touched (FR-02-3 / AC-10).
 */
import { fireEvent, render } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";

import IssueCard from "../src/components/IssueCard";
import PauseCard, { type PauseRequest } from "../src/components/PauseCard";
import RunPanel from "../src/components/RunPanel";
import StateBadge from "../src/components/StateBadge";
import type { BoardIssue } from "../src/api/board";
import type { WorkflowSummary } from "../src/api/runs";
import { handleKeyboardDrag } from "../src/a11y/keyboard-drag";

const BACKLOG_ISSUE: BoardIssue = {
  num: 247,
  title: "Add Codex support",
  labels: ["enhancement"],
  state: "backlog",
  workflow_id: null,
  agent: null,
  pr_num: null,
  run_status: null,
};

const PAUSE_REQUEST: PauseRequest = {
  task_name: "Analyze",
  questions: [
    {
      id: "phases",
      question: "How would you like to proceed?",
      options: [
        { value: "merge", label: "Merge phases", description: "Combine the last two." },
        { value: "keep", label: "Keep separate", description: "Leave as-is." },
      ],
      default: "merge",
    },
  ],
  context: { summary: "Two phases are very similar." },
};

const WORKFLOWS: WorkflowSummary[] = [
  {
    id: "plan",
    name: "plan",
    description: "PRD → full implementation docs",
    is_builtin: true,
    agent: "claude",
    model: "claude-sonnet-4-6",
    stages: [
      {
        index: 0,
        name: "Analyze",
        description: "",
        pause_after: true,
        budget_usd: null,
        for_each_item: null,
      },
    ],
    stage_count: 1,
    pause_count: 1,
    pause_points: ["Analyze"],
    est_total_usd: 12,
  },
];

/** Assert axe found no critical / serious violations in `container`. */
async function expectNoCriticalViolations(container: HTMLElement): Promise<void> {
  const results = await axe(container);
  const blocking = results.violations.filter(
    (v) => v.impact === "critical" || v.impact === "serious",
  );
  if (blocking.length > 0) {
    const summary = blocking.map((v) => `${v.id} (${v.impact}): ${v.help}`).join("\n");
    throw new Error(`axe reported blocking a11y violations:\n${summary}`);
  }
  expect(blocking).toHaveLength(0);
}

describe("accessibility — axe over key screens", () => {
  it("a board issue card has no critical violations", async () => {
    const { container } = render(
      <IssueCard issue={BACKLOG_ISSUE} onMoveColumn={vi.fn()} tabIndex={0} />,
    );
    await expectNoCriticalViolations(container);
  });

  it("the decision (pause) card has no critical violations", async () => {
    const { container } = render(
      <PauseCard runId="run-1" request={PAUSE_REQUEST} onSubmit={vi.fn(async () => ({}))} />,
    );
    await expectNoCriticalViolations(container);
  });

  it("the run panel has no critical violations", async () => {
    const { container } = render(
      <RunPanel
        issueNum={247}
        issueTitle="Add Codex support"
        repo="acme/app"
        workflows={WORKFLOWS}
        onLaunched={vi.fn()}
      />,
    );
    await expectNoCriticalViolations(container);
  });

  it("the StateBadge conveys state by icon + label, not color alone (INV-14)", () => {
    const { getByTestId, getByText } = render(<StateBadge status="running" />);
    // Both an icon AND a text label render — a colorblind operator reads the word.
    expect(getByTestId("state-icon")).toBeInTheDocument();
    expect(getByText("Running")).toBeInTheDocument();
  });
});

describe("accessibility — keyboard-only Backlog→Queued move (AC-10)", () => {
  it("moves a focused Backlog card to Queued with the keyboard, no mouse", () => {
    const onMoveColumn = vi.fn();
    const { container } = render(
      <IssueCard issue={BACKLOG_ISSUE} onMoveColumn={onMoveColumn} tabIndex={0} />,
    );
    const card = container.querySelector<HTMLElement>(".issue-card");
    expect(card).not.toBeNull();
    // The card is keyboard-focusable (in the tab order) — no mouse.
    card!.focus();
    expect(document.activeElement).toBe(card);
    // Press Enter (pick-up + drop to the other column) — keyboard only.
    fireEvent.keyDown(card!, { key: "Enter" });
    expect(onMoveColumn).toHaveBeenCalledTimes(1);
    // It fired with the Queued target (the same move the pointer drop would post).
    const [issueArg, targetArg] = onMoveColumn.mock.calls[0];
    expect(issueArg).toMatchObject({ num: 247 });
    expect(targetArg).toBe("queued");
  });

  it("ArrowRight moves Backlog→Queued and ArrowLeft moves Queued→Backlog", () => {
    // Backlog → Queued via the pure handler (the same one the card wires).
    const toQueued = vi.fn();
    handleKeyboardDrag(
      { key: "ArrowRight", preventDefault: vi.fn() } as never,
      "backlog",
      toQueued,
    );
    expect(toQueued).toHaveBeenCalledWith("queued");

    // Queued → Backlog.
    const toBacklog = vi.fn();
    handleKeyboardDrag(
      { key: "ArrowLeft", preventDefault: vi.fn() } as never,
      "queued",
      toBacklog,
    );
    expect(toBacklog).toHaveBeenCalledWith("backlog");
  });

  it("a run-driven column card is NOT keyboard-movable (rejects the move)", () => {
    const onMove = vi.fn();
    // An in_progress card is not draggable → handler returns false, no move.
    const handled = handleKeyboardDrag(
      { key: "Enter", preventDefault: vi.fn() } as never,
      "in_progress",
      onMove,
    );
    expect(handled).toBe(false);
    expect(onMove).not.toHaveBeenCalled();
  });
});
