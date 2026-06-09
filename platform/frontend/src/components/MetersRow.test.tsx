/**
 * MetersRow (FR-04-2, INV-7/INV-8). Asserts:
 *  - the cost shown is the SEGMENT-SUM value passed in (the prop), formatted $x.xx;
 *  - a Codex run (cost excluded) renders "—", NOT "$0.00" (AC-13 / INV-8) — even
 *    when the numeric cost is null;
 *  - tokens render for both agents (Codex tokens count);
 *  - elapsed formats as `{m}m {ss}s` and progress shows a percentage.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MetersRow, { formatClock, formatCost } from "./MetersRow";

describe("MetersRow formatting", () => {
  it("formats elapsed as {m}m {ss}s", () => {
    expect(formatClock(155)).toBe("2m 35s");
    expect(formatClock(2611)).toBe("43m 31s");
    expect(formatClock(5)).toBe("0m 05s");
  });

  it("formats a segment-sum cost as $x.xx", () => {
    expect(formatCost(13.28, false)).toBe("$13.28");
    expect(formatCost(0, false)).toBe("$0.00");
  });

  it("renders Codex cost as — not $0.00 (INV-8)", () => {
    expect(formatCost(null, true)).toBe("—");
    expect(formatCost(0, true)).toBe("—");
  });
});

describe("MetersRow render", () => {
  it("shows the passed segment-sum cost (not a raw field)", () => {
    render(
      <MetersRow
        live
        elapsedSeconds={155}
        costUsd={12.0}
        tokensIn={71200}
        tokensOut={18400}
        turns={37}
        progress={0.62}
      />,
    );
    expect(screen.getByText("$12.00")).toBeInTheDocument();
    expect(screen.getByText("2m 35s")).toBeInTheDocument();
    expect(screen.getByText("37")).toBeInTheDocument();
    expect(screen.getByText("62%")).toBeInTheDocument();
  });

  it("renders — for a Codex run but still shows its tokens (AC-13)", () => {
    render(
      <MetersRow
        live
        elapsedSeconds={10}
        costUsd={null}
        costExcluded
        tokensIn={1200}
        tokensOut={400}
        turns={15}
        progress={0.2}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
    // Tokens still render.
    expect(screen.getByText("1,200 · 400")).toBeInTheDocument();
  });
});
