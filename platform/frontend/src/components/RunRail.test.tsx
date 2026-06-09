/**
 * RunRail (FR-04-5, AC-16). Asserts the verbatim run-config keys render in order,
 * a null guardrail shows "null", the sandbox image + health line show, and a
 * linked PR section appears only when a PR is present.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunDetailResponse } from "../api/runs";
import RunRail from "./RunRail";

function detail(overrides: Partial<RunDetailResponse> = {}): RunDetailResponse {
  return {
    id: "run-uuid",
    engine_run_id: "250608-1200-abc",
    repo: "asaficontact/DKMV",
    issue: { num: 12, title: "Rotate token" },
    workflow_id: "plan",
    agent: "claude",
    model: "claude-sonnet-4-6",
    status: "running",
    branch: "feat/codex",
    cost_usd: 4.18,
    tokens_in: 100,
    tokens_out: 50,
    turns: 10,
    duration_s: 120,
    started_at: "2026-06-08T12:00:00Z",
    finished_at: null,
    pr: null,
    error: null,
    stages: [],
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

const CONFIG_KEYS = [
  "repo",
  "branch",
  "feature_name",
  "model",
  "max_turns",
  "timeout_minutes",
  "max_budget_usd",
  "memory_limit",
];

describe("RunRail", () => {
  it("renders the verbatim run-config keys (AC-16)", () => {
    render(<RunRail run={detail()} />);
    for (const key of CONFIG_KEYS) {
      expect(screen.getByText(key)).toBeInTheDocument();
    }
    // A null guardrail renders "null".
    expect(screen.getByTestId("config-max_budget_usd")).toHaveTextContent("null");
    // feature_name value present.
    expect(screen.getByTestId("config-feature_name")).toHaveTextContent("rotate_token");
  });

  it("renders the sandbox image + healthy line for a running run", () => {
    render(<RunRail run={detail()} />);
    expect(screen.getByText("dkmv-sandbox:latest")).toBeInTheDocument();
    expect(screen.getByText("8g · 2 vCPU · healthy")).toBeInTheDocument();
  });

  it("shows the live artifact badge", () => {
    render(<RunRail run={detail()} />);
    expect(screen.getByText("session.log")).toBeInTheDocument();
    expect(screen.getByText("live")).toBeInTheDocument();
  });

  it("omits the PR section when no PR is linked", () => {
    render(<RunRail run={detail({ pr: null })} />);
    expect(screen.queryByText("Pull request")).not.toBeInTheDocument();
  });

  it("renders the PR section when a PR is present", () => {
    render(
      <RunRail
        run={detail({ pr: { num: 88, title: "fix(auth): rotate token", checks: null } })}
        prUrl="https://github.com/asaficontact/DKMV/pull/88"
      />,
    );
    expect(screen.getByText("Pull request")).toBeInTheDocument();
    expect(screen.getByText("#88")).toBeInTheDocument();
  });
});
