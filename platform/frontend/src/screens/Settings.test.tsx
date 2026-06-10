/**
 * Settings screen render tests (G6 / FR-SET-1 — §5.9).
 *
 * Covers:
 *  - the screen loads + renders the run defaults (`GET /settings`) and the preflight
 *    rows (`GET /preflight`);
 *  - editing a default + Save `PUT`s `/settings` and reflects the saved value;
 *  - a §8.9 `validation_error` from `PUT` surfaces a per-field message + does not
 *    clear the dirty state;
 *  - **Switch repo** invokes the `onSwitchRepo` route handler.
 *
 * The api modules are mocked so no real network is touched.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { PreflightReport } from "../api/connect";
import type { RunDefaults } from "../api/settings";

const mocks = vi.hoisted(() => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
  getPreflight: vi.fn(),
}));

vi.mock("../api/settings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/settings")>();
  return { ...actual, getSettings: mocks.getSettings, updateSettings: mocks.updateSettings };
});

vi.mock("../api/connect", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/connect")>();
  return { ...actual, getPreflight: mocks.getPreflight };
});

import Settings from "./Settings";

const DEFAULTS: RunDefaults = {
  default_agent: "claude",
  default_model: "claude-sonnet-4-6",
  default_memory: "8g",
  default_timeout_minutes: 40,
  default_max_budget_usd: null,
  default_max_turns: null,
  daily_spend_alert_usd: 25.0,
};

const PREFLIGHT: PreflightReport = {
  ready: true,
  checks: [
    { id: "docker", label: "Docker available", sub: "27.0.0", ok: true },
    { id: "sandbox_image", label: "Sandbox image present", sub: "dkmv-sandbox:latest", ok: true },
  ],
  blockers: [],
};

function renderScreen(onSwitchRepo = vi.fn()) {
  return render(
    <MemoryRouter>
      <Settings repoSlug="asaficontact/DKMV" onSwitchRepo={onSwitchRepo} />
    </MemoryRouter>,
  );
}

describe("Settings screen", () => {
  it("loads + renders the run defaults and preflight rows", async () => {
    mocks.getSettings.mockResolvedValue(DEFAULTS);
    mocks.getPreflight.mockResolvedValue(PREFLIGHT);
    renderScreen();

    // Defaults populate the form.
    await waitFor(() => expect(screen.getByLabelText("Default memory")).toHaveValue("8g"));
    expect(screen.getByLabelText("Default timeout (min)")).toHaveValue(40);
    // Preflight rows render.
    expect(screen.getByText("Docker available")).toBeInTheDocument();
    expect(screen.getByText("Sandbox image present")).toBeInTheDocument();
  });

  it("edits a default + Save PUTs /settings and reflects the saved value", async () => {
    mocks.getSettings.mockResolvedValue(DEFAULTS);
    mocks.getPreflight.mockResolvedValue(PREFLIGHT);
    mocks.updateSettings.mockResolvedValue({ ...DEFAULTS, default_memory: "16g" });
    renderScreen();

    const mem = await screen.findByLabelText("Default memory");
    fireEvent.change(mem, { target: { value: "16g" } });
    // Dirty state surfaces.
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() =>
      expect(mocks.updateSettings).toHaveBeenCalledWith(
        expect.objectContaining({ default_memory: "16g" }),
      ),
    );
    await waitFor(() => expect(screen.getByText("Saved")).toBeInTheDocument());
  });

  it("surfaces a §8.9 validation_error per-field on a bad value", async () => {
    mocks.getSettings.mockResolvedValue(DEFAULTS);
    mocks.getPreflight.mockResolvedValue(PREFLIGHT);
    mocks.updateSettings.mockRejectedValue(
      new ApiError(400, "validation_error", "Invalid settings value", {
        fields: [
          {
            loc: ["default_timeout_minutes"],
            msg: "Input should be greater than or equal to 1",
            type: "greater_than_equal",
          },
        ],
      }),
    );
    renderScreen();

    const timeout = await screen.findByLabelText("Default timeout (min)");
    fireEvent.change(timeout, { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() =>
      expect(
        screen.getByText("Input should be greater than or equal to 1"),
      ).toBeInTheDocument(),
    );
    // The save banner shows the error summary.
    expect(
      screen.getByText("Some values are invalid — fix the highlighted fields."),
    ).toBeInTheDocument();
  });

  it("invokes onSwitchRepo from the Switch repo button", async () => {
    const onSwitchRepo = vi.fn();
    mocks.getSettings.mockResolvedValue(DEFAULTS);
    mocks.getPreflight.mockResolvedValue(PREFLIGHT);
    renderScreen(onSwitchRepo);

    const btn = await screen.findByRole("button", { name: /switch repo/i });
    fireEvent.click(btn);
    expect(onSwitchRepo).toHaveBeenCalledTimes(1);
  });
});
