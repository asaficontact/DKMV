/**
 * Runs history & analytics screen tests (AC-5, AC-7, AC-8, AC-9 / FR-06).
 *
 * Covers:
 *  - AC-5 — the runs table renders the FR-06-4 columns; a sort header toggles the
 *    row order; a `workflow`/`agent`/`status` filter narrows the rows; a row click
 *    opens the read-only finished-run view (`/runs/:id/detail`).
 *  - AC-7 — the five aggregate cards + the SpendChart render from `GET /stats`; the
 *    spend is the Codex-excluded backend total + the "excludes Codex" footnote.
 *  - AC-8 — the rate-limit health row renders Anthropic/OpenAI usage ("—" when
 *    null); the retry-queue card renders `attempt N/3 · due in …` and its
 *    "Retry now" posts `POST /runs/{id}/retry`.
 *  - AC-9 — the empty state renders "No runs yet" + "Run your first issue".
 *
 * The `api/history` module is mocked so no real network is touched.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type {
  RetryQueuePage,
  RunSummary,
  RunsPage,
  StatsResponse,
} from "../api/history";

const mocks = vi.hoisted(() => ({
  listRuns: vi.fn(),
  getStats: vi.fn(),
  getRetryQueue: vi.fn(),
  retryRun: vi.fn(),
}));

vi.mock("../api/history", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/history")>();
  return { ...actual, ...mocks };
});

import History from "./History";

function run(partial: Partial<RunSummary> & Pick<RunSummary, "id">): RunSummary {
  return {
    engine_run_id: null,
    repo: "asaficontact/DKMV",
    issue_num: 1,
    issue_title: "An issue",
    workflow_id: "dev",
    agent: "claude",
    model: "claude-sonnet-4-6",
    status: "completed",
    branch: "feat/x",
    cost_usd: 1.0,
    tokens_in: 100,
    tokens_out: 50,
    turns: 5,
    duration_s: 120,
    started_at: "2026-03-07 09:12",
    finished_at: "2026-03-07 09:14",
    pr_num: null,
    ...partial,
  };
}

const STATS: StatsResponse = {
  total_runs: 3,
  success_rate: 0.5,
  total_spend_usd: 12.34,
  tokens: 250_000,
  agent_hours: 1.5,
  spend_series: [
    { date: "2026-03-05", usd: 4.0 },
    { date: "2026-03-06", usd: 3.0 },
    { date: "2026-03-07", usd: 5.34 },
  ],
  rate_limits: {
    github: {
      remaining: 38,
      limit: 100,
      reset: null,
      used_pct: 0.62,
      secondary_limited: false,
      secondary_retry_after: 0,
    },
    anthropic: {
      remaining: null,
      limit: null,
      reset: null,
      used_pct: null,
      secondary_limited: false,
      secondary_retry_after: 0,
    },
    openai: {
      remaining: null,
      limit: null,
      reset: null,
      used_pct: null,
      secondary_limited: false,
      secondary_retry_after: 0,
    },
  },
};

function setup(opts: {
  runs?: RunSummary[];
  retry?: RetryQueuePage["items"];
  stats?: StatsResponse;
}) {
  const page: RunsPage = { items: opts.runs ?? [], next_cursor: null };
  mocks.listRuns.mockResolvedValue(page);
  mocks.getStats.mockResolvedValue(opts.stats ?? STATS);
  mocks.getRetryQueue.mockResolvedValue({ items: opts.retry ?? [], next_cursor: null });
  mocks.retryRun.mockResolvedValue({ run_id: "r1", status: "queued" });
  const onOpenRun = vi.fn();
  render(
    <MemoryRouter>
      <History repoSlug="asaficontact/DKMV" onOpenRun={onOpenRun} />
    </MemoryRouter>,
  );
  return { onOpenRun };
}

describe("History (Screen E)", () => {
  it("renders the FR-06-4 columns and a row opens the read-only view (AC-5)", async () => {
    const { onOpenRun } = setup({
      runs: [run({ id: "run-aaa", issue_num: 247, issue_title: "Fix auth" })],
    });
    await screen.findByText("Fix auth");

    // FR-06-4 column headers
    for (const col of ["Run", "Issue", "Workflow", "Agent", "Status", "Cost", "Turns", "Duration", "Started"]) {
      expect(screen.getByText(col)).toBeInTheDocument();
    }

    // Row click → read-only finished-run view
    fireEvent.click(screen.getByText("Fix auth"));
    expect(onOpenRun).toHaveBeenCalledWith("run-aaa");
  });

  it("sorts when a sortable header is clicked (AC-5)", async () => {
    setup({
      runs: [
        run({ id: "low", cost_usd: 1.0, issue_title: "cheap" }),
        run({ id: "high", cost_usd: 9.0, issue_title: "pricey" }),
      ],
    });
    await screen.findByText("cheap");

    // Click "Cost" → desc first (pricey above cheap)
    fireEvent.click(screen.getByText("Cost"));
    let firstId = document.querySelector(".runs-row .runs-id")?.textContent;
    expect(firstId).toBe("high");

    // Click again → asc (cheap above pricey)
    fireEvent.click(screen.getByText("Cost"));
    firstId = document.querySelector(".runs-row .runs-id")?.textContent;
    expect(firstId).toBe("low");
  });

  it("narrows rows when a filter is applied (AC-5)", async () => {
    setup({
      runs: [
        run({ id: "claude-run", agent: "claude", issue_title: "by claude" }),
        run({ id: "codex-run", agent: "codex", cost_usd: null, issue_title: "by codex" }),
      ],
    });
    await screen.findByText("by claude");
    expect(screen.getByText("by codex")).toBeInTheDocument();

    const agentFilter = screen.getByLabelText("Filter by agent");
    fireEvent.change(agentFilter, { target: { value: "claude" } });

    expect(screen.getByText("by claude")).toBeInTheDocument();
    expect(screen.queryByText("by codex")).not.toBeInTheDocument();
  });

  it("renders the aggregate cards + SpendChart with the Codex-excluded footnote (AC-7)", async () => {
    setup({ runs: [run({ id: "r1" })] });
    await screen.findByText("Total runs");

    expect(screen.getByText("Success rate")).toBeInTheDocument();
    expect(screen.getByText("Total spend")).toBeInTheDocument();
    expect(screen.getByText("Tokens")).toBeInTheDocument();
    expect(screen.getByText("Agent-hours")).toBeInTheDocument();
    // Codex-excluded total spend (from GET /stats, not a run-list sum) — appears
    // on both the spend card and the chart total (the series sums to the same).
    expect(screen.getAllByText("$12.34").length).toBeGreaterThan(0);
    // the footnote (greppable: "excludes Codex" / "cost not reported")
    expect(screen.getByText("excludes Codex (cost not reported)")).toBeInTheDocument();
  });

  it("renders the rate-limit health row with '—' for a null provider (AC-8)", async () => {
    setup({ runs: [run({ id: "r1" })] });
    await screen.findByText(/Rate limits healthy/);
    // anthropic/openai report null usage today → rendered "—" (not a fabricated %)
    expect(screen.getByText(/Anthropic — · OpenAI —/)).toBeInTheDocument();
  });

  it("renders a retry-queue row and 'Retry now' posts the retry (AC-8)", async () => {
    setup({
      runs: [run({ id: "r1" })],
      retry: [{ id: "queued-run", issue: 230, attempt: 2, dueIn: "2m 10s", lastError: "boom" }],
    });
    await screen.findByText("Retry queue");

    // open the collapsible card
    fireEvent.click(screen.getByText("Retry queue"));
    expect(await screen.findByText("attempt 2/3 · due in 2m 10s")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Retry now/ }));
    await waitFor(() => expect(mocks.retryRun).toHaveBeenCalledWith("queued-run"));
  });

  it("renders the empty state when there are no runs (AC-9)", async () => {
    setup({ runs: [] });
    expect(await screen.findByText("No runs yet")).toBeInTheDocument();
    expect(screen.getByText("Run your first issue")).toBeInTheDocument();
  });

  it("renders a Codex run's cost as '—' (INV-8)", async () => {
    setup({ runs: [run({ id: "codex-run", agent: "codex", cost_usd: null, issue_title: "codex run" })] });
    await screen.findByText("codex run");
    const row = screen.getByText("codex run").closest(".runs-row") as HTMLElement;
    expect(within(row).getByText("—")).toBeInTheDocument();
  });
});
