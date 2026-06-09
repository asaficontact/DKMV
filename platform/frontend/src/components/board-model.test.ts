/**
 * board-model unit tests. Focus: `isCostExcludedAgent` — the single-sourced
 * Codex spend-exclusion predicate (INV-8 / FR-06-1a). The literal agent name
 * lives in `COST_EXCLUDED_AGENT` (mirrors the backend) and must match the
 * In-Progress live-cost header (Board) and the card mini-meter (IssueCard).
 */
import { describe, expect, it } from "vitest";

import { COST_EXCLUDED_AGENT, isCostExcludedAgent } from "./board-model";

describe("isCostExcludedAgent (INV-8)", () => {
  it("excludes the cost-excluded agent (codex)", () => {
    expect(isCostExcludedAgent(COST_EXCLUDED_AGENT)).toBe(true);
    expect(isCostExcludedAgent("codex")).toBe(true);
  });

  it("is case/space-insensitive (mirrors the backend predicate)", () => {
    expect(isCostExcludedAgent("Codex")).toBe(true);
    expect(isCostExcludedAgent("  CODEX  ")).toBe(true);
  });

  it("does not exclude other agents or empty/null/undefined", () => {
    expect(isCostExcludedAgent("claude")).toBe(false);
    expect(isCostExcludedAgent("")).toBe(false);
    expect(isCostExcludedAgent(null)).toBe(false);
    expect(isCostExcludedAgent(undefined)).toBe(false);
  });
});
