/**
 * Read-only finished-run view (F10 / §5.7, FR-06-4). The Runs-history row click
 * lands here: a **static** render of a finished run from `GET /runs/{id}` (the full
 * §8.9 detail) inside the global chrome ({@link AppLayout}).
 *
 * **Read-only (no live SSE).** A finished run is static — there is **no** event
 * stream, no live meter ticking, and **no Stop control** (the live view, slice 2.4,
 * owns those). It reuses the 2.4 building blocks ({@link MetersRow},
 * {@link StageTracker}, {@link RunRail}) but in their non-live form: `live={false}`,
 * the meters show the final segment-sum cost (INV-7), the stages show their final
 * state, and the rail shows config/sandbox/artifacts/PR.
 *
 * **Failed-run "Retry now" (FR-06-3).** The ONLY action here is a failed /
 * `interrupted` run's **Retry now**, which posts `POST /runs/{id}/retry` via
 * {@link retryRun} (idempotent — the endpoint ships in slice 3.4; INV-15). After a
 * successful retry we re-fetch the detail (the status moves out of `failed`).
 *
 * **INV-8.** A Codex run's cost is "—" (excluded from spend), driven by
 * `cost_excluded`. **INV-14.** No hex literals — all color is token-driven; status
 * is the {@link StateBadge} (icon + label), never color alone.
 */
import { useCallback, useEffect, useState } from "react";

import "./run-detail.css";
import { retryRun } from "../api/history";
import { type RunDetailResponse, getRun } from "../api/runs";
import AppLayout from "../chrome/AppLayout";
import { BranchIcon, RetryIcon } from "../components/icons";
import MetersRow from "../components/MetersRow";
import RunRail from "../components/RunRail";
import StageTracker from "../components/StageTracker";
import StateBadge from "../components/StateBadge";

type LoadPhase = "loading" | "ready" | "error";

/** A run is "retryable" when it ended in a failure-class terminal state (FR-06-3). */
function isRetryable(status: string): boolean {
  const s = status.toLowerCase();
  return s === "failed" || s === "timed_out" || s === "interrupted";
}

/** Overall progress = done stages / total stages (0..1). Completed → 1. */
function deriveProgress(run: RunDetailResponse): number {
  if (run.status === "completed") return 1;
  if (run.stages.length === 0) return 0;
  const done = run.stages.filter((s) => {
    const st = s.status.toLowerCase();
    return st === "done" || st === "completed";
  }).length;
  return done / run.stages.length;
}

export interface RunDetailProps {
  /** The platform UUID of the run (the detail's address). */
  runId: string;
  /** The connected repo slug (chrome + PR link); falls back to the run's `repo`. */
  repoSlug?: string;
  /** Back to the Runs history list. */
  onBack?: () => void;
}

export default function RunDetail({ runId, repoSlug = "", onBack }: RunDetailProps) {
  const [run, setRun] = useState<RunDetailResponse | null>(null);
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [retrying, setRetrying] = useState(false);

  const load = useCallback(async () => {
    try {
      const detail = await getRun(runId);
      setRun(detail);
      setPhase("ready");
    } catch {
      setPhase((prev) => (prev === "loading" ? "error" : prev));
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const onRetry = useCallback(async () => {
    setRetrying(true);
    try {
      await retryRun(runId);
      await load();
    } catch {
      // The next load reflects reality; never throw out of the click handler.
    } finally {
      setRetrying(false);
    }
  }, [runId, load]);

  // The chrome + PR link need the repo slug; prefer the route's `?repo=` but fall
  // back to the run's own `repo` for a direct visit.
  const effectiveRepo = repoSlug || run?.repo || "";

  // Final elapsed = duration_s when known (this view never ticks a clock — static).
  const elapsed = run?.duration_s ?? 0;

  return (
    <AppLayout
      repoSlug={effectiveRepo}
      title={`${effectiveRepo || "Run"} · Run`}
      activeNav="runs"
      onRefresh={() => void load()}
    >
      {phase === "loading" && <LoadingState />}
      {phase === "error" && <ErrorState onRetry={() => void load()} />}
      {phase === "ready" && run && (
        <div className="run-detail">
          <div className="run-detail-main">
            <RunHeader run={run} retrying={retrying} onRetry={() => void onRetry()} onBack={onBack} />
            <MetersRow
              live={false}
              elapsedSeconds={elapsed}
              costUsd={run.cost_usd}
              costExcluded={run.cost_excluded}
              tokensIn={run.tokens_in}
              tokensOut={run.tokens_out}
              turns={run.turns}
              progress={deriveProgress(run)}
              status={run.status}
            />
            <StageTracker stages={run.stages} />

            {run.error && (
              <section className="run-detail-error" role="note">
                <span className="cap run-detail-error-label">Error</span>
                <p className="run-detail-error-text">{run.error}</p>
              </section>
            )}
          </div>
          <RunRail run={run} prUrl={prGitHubUrl(effectiveRepo, run)} />
        </div>
      )}
    </AppLayout>
  );
}

/**
 * The read-only run header: status badge + id + issue title + workflow/agent/branch.
 * The ONLY control is a **Retry now** on a failed / `interrupted` run (FR-06-3) —
 * there is no Stop here (a finished run is static; INV-15 / no live controls).
 */
function RunHeader({
  run,
  retrying,
  onRetry,
  onBack,
}: {
  run: RunDetailResponse;
  retrying: boolean;
  onRetry: () => void;
  onBack?: () => void;
}) {
  return (
    <header className="run-detail-head">
      <div className="run-detail-head-main">
        <div className="run-detail-head-top">
          <StateBadge status={run.status} />
          <span className="mono run-detail-id">{run.id}</span>
        </div>
        <h1 className="run-detail-title">
          {run.issue && <span className="mono run-detail-issue-num">#{run.issue.num} </span>}
          {run.issue?.title ?? run.workflow_id ?? "Run"}
        </h1>
        <div className="run-detail-meta">
          {run.workflow_id && <span className="run-detail-meta-item">{run.workflow_id}</span>}
          {run.agent && <span className="run-detail-meta-item">{run.agent}</span>}
          {run.model && <span className="mono run-detail-meta-item">{run.model}</span>}
          <span className="run-detail-meta-item">
            <BranchIcon size={12} /> <span className="mono">{run.branch}</span>
          </span>
        </div>
      </div>
      <div className="run-detail-head-actions">
        {onBack && (
          <button type="button" className="btn btn-ghost" onClick={onBack}>
            Back
          </button>
        )}
        {isRetryable(run.status) && (
          <button
            type="button"
            className="btn btn-soft run-detail-retry"
            onClick={onRetry}
            disabled={retrying}
          >
            <RetryIcon size={15} /> {retrying ? "Retrying…" : "Retry now"}
          </button>
        )}
      </div>
    </header>
  );
}

/** Build the GitHub PR URL from the repo slug + the linked PR number. */
function prGitHubUrl(repoSlug: string, run: RunDetailResponse): string | undefined {
  if (!run.pr) return undefined;
  return `https://github.com/${repoSlug}/pull/${run.pr.num}`;
}

function LoadingState() {
  return (
    <div className="run-detail-state">
      <div className="run-bar run-detail-loading-bar" />
      <p className="cap">Loading run…</p>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="run-detail-state" role="alert">
      <h2 className="run-detail-state-title">Couldn&rsquo;t load the run</h2>
      <p className="cap">We hit a snag reaching the control plane.</p>
      <button type="button" className="btn btn-soft" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}
