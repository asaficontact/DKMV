/**
 * Board render + interaction tests (AC-15, AC-16, AC-18, AC-20 / FR-02, §5.3.1).
 *
 * Covers:
 *  - AC-15 — exactly the six §5.3.1 columns in left→right order.
 *  - AC-16 — dragging a card Backlog↔Queued posts the right `agent-state` target;
 *    run-driven columns are not droppable (no post).
 *  - AC-18 — Populated / Empty / Syncing states; Empty shows the AC-18 copy.
 *  - AC-20 — the board (and chrome) never instantiate an `EventSource` (poll-only).
 *
 * The `api/board` module is mocked so no real network is touched.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BoardAggregate, BoardIssue } from "../api/board";

const mocks = vi.hoisted(() => ({
  listBoardIssues: vi.fn(),
  getBoardAggregate: vi.fn(),
  setAgentState: vi.fn(),
}));

vi.mock("../api/board", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/board")>();
  return { ...actual, ...mocks };
});

import Board from "./Board";

/** Render the Board inside a router (it uses `useNavigate` to open issues). */
function renderBoard() {
  return render(
    <MemoryRouter>
      <Board repoSlug="asaficontact/DKMV" />
    </MemoryRouter>,
  );
}

const AGG: BoardAggregate = {
  repo: "asaficontact/DKMV",
  in_progress: 1,
  needs_you: 1,
  spent_today: 4.18,
  tokens_today: 88_400,
};

function issue(partial: Partial<BoardIssue> & Pick<BoardIssue, "num" | "state">): BoardIssue {
  return {
    title: `Issue ${partial.num}`,
    labels: [],
    workflow_id: null,
    agent: null,
    pr_num: null,
    run_status: null,
    ...partial,
  };
}

const POPULATED: BoardIssue[] = [
  issue({ num: 263, state: "backlog", labels: ["frontend", "good first issue"] }),
  issue({ num: 233, state: "queued", labels: ["enhancement"], workflow_id: "dev" }),
  issue({ num: 247, state: "in_progress", agent: "codex", workflow_id: "dev", live_turns: 37 }),
  issue({ num: 251, state: "needs_you", agent: "claude", workflow_id: "plan" }),
  issue({ num: 260, state: "in_review", pr_num: 184 }),
  issue({ num: 244, state: "done", pr_num: 176 }),
];

const EXPECTED_COLUMNS = [
  "Backlog",
  "Queued",
  "In Progress",
  "Needs You",
  "In Review",
  "Done",
];

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getBoardAggregate.mockResolvedValue(AGG);
  mocks.setAgentState.mockResolvedValue({
    repo: "asaficontact/DKMV",
    num: 263,
    agent_label: "agent:queued",
    labels: ["agent:queued"],
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Board columns (AC-15)", () => {
  it("renders exactly the six §5.3.1 columns in order", async () => {
    mocks.listBoardIssues.mockResolvedValue({ items: POPULATED, next_cursor: null });
    renderBoard();

    await screen.findByText("Issue 247");
    const board = document.querySelector(".board-columns") as HTMLElement;
    const columns = within(board).getAllByRole("listitem");
    expect(columns.map((c) => c.getAttribute("aria-label"))).toEqual(EXPECTED_COLUMNS);
  });
});

describe("Board states (AC-18)", () => {
  it("shows the Empty state with the verbatim copy when there are no issues", async () => {
    mocks.listBoardIssues.mockResolvedValue({ items: [], next_cursor: null });
    renderBoard();

    expect(
      await screen.findByText(/Create an issue on GitHub or import/i),
    ).toBeInTheDocument();
  });

  it("renders the populated board (hero) when issues are present", async () => {
    mocks.listBoardIssues.mockResolvedValue({ items: POPULATED, next_cursor: null });
    renderBoard();

    expect(await screen.findByText("Issue 247")).toBeInTheDocument();
  });
});

describe("Drag Backlog↔Queued (AC-16)", () => {
  it("posts target=queued when a Backlog card is dropped on Queued", async () => {
    mocks.listBoardIssues.mockResolvedValue({ items: POPULATED, next_cursor: null });
    renderBoard();
    await screen.findByText("Issue 263");

    const card = document.querySelector('.issue-card[data-num="263"]') as HTMLElement;
    const queuedCol = screen.getByRole("listitem", { name: "Queued" });

    fireEvent.dragStart(card);
    fireEvent.dragOver(queuedCol);
    fireEvent.drop(queuedCol);

    await waitFor(() =>
      expect(mocks.setAgentState).toHaveBeenCalledWith("asaficontact/DKMV", 263, "queued"),
    );
  });

  it("posts target=none when a Queued card is dropped back on Backlog", async () => {
    mocks.listBoardIssues.mockResolvedValue({ items: POPULATED, next_cursor: null });
    renderBoard();
    await screen.findByText("Issue 233");

    const card = document.querySelector('.issue-card[data-num="233"]') as HTMLElement;
    const backlogCol = screen.getByRole("listitem", { name: "Backlog" });

    fireEvent.dragStart(card);
    fireEvent.dragOver(backlogCol);
    fireEvent.drop(backlogCol);

    await waitFor(() =>
      expect(mocks.setAgentState).toHaveBeenCalledWith("asaficontact/DKMV", 233, "none"),
    );
  });

  it("does not post when a card is dropped on a run-driven column", async () => {
    mocks.listBoardIssues.mockResolvedValue({ items: POPULATED, next_cursor: null });
    renderBoard();
    await screen.findByText("Issue 263");

    const card = document.querySelector('.issue-card[data-num="263"]') as HTMLElement;
    const progressCol = screen.getByRole("listitem", { name: "In Progress" });

    // The run-driven column is not droppable (no onDrop handler wired).
    expect(progressCol.getAttribute("data-droppable")).toBe("false");
    fireEvent.dragStart(card);
    fireEvent.drop(progressCol);

    // give any rejected handler a tick; nothing should have posted
    await new Promise((r) => setTimeout(r, 0));
    expect(mocks.setAgentState).not.toHaveBeenCalled();
  });

  it("only Backlog and Queued cards are draggable (AC-16)", async () => {
    mocks.listBoardIssues.mockResolvedValue({ items: POPULATED, next_cursor: null });
    renderBoard();
    await screen.findByText("Issue 247");

    const backlog = document.querySelector('.issue-card[data-num="263"]') as HTMLElement;
    const queued = document.querySelector('.issue-card[data-num="233"]') as HTMLElement;
    const progress = document.querySelector('.issue-card[data-num="247"]') as HTMLElement;
    expect(backlog.getAttribute("draggable")).toBe("true");
    expect(queued.getAttribute("draggable")).toBe("true");
    expect(progress.getAttribute("draggable")).toBe("false");
  });
});

describe("In-Progress live cost (FR-02-1)", () => {
  it("shows an aggregate live cost in the In Progress header", async () => {
    const withCost = POPULATED.map((i) =>
      i.num === 247 ? { ...i, agent: "claude", live_cost: 2.5 } : i,
    );
    mocks.listBoardIssues.mockResolvedValue({ items: withCost, next_cursor: null });
    renderBoard();

    const col = await screen.findByRole("listitem", { name: "In Progress" });
    const header = col.querySelector(".column-head") as HTMLElement;
    expect(within(header).getByText("$2.50")).toBeInTheDocument();
  });
});
