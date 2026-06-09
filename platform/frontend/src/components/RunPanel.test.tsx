/**
 * RunPanel render tests (AC-6 / FR-03-2, §5.4). Covers:
 *
 *  - the workflow picker is populated **from the fetched `GET /workflows` list**,
 *    not a hardcoded constant (the cards reflect the props, not inlined data);
 *  - selecting / resolving a **Codex** workflow **hides** the Max-budget and
 *    Max-turns fields and shows "Codex runs are time-bounded, not cost-bounded";
 *  - a **Claude** workflow **shows** the Max-budget and Max-turns fields;
 *  - the model picker reflects the engine adapter defaults carried by the
 *    workflow summaries (no inlined model label).
 *
 * `api/runs.createRun` is mocked so no network is touched.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowSummary } from "../api/runs";

const mocks = vi.hoisted(() => ({ createRun: vi.fn() }));

vi.mock("../api/runs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/runs")>();
  return { ...actual, ...mocks };
});

import RunPanel, { deriveAgentModels } from "./RunPanel";

function stage(index: number, name: string, pause = false): WorkflowSummary["stages"][number] {
  return { index, name, description: "", pause_after: pause, budget_usd: null, for_each_item: null };
}

/** A Claude workflow (`plan`) and a Codex workflow (`dev`) — the agent/model are
 *  the engine adapter defaults the API surfaces (Codex default gpt-5.4). */
const WORKFLOWS_FIXTURE: WorkflowSummary[] = [
  {
    id: "plan",
    name: "plan",
    description: "PRD → full implementation docs",
    is_builtin: true,
    agent: "claude",
    model: "claude-sonnet-4-6",
    stages: [stage(0, "Analyze", true), stage(1, "Plan")],
    stage_count: 2,
    pause_count: 1,
    pause_points: ["Analyze"],
    est_total_usd: 12,
  },
  {
    id: "dev",
    name: "dev",
    description: "Implement each phase",
    is_builtin: true,
    agent: "codex",
    model: "gpt-5.4",
    stages: [stage(0, "Implement")],
    stage_count: 1,
    pause_count: 0,
    pause_points: [],
    est_total_usd: 10,
  },
];

function renderPanel(workflows = WORKFLOWS_FIXTURE) {
  return render(
    <RunPanel
      issueNum={247}
      issueTitle="Add Codex support"
      repo="asaficontact/DKMV"
      workflows={workflows}
      onLaunched={vi.fn()}
    />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Workflow picker from GET /workflows (AC-6)", () => {
  it("renders one card per fetched workflow (not a hardcoded list)", () => {
    renderPanel();
    expect(screen.getByRole("radio", { name: /plan/i })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /dev/i })).toBeInTheDocument();
  });

  it("reflects a different fetched list (proves it is data-driven)", () => {
    renderPanel([WORKFLOWS_FIXTURE[1]]);
    expect(screen.queryByRole("radio", { name: /^plan/i })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /dev/i })).toBeInTheDocument();
  });
});

describe("Capability-aware guardrails (AC-6 / INV-8)", () => {
  it("Claude workflow shows Max budget + Max turns fields", () => {
    renderPanel();
    // plan (claude) is selected first; open the advanced guardrails.
    fireEvent.click(screen.getByRole("button", { name: /advanced guardrails/i }));
    expect(screen.getByLabelText("Max budget")).toBeInTheDocument();
    expect(screen.getByLabelText("Max turns")).toBeInTheDocument();
    expect(screen.queryByTestId("codex-time-bounded")).not.toBeInTheDocument();
  });

  it("Codex workflow hides budget/turns and shows 'time-bounded'", () => {
    renderPanel();
    // Select the codex workflow (dev), then open the advanced guardrails.
    fireEvent.click(screen.getByRole("radio", { name: /dev/i }));
    fireEvent.click(screen.getByRole("button", { name: /advanced guardrails/i }));
    expect(screen.queryByLabelText("Max budget")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Max turns")).not.toBeInTheDocument();
    expect(screen.getByTestId("codex-time-bounded")).toHaveTextContent(/time-bounded/i);
  });

  it("explicit Codex agent (with a Claude workflow) also hides budget/turns", () => {
    renderPanel();
    // plan is claude; explicitly pick the codex agent → resolved agent is codex.
    fireEvent.click(screen.getByRole("radio", { name: /Codex/ }));
    fireEvent.click(screen.getByRole("button", { name: /advanced guardrails/i }));
    expect(screen.queryByLabelText("Max budget")).not.toBeInTheDocument();
    expect(screen.getByTestId("codex-time-bounded")).toBeInTheDocument();
  });
});

describe("Model picker from engine adapter defaults (AC-6 / §6.1)", () => {
  it("derives each agent's default model from the fetched workflows", () => {
    expect(deriveAgentModels(WORKFLOWS_FIXTURE)).toEqual({
      claude: "claude-sonnet-4-6",
      codex: "gpt-5.4",
    });
  });

  it("shows the resolved model (Codex default gpt-5.4, not a prototype label)", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("radio", { name: /dev/i }));
    expect(screen.getByTestId("resolved-model")).toHaveTextContent("gpt-5.4");
  });
});
