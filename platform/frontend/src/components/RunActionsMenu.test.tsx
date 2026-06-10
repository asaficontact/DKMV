/**
 * RunActionsMenu tests (FR-04-1, ship-gap G7). Covers:
 *  - the `⋯` menu opens and shows the live items (exec + keep-alive info);
 *  - "Run a command in the container" opens the exec panel and submits the command
 *    to the exec endpoint, rendering the (redacted) stdout;
 *  - "Retry run" shows only for a failed run and posts the retry;
 *  - "View PR #{n}" shows only for a completed run with the correct GitHub URL;
 *  - the menu is keyboard-accessible (Escape closes; arrow keys move focus).
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import RunActionsMenu from "./RunActionsMenu";

function setup(overrides: Partial<React.ComponentProps<typeof RunActionsMenu>> = {}) {
  const onExec = vi.fn().mockResolvedValue({ run_id: "r1", output: "drwxr-xr-x workspace" });
  const onRetry = vi.fn().mockResolvedValue({ run_id: "r1", status: "queued" });
  render(
    <RunActionsMenu
      runId="r1"
      status="running"
      live
      prNum={null}
      prUrl={null}
      onExec={onExec}
      onRetry={onRetry}
      {...overrides}
    />,
  );
  return { onExec, onRetry };
}

function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: /run actions/i }));
  return screen.getByRole("menu", { name: /run actions/i });
}

afterEach(() => vi.clearAllMocks());

describe("RunActionsMenu", () => {
  it("opens the ⋯ menu and shows the live items", () => {
    setup();
    const menu = openMenu();
    expect(within(menu).getByText("Run a command in the container")).toBeInTheDocument();
    // Keep alive is an honest informational (disabled) item, not a live toggle.
    expect(within(menu).getByText(/Keep alive on finish/i)).toBeInTheDocument();
  });

  it("exec submits the command to the endpoint and shows the redacted output", async () => {
    const { onExec } = setup();
    openMenu();
    fireEvent.click(screen.getByText("Run a command in the container"));
    const input = await screen.findByLabelText(/command to run in the container/i);
    fireEvent.change(input, { target: { value: "ls -la /workspace" } });
    fireEvent.click(screen.getByRole("button", { name: /^Run$/ }));
    await waitFor(() => expect(onExec).toHaveBeenCalledWith("r1", "ls -la /workspace"));
    expect(await screen.findByLabelText(/command output/i)).toHaveTextContent(
      "drwxr-xr-x workspace",
    );
  });

  it("shows 'Retry run' for a failed run and posts the retry", async () => {
    const { onRetry } = setup({ status: "failed", live: false });
    openMenu();
    const retry = screen.getByRole("menuitem", { name: /Retry run/i });
    fireEvent.click(retry);
    await waitFor(() => expect(onRetry).toHaveBeenCalledWith("r1"));
  });

  it("does NOT show 'Retry run' for a running run", () => {
    setup({ status: "running", live: true });
    openMenu();
    expect(screen.queryByRole("menuitem", { name: /Retry run/i })).not.toBeInTheDocument();
  });

  it("shows 'View PR #{n}' for a completed run with the correct GitHub URL", () => {
    setup({
      status: "completed",
      live: false,
      prNum: 42,
      prUrl: "https://github.com/asaficontact/DKMV/pull/42",
    });
    openMenu();
    const link = screen.getByRole("menuitem", { name: /View PR #42/i });
    expect(link).toHaveAttribute("href", "https://github.com/asaficontact/DKMV/pull/42");
  });

  it("does NOT show 'View PR' for a completed run without a PR", () => {
    setup({ status: "completed", live: false, prNum: null, prUrl: null });
    // No items → the trigger renders nothing actionable; the menu has no PR item.
    expect(screen.queryByRole("button", { name: /run actions/i })).not.toBeInTheDocument();
  });

  it("is keyboard-accessible: Escape closes the menu, arrows move focus", () => {
    setup();
    const trigger = screen.getByRole("button", { name: /run actions/i });
    fireEvent.click(trigger);
    const menu = screen.getByRole("menu", { name: /run actions/i });
    // First item is focused on open.
    const first = within(menu).getByText("Run a command in the container");
    expect(first).toHaveFocus();
    // Arrow-down moves to the next focusable item.
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(first).not.toHaveFocus();
    // Escape closes and returns focus to the trigger.
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
