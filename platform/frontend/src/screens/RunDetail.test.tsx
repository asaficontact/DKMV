/**
 * Read-only finished-run view tests (AC-5 / FR-06-4).
 *
 * Asserts:
 *  - a completed run renders read-only — **no Stop control** (the live view owns
 *    that) and **no SSE stream** is opened (a finished run is static);
 *  - a failed / `interrupted` run shows the only action, **Retry now**, which posts
 *    `POST /runs/{id}/retry` (the endpoint ships in slice 3.4).
 *
 * The `api/runs` (detail) + `api/history` (retry) modules are mocked.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { RunDetailResponse } from "../api/runs";

const runMocks = vi.hoisted(() => ({ getRun: vi.fn() }));
const histMocks = vi.hoisted(() => ({ retryRun: vi.fn() }));

vi.mock("../api/runs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/runs")>();
  return { ...actual, ...runMocks };
});
vi.mock("../api/history", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/history")>();
  return { ...actual, ...histMocks };
});

// Guard: a finished run never opens an EventSource (static, no live SSE).
const eventSourceSpy = vi.fn();
class FakeEventSource {
  constructor() {
    eventSourceSpy();
  }
  close() {}
  addEventListener() {}
}
vi.stubGlobal("EventSource", FakeEventSource);

import RunDetail from "./RunDetail";

function detail(partial: Partial<RunDetailResponse> & Pick<RunDetailResponse, "id" | "status">): RunDetailResponse {
  return {
    engine_run_id: "eng",
    repo: "asaficontact/DKMV",
    issue: { num: 247, title: "Fix auth" },
    workflow_id: "dev",
    agent: "claude",
    model: "claude-sonnet-4-6",
    branch: "feat/x",
    cost_usd: 3.2,
    tokens_in: 100,
    tokens_out: 50,
    turns: 5,
    duration_s: 120,
    started_at: "2026-03-07 09:12",
    finished_at: "2026-03-07 09:14",
    pr: null,
    error: null,
    stages: [],
    config: {
      repo: "asaficontact/DKMV",
      branch: "feat/x",
      feature_name: "f",
      model: "claude-sonnet-4-6",
      max_turns: 100,
      timeout_minutes: 30,
      max_budget_usd: 10,
      memory_limit: "8g",
    },
    sandbox: { image: "dkmv-sandbox:latest", mem: "8g", vcpu: 2, health: "healthy" },
    artifacts: [],
    ...partial,
  };
}

function renderDetail() {
  return render(
    <MemoryRouter>
      <RunDetail runId="run-1" repoSlug="asaficontact/DKMV" />
    </MemoryRouter>,
  );
}

describe("RunDetail (read-only finished-run view)", () => {
  it("renders a completed run read-only — no Stop control, no SSE", async () => {
    runMocks.getRun.mockResolvedValue(detail({ id: "run-1", status: "completed" }));
    renderDetail();
    await screen.findByText("Fix auth");

    expect(screen.queryByRole("button", { name: /Stop/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Retry now/ })).not.toBeInTheDocument();
    expect(eventSourceSpy).not.toHaveBeenCalled();
  });

  it("shows 'Retry now' on a failed run and posts the retry (FR-06-3)", async () => {
    runMocks.getRun.mockResolvedValue(detail({ id: "run-1", status: "failed", error: "boom" }));
    histMocks.retryRun.mockResolvedValue({ run_id: "run-1", status: "queued" });
    renderDetail();
    await screen.findByText("Fix auth");

    const retry = screen.getByRole("button", { name: /Retry now/ });
    fireEvent.click(retry);
    await waitFor(() => expect(histMocks.retryRun).toHaveBeenCalledWith("run-1"));
  });

  it("offers 'Retry now' for an interrupted run too (§6.5)", async () => {
    runMocks.getRun.mockResolvedValue(detail({ id: "run-1", status: "interrupted" }));
    renderDetail();
    await screen.findByText("Fix auth");
    expect(screen.getByRole("button", { name: /Retry now/ })).toBeInTheDocument();
  });
});
