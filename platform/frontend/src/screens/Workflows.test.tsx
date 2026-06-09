/**
 * Workflows viewer screen tests (AC-5 / §5.8 FR-07-1v, AC-7).
 *
 * Covers:
 *  - AC-5 — the screen lists **built-in** (`plan/dev/qa/docs/ship`) **and a
 *    registered custom** component from `GET /workflows`; selecting one renders its
 *    pipeline summary + the read-only YAML view.
 *  - AC-7 — the selected detail surfaces the verbatim authoring-deferred note.
 *
 * The `api/workflows` module is mocked so no real network is touched.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { WorkflowDetail, WorkflowSummary } from "../api/workflows";

const mocks = vi.hoisted(() => ({
  listWorkflows: vi.fn(),
  getWorkflow: vi.fn(),
}));

vi.mock("../api/workflows", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/workflows")>();
  return { ...actual, ...mocks };
});

import Workflows from "./Workflows";

function summary(partial: Partial<WorkflowSummary> & Pick<WorkflowSummary, "id" | "name">): WorkflowSummary {
  return {
    description: "",
    is_builtin: true,
    agent: "claude",
    model: "claude-sonnet-4-6",
    stages: [{ index: 0, name: "Step", description: "", pause_after: false, budget_usd: null, for_each_item: null }],
    stage_count: 1,
    pause_count: 0,
    pause_points: [],
    est_total_usd: null,
    ...partial,
  };
}

const QA = summary({
  id: "qa",
  name: "QA",
  description: "Evaluate, fix, re-evaluate",
  stages: [
    { index: 0, name: "Evaluate", description: "", pause_after: true, budget_usd: 0.8, for_each_item: null },
    { index: 1, name: "Fix", description: "", pause_after: false, budget_usd: 0.8, for_each_item: null },
    { index: 2, name: "Re-evaluate", description: "", pause_after: false, budget_usd: 0.4, for_each_item: null },
  ],
  stage_count: 3,
  pause_count: 1,
  pause_points: ["Evaluate"],
  est_total_usd: 2.0,
});

const LIST: WorkflowSummary[] = [
  summary({ id: "plan", name: "Plan" }),
  summary({ id: "dev", name: "Dev" }),
  QA,
  summary({ id: "docs", name: "Docs" }),
  summary({ id: "ship", name: "Ship" }),
  summary({ id: "custom", name: "Custom", description: "a custom workflow", is_builtin: false }),
];

const QA_DETAIL: WorkflowDetail = {
  summary: QA,
  component_yaml: { filename: "component.yaml", content: "name: qa\nmax_budget_usd: 2.00\n" },
  task_yaml: [{ filename: "01-evaluate.yaml", content: "name: Evaluate\n" }],
};

function renderScreen() {
  return render(
    <MemoryRouter initialEntries={["/workflows?repo=o/r"]}>
      <Workflows repoSlug="o/r" />
    </MemoryRouter>,
  );
}

describe("Workflows screen (AC-5)", () => {
  it("lists the five built-ins + a registered custom component", async () => {
    mocks.listWorkflows.mockResolvedValue(LIST);
    mocks.getWorkflow.mockResolvedValue({ ...QA_DETAIL, summary: LIST[0] });
    renderScreen();

    await waitFor(() => expect(screen.getByRole("option", { name: /Plan/ })).toBeInTheDocument());
    for (const name of ["Plan", "Dev", "QA", "Docs", "Ship"]) {
      expect(screen.getByRole("option", { name: new RegExp(name) })).toBeInTheDocument();
    }
    // The registered on-disk custom component appears (AC-5 / ties to AC-8).
    const custom = screen.getByRole("option", { name: /Custom/ });
    expect(custom).toBeInTheDocument();
    expect(custom).toHaveTextContent("custom");
  });

  it("selecting qa renders its pipeline summary (3 / 1 / $2.00) + the YAML view", async () => {
    mocks.listWorkflows.mockResolvedValue(LIST);
    mocks.getWorkflow.mockResolvedValue(QA_DETAIL);
    renderScreen();

    await waitFor(() => expect(screen.getByRole("option", { name: /QA/ })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("option", { name: /QA/ }));

    await waitFor(() => expect(screen.getByTestId("stage-count")).toHaveTextContent("3"));
    expect(screen.getByTestId("pause-count")).toHaveTextContent("1");
    expect(screen.getByTestId("est-total")).toHaveTextContent("$2.00");

    // The read-only YAML view + the verbatim authoring-deferred note render (AC-7).
    await waitFor(() =>
      expect(
        screen.getByText("Workflow authoring coming in v1.1 — edit the YAML directly for now"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("component.yaml")).toBeInTheDocument();
  });

  it("renders the error state when the list fails", async () => {
    mocks.listWorkflows.mockRejectedValue(new Error("boom"));
    renderScreen();
    await waitFor(() => expect(screen.getByText(/Couldn’t load workflows/)).toBeInTheDocument());
  });
});
