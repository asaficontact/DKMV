/**
 * PauseCard render + submit tests (AC-19 / §6.1 / FR-05).
 *
 * The decision card uses the **engine-authoritative** option shape
 * `{value, label, description?}` (NOT the `data.jsx` `{label, description}` mock).
 * Covers:
 *
 *  - the **recommended** marker tracks the option whose **`value === default`**
 *    (NOT a label match) — including the case where a *non-first* option is the
 *    default and where label≠value;
 *  - **Approve & continue** posts `{answers:{question_id: <chosen VALUE>},
 *    skip_remaining:false}` — the chosen **value**, never the label;
 *  - selecting a different option changes the posted value;
 *  - **Ship as-is** and **Abort** post `skip_remaining:true`;
 *  - the card renders the engine `label`/`description`, the `PAUSED · after
 *    {task_name}` badge, the question, and the `context.summary`.
 *
 * `onSubmit` is injected as a spy so no network is touched.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PauseCard, { type PauseRequest } from "./PauseCard";

/** Click + flush the async submit's trailing state updates (avoids act() warns). */
async function clickAndFlush(text: string): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByText(text));
  });
}

/** A plan-style pause where the default is a NON-first option and label≠value. */
const REQUEST: PauseRequest = {
  task_name: "Analyze",
  questions: [
    {
      id: "phases",
      question: "How would you like to proceed?",
      options: [
        { value: "merge34", label: "Merge phases 3 & 4", description: "Combine the last two." },
        { value: "all4", label: "Proceed with all 4 phases", description: "Keep all four." },
        { value: "edit", label: "Let me edit the plan first" },
      ],
      default: "all4",
    },
  ],
  context: { summary: "I found 4 candidate phases for this implementation." },
};

describe("PauseCard", () => {
  it("marks the recommended option by value===default (not label, not first)", () => {
    render(<PauseCard runId="r1" request={REQUEST} onSubmit={vi.fn()} />);
    // The recommended marker sits on the option whose VALUE is the default
    // ("all4" → "Proceed with all 4 phases"), not the first row.
    const marker = screen.getByTestId("recommended-marker");
    const row = marker.closest("button");
    expect(row).not.toBeNull();
    expect(row?.textContent).toContain("Proceed with all 4 phases");
    expect(row?.textContent).not.toContain("Merge phases 3 & 4");
  });

  it("renders the engine label + description + badge + question + summary", () => {
    render(<PauseCard runId="r1" request={REQUEST} onSubmit={vi.fn()} />);
    expect(screen.getByText("PAUSED · after Analyze")).toBeInTheDocument();
    expect(screen.getByText("How would you like to proceed?")).toBeInTheDocument();
    expect(
      screen.getByText("I found 4 candidate phases for this implementation."),
    ).toBeInTheDocument();
    expect(screen.getByText("Merge phases 3 & 4")).toBeInTheDocument();
    expect(screen.getByText("Combine the last two.")).toBeInTheDocument();
  });

  it("Approve posts the chosen option VALUE (not the label), skip_remaining false", async () => {
    const onSubmit = vi.fn().mockResolvedValue({ resolved: true });
    render(<PauseCard runId="run-uuid" request={REQUEST} onSubmit={onSubmit} />);

    // Default selection is the recommended value ("all4").
    await clickAndFlush("Approve & continue");
    expect(onSubmit).toHaveBeenCalledWith("run-uuid", {
      answers: { phases: "all4" },
      skip_remaining: false,
    });
  });

  it("selecting another option posts that option's value", async () => {
    const onSubmit = vi.fn().mockResolvedValue({ resolved: true });
    render(<PauseCard runId="run-uuid" request={REQUEST} onSubmit={onSubmit} />);

    // Pick the first row ("Merge phases 3 & 4" → value "merge34").
    fireEvent.click(screen.getByText("Merge phases 3 & 4"));
    await clickAndFlush("Approve & continue");
    expect(onSubmit).toHaveBeenCalledWith("run-uuid", {
      answers: { phases: "merge34" },
      skip_remaining: false,
    });
  });

  it("Ship as-is and Abort set skip_remaining true with no answers", async () => {
    const onSubmit = vi.fn().mockResolvedValue({ resolved: true });
    const { rerender } = render(<PauseCard runId="r1" request={REQUEST} onSubmit={onSubmit} />);

    await clickAndFlush("Ship as-is");
    expect(onSubmit).toHaveBeenLastCalledWith("r1", { answers: {}, skip_remaining: true });

    rerender(<PauseCard runId="r1" request={REQUEST} onSubmit={onSubmit} />);
    await clickAndFlush("Abort");
    expect(onSubmit).toHaveBeenLastCalledWith("r1", { answers: {}, skip_remaining: true });
  });
});
