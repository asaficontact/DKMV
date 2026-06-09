/**
 * Screen E — Runs history & analytics (F10 / §5.7, FR-06). Ported from
 * `history.jsx RunsHistory`, mounted inside the global chrome ({@link AppLayout}).
 *
 * Owns the screen's data + interaction state:
 *  - **Aggregate cards** (Total runs / Success rate / Total spend / Tokens /
 *    Agent-hours) + the {@link SpendChart} — all from `GET /stats` (FR-06-1). The
 *    spend card + chart are **Codex-excluded** with the "excludes Codex" footnote.
 *  - **Rate-limit health row** + the {@link RetryQueue} card (FR-06-2/3) — from
 *    `GET /stats.rate_limits` and `GET /retry-queue`.
 *  - **Filters** (`workflow`/`agent`/`status`) + the sortable {@link RunsTable}
 *    (FR-06-4/5) — from `GET /runs`. A row click opens the **read-only**
 *    finished-run view (`/runs/{id}/detail` via `onOpenRun`).
 *  - **Empty state** (`RunsEmpty`) when there are zero runs (AC-9).
 *
 * **Sort/filter ownership.** The screen holds the sort + filter state and computes
 * the filtered + sorted rows; the {@link RunsTable} is the pure render. So a render
 * test can assert a header click toggles order and a filter narrows rows (AC-5).
 *
 * **INV-8 (binding).** Spend (`total_spend_usd` + chart) is the backend's
 * Codex-excluded projection — this screen never sums a run list for spend, and a
 * Codex run's cost cell is "—".  **INV-14.** No hex literals — all color is
 * token-driven; status is the {@link StateBadge} (icon + label).
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import "./history.css";
import {
  type RateLimitSlot,
  type RetryEntry,
  type RunSummary,
  type StatsResponse,
  getRetryQueue,
  getStats,
  listRuns,
} from "../api/history";
import AppLayout from "../chrome/AppLayout";
import {
  CheckIcon,
  ChartIcon,
  ClockIcon,
  CoinIcon,
  FilterIcon,
  PlayIcon,
  RunsIcon,
  TokenIcon,
} from "../components/icons";
import RetryQueue from "../components/RetryQueue";
import RunsTable, { type SortKey, type SortState } from "../components/RunsTable";
import SpendChart from "../components/SpendChart";
import StatCard from "../components/StatCard";

type LoadPhase = "loading" | "ready" | "error";

const WORKFLOW_OPTIONS: [string, string][] = [
  ["all", "All workflows"],
  ["plan", "🧭 Plan"],
  ["dev", "🛠️ Dev"],
  ["qa", "🔍 QA"],
  ["docs", "📝 Docs"],
  ["ship", "🚀 Ship"],
];

const AGENT_OPTIONS: [string, string][] = [
  ["all", "All agents"],
  ["claude", "Claude"],
  ["codex", "Codex"],
];

const STATUS_OPTIONS: [string, string][] = [
  ["all", "All statuses"],
  ["running", "Running"],
  ["paused", "Paused"],
  ["completed", "Completed"],
  ["failed", "Failed"],
  ["cancelled", "Cancelled"],
  ["interrupted", "Interrupted"],
  ["timed_out", "Timed out"],
];

/** Map a {@link SortKey} to the {@link RunSummary} field it sorts on. */
function sortValue(run: RunSummary, key: SortKey): number | string {
  switch (key) {
    case "id":
      return run.id;
    case "status":
      return run.status ?? "";
    case "cost":
      return run.cost_usd ?? 0;
    case "turns":
      return run.turns;
    case "dur":
      return run.duration_s ?? 0;
    case "started":
      return run.started_at ?? "";
  }
}

export interface HistoryProps {
  /** The connected repo slug (for the chrome + the run-detail back link). */
  repoSlug?: string;
  /** Open a run's read-only finished view. */
  onOpenRun: (id: string) => void;
}

export default function History({ repoSlug = "", onOpenRun }: HistoryProps) {
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [retry, setRetry] = useState<RetryEntry[]>([]);

  const [wf, setWf] = useState("all");
  const [agent, setAgent] = useState("all");
  const [status, setStatus] = useState("all");
  const [sort, setSort] = useState<SortState>({ key: "started", dir: "desc" });

  const load = useCallback(async () => {
    try {
      const [page, statsBody, retryBody] = await Promise.all([
        listRuns({ repo: repoSlug || undefined, limit: 100 }),
        getStats(),
        getRetryQueue(),
      ]);
      setRuns(page.items);
      setStats(statsBody);
      setRetry(retryBody.items);
      setPhase("ready");
    } catch {
      setPhase((prev) => (prev === "loading" ? "error" : prev));
    }
  }, [repoSlug]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleSort = useCallback((key: SortKey) => {
    setSort((s) => ({ key, dir: s.key === key && s.dir === "desc" ? "asc" : "desc" }));
  }, []);

  // Filter then sort the rows (the parent owns this so RunsTable is a pure render).
  const filtered = useMemo(() => {
    const matched = runs.filter(
      (r) =>
        (wf === "all" || r.workflow_id === wf) &&
        (agent === "all" || r.agent === agent) &&
        (status === "all" || r.status === status),
    );
    const sorted = [...matched].sort((a, b) => {
      const av = sortValue(a, sort.key);
      const bv = sortValue(b, sort.key);
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [runs, wf, agent, status, sort]);

  return (
    <AppLayout
      repoSlug={repoSlug}
      title={`${repoSlug || "Runs"} · History`}
      activeNav="runs"
      onRefresh={() => void load()}
    >
      {phase === "loading" && <LoadingState />}
      {phase === "error" && <ErrorState onRetry={() => void load()} />}
      {phase === "ready" && runs.length === 0 && <RunsEmpty />}
      {phase === "ready" && runs.length > 0 && (
        <div className="history-screen">
          {/* aggregate cards + spend chart */}
          <div className="history-cards">
            <StatCard Icon={RunsIcon} label="Total runs" value={String(stats?.total_runs ?? 0)} />
            <StatCard
              Icon={CheckIcon}
              label="Success rate"
              value={`${Math.round((stats?.success_rate ?? 0) * 100)}%`}
              accentVar="var(--st-done)"
              sub={`${countCompleted(runs)} completed`}
            />
            <StatCard
              Icon={CoinIcon}
              label="Total spend"
              value={`$${(stats?.total_spend_usd ?? 0).toFixed(2)}`}
              accentVar="var(--accent)"
              sub="excludes Codex"
            />
            <StatCard
              Icon={TokenIcon}
              label="Tokens"
              value={`${((stats?.tokens ?? 0) / 1000).toFixed(0)}k`}
            />
            <StatCard
              Icon={ClockIcon}
              label="Agent-hours"
              value={(stats?.agent_hours ?? 0).toFixed(1)}
            />
            <SpendChart series={stats?.spend_series ?? []} />
          </div>

          {/* rate-limit health row + retry queue */}
          <div className="history-health-row">
            <RateLimitHealth rateLimits={stats?.rate_limits ?? null} />
            <RetryQueue entries={retry} onRetried={() => void load()} />
          </div>

          {/* filters */}
          <div className="history-filters">
            <span className="cap history-filter-label">
              <FilterIcon size={14} />
              Filter
            </span>
            <FilterSelect value={wf} onChange={setWf} options={WORKFLOW_OPTIONS} ariaLabel="Filter by workflow" />
            <FilterSelect value={agent} onChange={setAgent} options={AGENT_OPTIONS} ariaLabel="Filter by agent" />
            <FilterSelect value={status} onChange={setStatus} options={STATUS_OPTIONS} ariaLabel="Filter by status" />
            <span className="cap history-filter-count">
              {filtered.length} of {runs.length} runs
            </span>
          </div>

          <RunsTable rows={filtered} sort={sort} onSort={toggleSort} onOpenRun={onOpenRun} />
        </div>
      )}
    </AppLayout>
  );
}

/** Completed-run count for the success-rate card sub-line. */
function countCompleted(runs: RunSummary[]): number {
  return runs.filter((r) => r.status === "completed").length;
}

/** Render a usage percentage from a provider slot, or "—" when unknown (AC-8). */
function usageText(slot: RateLimitSlot | undefined): string {
  if (!slot || slot.used_pct == null) return "—";
  return `${Math.round(slot.used_pct * 100)}%`;
}

/**
 * The rate-limit health row (FR-06-2). Shows "Rate limits healthy" + per-provider
 * usage (Anthropic / OpenAI / GitHub) and a usage bar. A provider with no observed
 * header (`used_pct === null`) renders **"—"** rather than a fabricated percentage
 * (3.1 returns `null` for anthropic/openai today — handle gracefully, AC-8).
 */
function RateLimitHealth({
  rateLimits,
}: {
  rateLimits: StatsResponse["rate_limits"] | null;
}) {
  const anthropic = usageText(rateLimits?.anthropic);
  const openai = usageText(rateLimits?.openai);
  const github = usageText(rateLimits?.github);
  // Bar width tracks the highest known provider usage; 0 when all unknown.
  const known = [rateLimits?.github, rateLimits?.anthropic, rateLimits?.openai]
    .map((s) => s?.used_pct)
    .filter((p): p is number => p != null);
  const peakPct = known.length ? Math.max(...known) : 0;
  const limited = rateLimits?.github?.secondary_limited ?? false;
  return (
    <div className="card health-row">
      <span className={`health-dot${limited ? " is-limited" : ""}`} aria-hidden />
      <span className="health-title">
        {limited ? "Rate limited" : "Rate limits healthy"}
      </span>
      <span className="cap mono health-usage">
        Anthropic {anthropic} · OpenAI {openai} · GitHub {github} used this hour
      </span>
      <div className="health-spacer" />
      <div className="health-bar" aria-hidden>
        <div className="health-bar-fill" style={{ width: `${Math.round(peakPct * 100)}%` }} />
      </div>
    </div>
  );
}

/** A styled native `<select>` for a history filter (ported from `FilterSelect`). */
function FilterSelect({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  options: [string, string][];
  ariaLabel: string;
}) {
  return (
    <select
      className="select history-filter-select"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={ariaLabel}
    >
      {options.map(([v, label]) => (
        <option key={v} value={v}>
          {label}
        </option>
      ))}
    </select>
  );
}

/** Empty state (AC-9) — "No runs yet" + "Run your first issue". */
function RunsEmpty() {
  return (
    <div className="history-empty">
      <div className="history-empty-inner fade-in">
        <span className="history-empty-ico" aria-hidden>
          <RunsIcon size={44} />
        </span>
        <h2 className="history-empty-title">No runs yet</h2>
        <p className="history-empty-text">
          Once you run an issue, every run shows up here with its full cost, token,
          and duration history.
        </p>
        <button type="button" className="btn btn-primary btn-lg">
          <PlayIcon size={16} />
          Run your first issue
        </button>
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="history-state">
      <div className="run-bar history-loading-bar" />
      <p className="cap">Loading runs…</p>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="history-state" role="alert">
      <ChartIcon size={28} />
      <h2 className="history-state-title">Couldn&rsquo;t load history</h2>
      <p className="cap">We hit a snag reaching the control plane.</p>
      <button type="button" className="btn btn-soft" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}
