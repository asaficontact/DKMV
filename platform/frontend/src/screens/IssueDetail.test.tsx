/**
 * IssueDetail render tests (AC-7 / FR-03-1/3, §5.4). Covers:
 *
 *  - the markdown renderer supports `###`, ordered + unordered lists, `` `code` ``,
 *    and `**bold**`;
 *  - the existing-run alert shows the **paused** (amber / "needs your decision" /
 *    Review decision) vs **running** (blue / "in progress" / Watch live) variants;
 *  - **Run with {Claude|Codex}** posts `POST /runs` with
 *    `resolvedAgent = agent === "auto" ? workflow.agent : agent`.
 *
 * The `api/runs` module is mocked so no network is touched. The screen takes its
 * navigation callbacks as props (no router needed for these renders).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IssueDetailResponse, WorkflowSummary } from "../api/runs";
import Markdown from "../components/Markdown";

const mocks = vi.hoisted(() => ({
  getIssueDetail: vi.fn(),
  listWorkflows: vi.fn(),
  createRun: vi.fn(),
}));

vi.mock("../api/runs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/runs")>();
  return { ...actual, ...mocks };
});

import IssueDetail from "./IssueDetail";

function wfStage(index: number, name: string, pause = false): WorkflowSummary["stages"][number] {
  return { index, name, description: "", pause_after: pause, budget_usd: null, for_each_item: null };
}

const WORKFLOWS: WorkflowSummary[] = [
  {
    id: "plan",
    name: "plan",
    description: "PRD → docs",
    is_builtin: true,
    agent: "claude",
    model: "claude-sonnet-4-6",
    stages: [wfStage(0, "Analyze", true)],
    stage_count: 1,
    pause_count: 1,
    pause_points: ["Analyze"],
    est_total_usd: 12,
  },
  {
    id: "dev",
    name: "dev",
    description: "Implement",
    is_builtin: true,
    agent: "codex",
    model: "gpt-5.4",
    stages: [wfStage(0, "Implement")],
    stage_count: 1,
    pause_count: 0,
    pause_points: [],
    est_total_usd: 10,
  },
];

function issueFixture(over: Partial<IssueDetailResponse> = {}): IssueDetailResponse {
  return {
    num: 247,
    title: "Add Codex support",
    body: "Plain paragraph.",
    state: "open",
    url: "https://github.com/asaficontact/DKMV/issues/247",
    created_at: null,
    author: { login: "asaficontact", avatar: null },
    labels: [{ name: "backend", color: "4f8cff" }],
    comments: [],
    active_run: null,
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listWorkflows.mockResolvedValue(WORKFLOWS);
});

describe("Markdown renderer (AC-7)", () => {
  it("renders headings, ordered/unordered lists, code and bold", () => {
    const body = [
      "### Heading",
      "1. first",
      "2. second",
      "- bullet a",
      "- bullet b",
      "Use `code` and **bold** text.",
    ].join("\n");
    render(<Markdown text={body} />);

    expect(screen.getByRole("heading", { level: 4, name: "Heading" })).toBeInTheDocument();
    // Ordered + unordered lists are distinct elements.
    const lists = document.querySelectorAll(".markdown .md-list");
    expect(document.querySelector("ol.md-list")).not.toBeNull();
    expect(document.querySelector("ul.md-list")).not.toBeNull();
    expect(lists.length).toBe(2);
    expect(screen.getByText("first")).toBeInTheDocument();
    expect(screen.getByText("bullet a")).toBeInTheDocument();
    // Inline code + bold.
    const code = document.querySelector(".md-code");
    expect(code?.textContent).toBe("code");
    const strong = document.querySelector(".md-strong");
    expect(strong?.textContent).toBe("bold");
  });
});

describe("Existing-run alert (AC-7)", () => {
  it("renders the paused (amber / Review decision) variant", async () => {
    mocks.getIssueDetail.mockResolvedValue(
      issueFixture({ active_run: { run_id: "run-uuid-1", status: "paused", pr_num: null } }),
    );
    render(
      <IssueDetail repoSlug="asaficontact/DKMV" issueNum={247} onOpenRun={vi.fn()} />,
    );

    const alert = await screen.findByText(/this run is paused and needs your decision/i);
    expect(alert).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /review decision/i })).toBeInTheDocument();
    const card = document.querySelector(".existing-run-alert");
    expect(card?.getAttribute("data-variant")).toBe("paused");
  });

  it("renders the running (blue / Watch live) variant", async () => {
    mocks.getIssueDetail.mockResolvedValue(
      issueFixture({ active_run: { run_id: "run-uuid-2", status: "running", pr_num: null } }),
    );
    render(
      <IssueDetail repoSlug="asaficontact/DKMV" issueNum={247} onOpenRun={vi.fn()} />,
    );

    expect(await screen.findByText(/a run is in progress for this issue/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /watch live/i })).toBeInTheDocument();
    const card = document.querySelector(".existing-run-alert");
    expect(card?.getAttribute("data-variant")).toBe("running");
  });

  it("Review decision navigates to the live run by id", async () => {
    const onOpenRun = vi.fn();
    mocks.getIssueDetail.mockResolvedValue(
      issueFixture({ active_run: { run_id: "run-uuid-3", status: "paused", pr_num: null } }),
    );
    render(
      <IssueDetail repoSlug="asaficontact/DKMV" issueNum={247} onOpenRun={onOpenRun} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /review decision/i }));
    expect(onOpenRun).toHaveBeenCalledWith("run-uuid-3");
  });
});

describe("Launch posts resolvedAgent (AC-7 / FR-03-3)", () => {
  it("auto → workflow.agent (codex) when the codex workflow is selected", async () => {
    mocks.getIssueDetail.mockResolvedValue(issueFixture());
    mocks.createRun.mockResolvedValue({ run_id: "new-run-uuid" });
    const onOpenRun = vi.fn();
    render(
      <IssueDetail repoSlug="asaficontact/DKMV" issueNum={247} onOpenRun={onOpenRun} />,
    );

    // Select the codex workflow (dev); agent stays "auto" → resolves to codex.
    fireEvent.click(await screen.findByRole("radio", { name: /dev/i }));
    fireEvent.click(screen.getByRole("button", { name: /run with codex/i }));

    await waitFor(() => expect(mocks.createRun).toHaveBeenCalled());
    expect(mocks.createRun.mock.calls[0][0]).toMatchObject({
      issue_num: 247,
      repo: "asaficontact/DKMV",
      workflow_id: "dev",
      agent: "codex",
    });
    // A codex launch never carries budget/turns (INV-8).
    const body = mocks.createRun.mock.calls[0][0];
    expect(body.max_budget_usd).toBeUndefined();
    expect(body.max_turns).toBeUndefined();
    await waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("new-run-uuid"));
  });

  it("explicit agent overrides auto (claude workflow + explicit codex → codex)", async () => {
    mocks.getIssueDetail.mockResolvedValue(issueFixture());
    mocks.createRun.mockResolvedValue({ run_id: "r2" });
    render(<IssueDetail repoSlug="asaficontact/DKMV" issueNum={247} onOpenRun={vi.fn()} />);

    // plan (claude) is selected; explicitly pick codex.
    await screen.findByRole("radio", { name: /plan/i });
    fireEvent.click(screen.getByRole("radio", { name: /Codex/ }));
    fireEvent.click(screen.getByRole("button", { name: /run with codex/i }));

    await waitFor(() => expect(mocks.createRun).toHaveBeenCalled());
    expect(mocks.createRun.mock.calls[0][0]).toMatchObject({ workflow_id: "plan", agent: "codex" });
  });
});
