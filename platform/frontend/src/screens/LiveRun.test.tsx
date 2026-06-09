/**
 * LiveRun screen tests (FR-04, §5.5). Covers:
 *  - the meters row shows the segment-sum cost from `GET /runs/{id}` (INV-7);
 *  - the decision-card SLOT renders the wired PauseCard when the run is paused,
 *    sourced from the `decision` rehydration block (slice 2.6 wiring); and the
 *    fallback prompt when the decision has not rehydrated yet;
 *  - submitting an answer posts the chosen option VALUE to `answerRun`;
 *  - the Stop control calls `stopRun`;
 *  - the SSE stream is opened via the cookie-auth consumer (no token in URL).
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RunDecision, RunDetailResponse } from "../api/runs";

const mocks = vi.hoisted(() => ({
  getRun: vi.fn(),
  stopRun: vi.fn(),
  answerRun: vi.fn(),
  subscribeRunEvents: vi.fn(),
}));

vi.mock("../api/runs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/runs")>();
  return { ...actual, getRun: mocks.getRun, stopRun: mocks.stopRun, answerRun: mocks.answerRun };
});

vi.mock("../api/sse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/sse")>();
  return { ...actual, subscribeRunEvents: mocks.subscribeRunEvents };
});

import LiveRun from "./LiveRun";

function detail(overrides: Partial<RunDetailResponse> = {}): RunDetailResponse {
  return {
    id: "run-uuid",
    engine_run_id: "250608-1200-abc",
    repo: "asaficontact/DKMV",
    issue: { num: 12, title: "Rotate token before expiry" },
    workflow_id: "plan",
    agent: "claude",
    model: "claude-sonnet-4-6",
    status: "running",
    branch: "feat/codex",
    cost_usd: 7.0,
    tokens_in: 1000,
    tokens_out: 300,
    turns: 42,
    duration_s: 120,
    started_at: "2026-06-08T12:00:00Z",
    finished_at: null,
    pr: null,
    error: null,
    stages: [
      { idx: 0, name: "Analyze", status: "done", cost_usd: 3.0, turns: 20, duration_s: 600 },
      { idx: 1, name: "Features", status: "running", cost_usd: null, turns: 0, duration_s: null },
    ],
    config: {
      repo: "asaficontact/DKMV",
      branch: "feat/codex",
      feature_name: "rotate_token",
      model: "claude-sonnet-4-6",
      max_turns: 100,
      timeout_minutes: 30,
      max_budget_usd: null,
      memory_limit: "8g",
    },
    sandbox: { image: "dkmv-sandbox:latest", mem: "8g", vcpu: 2, health: "healthy" },
    artifacts: [{ name: "session.log", live: true }],
    ...overrides,
  };
}

/** A paused run's `decision` rehydration block (a plan-style single-question pause). */
function decision(overrides: Partial<RunDecision> = {}): RunDecision {
  return {
    decision_id: "dec-1",
    task_name: "Analyze",
    status: "pending",
    timeout_at: "2026-06-08T13:00:00Z",
    request: {
      task_name: "Analyze",
      questions: [
        {
          id: "phases",
          question: "How would you like to proceed?",
          options: [
            { value: "merge34", label: "Merge phases 3 & 4" },
            { value: "all4", label: "Proceed with all 4 phases" },
          ],
          default: "all4",
        },
      ],
      context: { summary: "I found 4 candidate phases." },
    },
    ...overrides,
  };
}

function renderLiveRun() {
  return render(
    <MemoryRouter>
      <LiveRun runId="run-uuid" repoSlug="asaficontact/DKMV" />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("LiveRun", () => {
  it("renders the segment-sum cost meter + the issue title (INV-7)", async () => {
    mocks.getRun.mockResolvedValue(detail());
    mocks.subscribeRunEvents.mockReturnValue(() => {});
    renderLiveRun();
    await waitFor(() => expect(screen.getByText("Rotate token before expiry")).toBeInTheDocument());
    // The cost meter shows the server-computed segment-sum value.
    expect(screen.getByText("$7.00")).toBeInTheDocument();
    // The SSE stream was opened via the cookie-auth consumer.
    expect(mocks.subscribeRunEvents).toHaveBeenCalledWith("run-uuid", expect.any(Object));
  });

  it("mounts the PauseCard in the decision-card slot when paused (slice 2.6 wiring)", async () => {
    mocks.getRun.mockResolvedValue(detail({ status: "paused", decision: decision() }));
    mocks.subscribeRunEvents.mockReturnValue(() => {});
    const { container } = renderLiveRun();
    await waitFor(() =>
      expect(container.querySelector('[data-slot="decision-card"]')).not.toBeNull(),
    );
    // The wired PauseCard renders the question + its options inside the slot.
    expect(screen.getByText("How would you like to proceed?")).toBeInTheDocument();
    expect(screen.getByText("Merge phases 3 & 4")).toBeInTheDocument();
    expect(screen.getByText("Proceed with all 4 phases")).toBeInTheDocument();
  });

  it("submitting an answer posts the chosen option VALUE to answerRun", async () => {
    mocks.getRun.mockResolvedValue(detail({ status: "paused", decision: decision() }));
    mocks.answerRun.mockResolvedValue({ resolved: true });
    mocks.subscribeRunEvents.mockReturnValue(() => {});
    renderLiveRun();
    const approve = await waitFor(() => screen.getByText("Approve & continue"));
    await act(async () => {
      fireEvent.click(approve);
    });
    // Approve posts the recommended option's VALUE ("all4"), never its label (INV-9).
    expect(mocks.answerRun).toHaveBeenCalledWith("run-uuid", {
      answers: { phases: "all4" },
      skip_remaining: false,
    });
  });

  it("falls back to the minimal prompt when paused but the decision hasn't rehydrated", async () => {
    mocks.getRun.mockResolvedValue(detail({ status: "paused", decision: null }));
    mocks.subscribeRunEvents.mockReturnValue(() => {});
    const { container } = renderLiveRun();
    await waitFor(() =>
      expect(container.querySelector('[data-slot="decision-card"]')).not.toBeNull(),
    );
    expect(screen.getByText(/Decision required/i)).toBeInTheDocument();
  });

  it("the Stop control calls stopRun", async () => {
    mocks.getRun.mockResolvedValue(detail({ status: "running" }));
    mocks.stopRun.mockResolvedValue({ run_id: "run-uuid", status: "stopping", forced: false });
    mocks.subscribeRunEvents.mockReturnValue(() => {});
    renderLiveRun();
    const stop = await waitFor(() => screen.getByRole("button", { name: /Stop/ }));
    fireEvent.click(stop);
    await waitFor(() => expect(mocks.stopRun).toHaveBeenCalledWith("run-uuid"));
  });

  it("renders Codex cost as — not $0.00 (INV-8)", async () => {
    mocks.getRun.mockResolvedValue(detail({ agent: "codex", cost_usd: null, cost_excluded: true }));
    mocks.subscribeRunEvents.mockReturnValue(() => {});
    renderLiveRun();
    await waitFor(() => expect(screen.getByText("—")).toBeInTheDocument());
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
  });
});
