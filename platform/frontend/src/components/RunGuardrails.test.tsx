/**
 * RunGuardrails render tests (AC-9 / FR-03-2, R-10, INV-8). Covers:
 *
 *  - a **Codex** (timeout-only) selection shows
 *    "Codex runs are time-bounded, not cost-bounded." and **hides** the Max-budget
 *    and Max-turns inputs (the API still rejects them — `400 unsupported_for_agent`);
 *  - a **Claude** (budget-capable) selection **shows** Max-budget + Max-turns and
 *    does **not** show the time-bounded copy;
 *  - the **Timeout** field is shown in both cases (the universal guardrail).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RunGuardrails, { CODEX_TIME_BOUNDED_COPY } from "./RunGuardrails";

function renderGuardrails(isCodex: boolean) {
  return render(
    <RunGuardrails
      isCodex={isCodex}
      maxBudget=""
      onMaxBudgetChange={vi.fn()}
      maxTurns=""
      onMaxTurnsChange={vi.fn()}
      timeout=""
      onTimeoutChange={vi.fn()}
    />,
  );
}

describe("RunGuardrails — Codex (timeout-only, AC-9)", () => {
  it("shows the time-bounded copy for a Codex selection", () => {
    renderGuardrails(true);
    expect(screen.getByText(CODEX_TIME_BOUNDED_COPY)).toBeInTheDocument();
    // The exact AC-9 phrase is rendered (not a paraphrase).
    expect(
      screen.getByText("Codex runs are time-bounded, not cost-bounded."),
    ).toBeInTheDocument();
  });

  it("hides the Max-budget and Max-turns fields for a Codex selection (R-10)", () => {
    renderGuardrails(true);
    expect(screen.queryByLabelText("Max budget")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Max turns")).not.toBeInTheDocument();
  });

  it("still shows the Timeout field for Codex (its only guardrail)", () => {
    renderGuardrails(true);
    expect(screen.getByLabelText("Timeout in minutes")).toBeInTheDocument();
  });
});

describe("RunGuardrails — Claude (budget-capable)", () => {
  it("shows the Max-budget and Max-turns fields for a Claude selection", () => {
    renderGuardrails(false);
    expect(screen.getByLabelText("Max budget")).toBeInTheDocument();
    expect(screen.getByLabelText("Max turns")).toBeInTheDocument();
  });

  it("does not show the time-bounded copy for Claude", () => {
    renderGuardrails(false);
    expect(screen.queryByText(CODEX_TIME_BOUNDED_COPY)).not.toBeInTheDocument();
  });

  it("shows the Timeout field for Claude too", () => {
    renderGuardrails(false);
    expect(screen.getByLabelText("Timeout in minutes")).toBeInTheDocument();
  });
});
