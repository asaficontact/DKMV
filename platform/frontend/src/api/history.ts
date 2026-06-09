/**
 * History & analytics API surface (Screen E — F10 / §5.7, §8.9, FR-06). Thin
 * typed wrappers over the generic {@link apiGet}/{@link apiPost} client for the
 * Runs history screen:
 *
 *   - `GET  /runs?workflow=&agent=&status=&limit=&cursor=` — the FR-06-4
 *     `RunSummary` history page (cursor pagination → `{ items, next_cursor }`).
 *   - `GET  /runs/{id}`            — the full §8.9 detail (read-only finished view).
 *   - `GET  /stats`               — aggregate cards + spend chart + rate-limit row.
 *   - `GET  /retry-queue`         — the retry-queue card rows (empty until 3.4).
 *   - `POST /runs/{id}/retry`     — "Retry now" (the endpoint ships in 3.4 — INV-15;
 *     we wire the call now so the card is functional the moment 3.4 lands).
 *
 * **Codex cost (FR-06-1a / INV-8).** A Codex run's `cost_usd` is `null` (rendered
 * "—" and excluded from spend); we never fabricate a `$0`. Spend math is the
 * backend's Codex-excluded projection (`GET /stats`) — this client never computes
 * spend from a run list.
 *
 * **INV-2.** Nothing here ever puts a token in a URL/query — these are plain authed
 * JSON requests via {@link apiGet}/{@link apiPost} (the loopback token rides the
 * `Authorization` header; the SSE cookie is the live view's concern, not history's).
 */
import { apiGet, apiPost } from "./client";

/** One row of the `GET /runs` history page (FR-06-4 columns, backend `RunSummary`). */
export interface RunSummary {
  /** The platform run UUID (the "Run" column + the row's detail address). */
  id: string;
  engine_run_id: string | null;
  repo: string | null;
  /** The issue number (the "Issue" column `#num`). */
  issue_num: number | null;
  /** The issue title, when the backend resolves it (optional in the summary). */
  issue_title?: string | null;
  workflow_id: string | null;
  agent: string | null;
  model: string | null;
  /** Engine `RunStatus` (`running|paused|completed|failed|cancelled|timed_out`)
   *  plus the platform-only `interrupted` (§6.5). */
  status: string | null;
  branch: string | null;
  /** The segment-sum cost (INV-7); `null` for a Codex run → rendered "—" (INV-8). */
  cost_usd: number | null;
  tokens_in: number;
  tokens_out: number;
  turns: number;
  /** Total run duration in seconds (`null` while live / unknown). */
  duration_s?: number | null;
  started_at: string | null;
  finished_at: string | null;
  /** The linked PR number (the "PR" column), when present. */
  pr_num?: number | null;
}

/** The cursor-paginated `GET /runs` envelope (§8.9). */
export interface RunsPage {
  items: RunSummary[];
  /** Opaque next-page cursor (an offset string), or `null` on the last page. */
  next_cursor: string | null;
}

/** The query filters + cursor for `GET /runs` (FR-06-4, §8.9). */
export interface RunsQuery {
  /** Workflow id filter (`undefined`/`"all"` → no filter). */
  workflow?: string;
  /** Agent filter (`claude`/`codex`; `undefined`/`"all"` → no filter). */
  agent?: string;
  /** Status filter (engine `RunStatus`; `undefined`/`"all"` → no filter). */
  status?: string;
  /** Repo scope ("owner/name"). */
  repo?: string;
  /** Page size (1..100; backend caps at 100). */
  limit?: number;
  /** Opaque cursor from a prior page's `next_cursor`. */
  cursor?: string;
}

/** One rate-limit provider slot (`GET /stats.rate_limits.{github|anthropic|openai}`). */
export interface RateLimitSlot {
  remaining: number | null;
  limit: number | null;
  reset: number | null;
  /** Consumed fraction 0..1, or `null` when no header has been observed → "—". */
  used_pct: number | null;
  secondary_limited: boolean;
  secondary_retry_after: number;
}

/** The `GET /stats` rate-limit health block (FR-06-2). */
export interface RateLimits {
  github: RateLimitSlot;
  /** `null`-usage until the model-call header tap is wired → rendered "—". */
  anthropic: RateLimitSlot;
  openai: RateLimitSlot;
}

/** One daily spend point (`GET /stats.spend_series` — Codex-excluded, INV-8). */
export interface SpendPoint {
  /** The day (`YYYY-MM-DD`). */
  date: string;
  /** Codex-excluded segment-sum spend for that day. */
  usd: number;
}

/** The `GET /stats` aggregate body (FR-06-1 / FR-06-1a / FR-06-2). */
export interface StatsResponse {
  total_runs: number;
  /** `completed/(completed+failed)` as a 0..1 fraction. */
  success_rate: number;
  /** Codex-EXCLUDED total spend (INV-8). */
  total_spend_usd: number;
  /** All-agent token total (Codex tokens counted — FR-06-1a). */
  tokens: number;
  /** All-agent agent-hours (Σ duration_s / 3600). */
  agent_hours: number;
  /** Daily Codex-excluded spend series, oldest-first. */
  spend_series: SpendPoint[];
  rate_limits: RateLimits;
}

/** One retry-queue row (`GET /retry-queue` — PRD §6.1 `RetryEntry`). */
export interface RetryEntry {
  /** The run/issue's platform id (the `POST /runs/{id}/retry` target). */
  id: string;
  /** The issue number. */
  issue: number;
  /** The attempt count so far (rendered `attempt {attempt}/3`). */
  attempt: number;
  /** Human "due in" string (e.g. `"2m 10s"`). */
  dueIn: string;
  /** The last failure message. */
  lastError: string;
}

/** The cursor-paginated `GET /retry-queue` envelope (§8.9). */
export interface RetryQueuePage {
  items: RetryEntry[];
  next_cursor: string | null;
}

/** The `POST /runs/{id}/retry` 202 body (FR-06-3 — endpoint ships in 3.4). */
export interface RetryRunResponse {
  run_id: string;
  status: string;
}

/** Append a filter param only when it is a real, non-`all` value (a blank/`all`
 *  filter is a no-op so the backend returns the full set). */
function appendFilter(params: URLSearchParams, key: string, value: string | undefined): void {
  if (value && value !== "all") params.set(key, value);
}

/**
 * Fetch a filtered, cursor-paginated `GET /runs` history page (FR-06-4 / §8.9).
 *
 * Each filter (`workflow`/`agent`/`status`/`repo`) narrows the result set; the
 * cursor pages forward via the prior page's `next_cursor`. The returned costs are
 * the backend's segment-sum projection (Codex → `null` → "—", INV-7/INV-8).
 */
export function listRuns(query: RunsQuery = {}): Promise<RunsPage> {
  const params = new URLSearchParams();
  appendFilter(params, "workflow", query.workflow);
  appendFilter(params, "agent", query.agent);
  appendFilter(params, "status", query.status);
  if (query.repo) params.set("repo", query.repo);
  if (query.limit != null) params.set("limit", String(query.limit));
  if (query.cursor) params.set("cursor", query.cursor);
  const qs = params.toString();
  return apiGet<RunsPage>(`/runs${qs ? `?${qs}` : ""}`);
}

/** Fetch the §8.9 aggregate stats (cards + spend chart + rate-limit row). */
export function getStats(): Promise<StatsResponse> {
  return apiGet<StatsResponse>("/stats");
}

/** Fetch the retry-queue rows (`GET /retry-queue`; empty until 3.4 populates it). */
export function getRetryQueue(): Promise<RetryQueuePage> {
  return apiGet<RetryQueuePage>("/retry-queue");
}

/**
 * Enqueue a "Retry now" for a failed/`interrupted` run (`POST /runs/{id}/retry`,
 * FR-06-3). The endpoint ships in slice 3.4 (idempotent — a second call while a
 * retry is pending is a no-op, never a duplicate dispatch); the call is wired
 * here so the retry-queue card + the failed-run detail action are functional the
 * moment 3.4 lands. A state-changing POST → CSRF-safe {@link apiPost} (INV-1); no
 * token is ever placed in the URL (INV-2).
 */
export function retryRun(runId: string): Promise<RetryRunResponse> {
  return apiPost<RetryRunResponse>(`/runs/${encodeURIComponent(runId)}/retry`);
}
