/**
 * Screen D — Live run / session view (FR-04, §5.5, §8.3). Ported from `run.jsx`.
 *
 * Owns the live-run layout inside the global chrome ({@link AppLayout}): the run
 * header (status badge + id + issue title + workflow/agent/branch), the
 * {@link MetersRow} (segment-sum meters — INV-7), the {@link StageTracker}, a
 * clearly-marked **decision-card slot** rendered when the run is paused, the
 * {@link EventFeed} (Friendly/Raw + search, live auto-scroll), the
 * {@link RunRail} (config/sandbox/artifacts/PR), and a **Stop** (danger) control.
 *
 * **Decision card slot (wired — slice 2.6).** When the run is `paused` this renders
 * the {@link PauseCard} inside `<section data-slot="decision-card">`, sourced from
 * the `GET /runs/{id}` `decision` rehydration block (slice 2.3). Approve/Ship/Abort
 * POST to `/runs/{id}/answer` via `answerRun`; on a successful answer the SSE
 * `decision` event + status change flow in and the slot clears. (2.4 owned the slot,
 * 2.5 built `PauseCard` standalone; this is the documented post-merge wiring.)
 *
 * **Data.** `GET /runs/{id}` (slice 2.1 baseline — meters, stages, config, the
 * `decision` rehydration block) + the live SSE stream ({@link subscribeRunEvents};
 * cookie auth, NO token in URL — INV-2). Meters/stages refresh off `GET /runs/{id}`
 * on each lifecycle event so the segment-sum (computed server-side) stays
 * authoritative; the event feed appends live frames.
 *
 * **INV-14.** No hex literals — every color is a token; status is conveyed by the
 * {@link StateBadge} (icon + label), never color alone.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import "./live-run.css";
import {
  type RunDetailResponse,
  answerRun,
  execInContainer,
  getRun,
  retryRun,
  stopRun,
} from "../api/runs";
import { type RuntimeEvent, subscribeRunEvents } from "../api/sse";
import AppLayout from "../chrome/AppLayout";
import EventFeed from "../components/EventFeed";
import { BranchIcon, StopIcon } from "../components/icons";
import MetersRow from "../components/MetersRow";
import PauseCard from "../components/PauseCard";
import RunActionsMenu from "../components/RunActionsMenu";
import RunRail from "../components/RunRail";
import StageTracker from "../components/StageTracker";
import StateBadge from "../components/StateBadge";

type LoadPhase = "loading" | "ready" | "error";

/** Lifecycle event types that should trigger a `GET /runs/{id}` re-fetch so the
 * server-computed segment-sum meters + stages stay authoritative. */
const LIFECYCLE_TYPES = new Set([
  "task_started",
  "task_completed",
  "task_failed",
  "pause_requested",
  "run_completed",
  "run_failed",
  "decision",
]);

export interface LiveRunProps {
  /** The platform UUID of the run (the live view's address). */
  runId: string;
  /** The connected repo slug (for the chrome + PR links). */
  repoSlug: string;
  /** Back to the board. */
  onGoBoard?: () => void;
}

/** Map the engine run status to the run-header badge state. */
function headerBadge(status: string): { status: string; label: string } {
  const s = status.toLowerCase();
  if (s === "paused") return { status: "paused", label: "Paused · needs you" };
  if (s === "running" || s === "pending" || s === "stopping") {
    return { status: "running", label: s === "stopping" ? "Stopping" : "Running" };
  }
  if (s === "completed") return { status: "completed", label: "Completed" };
  if (s === "failed" || s === "timed_out") return { status: "failed", label: "Failed" };
  return { status: s, label: status };
}

/** Overall progress = done stages / total stages (0..1). */
function deriveProgress(run: RunDetailResponse): number {
  if (run.status === "completed") return 1;
  if (run.stages.length === 0) return 0;
  const done = run.stages.filter((s) => {
    const st = s.status.toLowerCase();
    return st === "done" || st === "completed";
  }).length;
  return done / run.stages.length;
}

/** Whether the run is in a live (ticking) state. */
function isLiveStatus(status: string): boolean {
  const s = status.toLowerCase();
  return s === "running" || s === "pending" || s === "stopping";
}

export default function LiveRun({ runId, repoSlug, onGoBoard }: LiveRunProps) {
  const [run, setRun] = useState<RunDetailResponse | null>(null);
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [raw, setRaw] = useState(false);
  const [query, setQuery] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [stopping, setStopping] = useState(false);

  const load = useCallback(async () => {
    try {
      const detail = await getRun(runId);
      setRun(detail);
      setPhase("ready");
    } catch {
      setPhase((prev) => (prev === "loading" ? "error" : prev));
    }
  }, [runId]);

  // Initial detail load.
  useEffect(() => {
    void load();
  }, [load]);

  // Live SSE stream (cookie auth, NO token in URL — INV-2). Appends each frame to
  // the feed and re-fetches the detail on a lifecycle frame so the server-computed
  // segment-sum meters + stages stay authoritative.
  useEffect(() => {
    const unsubscribe = subscribeRunEvents(runId, {
      onEvent: (event) => {
        setEvents((prev) => [...prev, event]);
        if (LIFECYCLE_TYPES.has(event.event_type)) {
          void load();
        }
      },
    });
    return unsubscribe;
  }, [runId, load]);

  // Elapsed clock: seed from started_at, tick each second while live.
  const live = run ? isLiveStatus(run.status) : false;
  const startedRef = useRef<number | null>(null);
  useEffect(() => {
    if (run?.started_at) {
      const t = new Date(run.started_at).getTime();
      if (!Number.isNaN(t)) startedRef.current = t;
    }
  }, [run?.started_at]);
  useEffect(() => {
    const tick = () => {
      if (startedRef.current != null) {
        setElapsed(Math.max(0, Math.floor((Date.now() - startedRef.current) / 1000)));
      }
    };
    tick();
    if (!live) return;
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [live, run?.id]);

  // The chrome + PR links need the repo slug; prefer the route's `?repo=` but fall
  // back to the run's own `repo` for a direct `/runs/:id` visit (no query).
  const effectiveRepo = repoSlug || run?.repo || "";

  const onStop = useCallback(async () => {
    setStopping(true);
    try {
      await stopRun(runId);
      await load();
    } catch {
      // Surface nothing destructive; the next detail load reflects reality.
    } finally {
      setStopping(false);
    }
  }, [runId, load]);

  return (
    <AppLayout
      repoSlug={effectiveRepo}
      title={`${effectiveRepo || "Run"} · Run`}
      onRefresh={() => void load()}
    >
      {phase === "loading" && <LoadingState />}
      {phase === "error" && <ErrorState onRetry={() => void load()} />}
      {phase === "ready" && run && (
        <div className="live-run">
          <div className="live-run-main">
            <RunHeader
              run={run}
              live={live}
              prUrl={prGitHubUrl(effectiveRepo, run)}
              stopping={stopping}
              onStop={() => void onStop()}
            />
            <MetersRow
              live={live}
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

            {/* DECISION-CARD SLOT (slice boundary). 2.4 owns this slot; 2.5 built
                PauseCard standalone; this is the POST-MERGE wiring (2.6) that mounts
                the card into the slot. The card is sourced from the GET /runs/{id}
                `decision` rehydration block (slice 2.3) so a reconnect mid-pause
                rehydrates from state, not the live push. Approve/Ship/Abort POST to
                /runs/{id}/answer via `answerRun` (INV-1/INV-2 — CSRF-safe, no token
                in URL); on success we re-fetch the detail (the SSE `decision` event +
                status change also flow in) and the slot clears once the run resumes.
                A paused run whose decision hasn't rehydrated yet (the brief window
                before the `decision` block is populated) shows the minimal prompt. */}
            {run.status === "paused" && (
              <section className="decision-card-slot" data-slot="decision-card">
                {run.decision ? (
                  <PauseCard
                    runId={run.id}
                    request={run.decision.request}
                    onSubmit={answerRun}
                    onAnswered={() => void load()}
                  />
                ) : (
                  <>
                    <span className="badge decision-slot-badge">PAUSED</span>
                    <span className="decision-slot-text">
                      Decision required — this run needs your decision to continue.
                    </span>
                  </>
                )}
              </section>
            )}

            <EventFeed
              events={events}
              raw={raw}
              onRawChange={setRaw}
              query={query}
              onQueryChange={setQuery}
              live={live}
            />
          </div>
          <RunRail run={run} prUrl={prGitHubUrl(effectiveRepo, run)} />
        </div>
      )}
      {phase === "ready" && run && run.status === "completed" && onGoBoard && (
        <button type="button" className="btn btn-ghost live-run-board-link" onClick={onGoBoard}>
          Back to board
        </button>
      )}
    </AppLayout>
  );
}

/** The run header: status badge + id + issue title + workflow/agent/branch + the
 * `⋯` run-actions menu (FR-04-1, G7) + Stop. */
function RunHeader({
  run,
  live,
  prUrl,
  stopping,
  onStop,
}: {
  run: RunDetailResponse;
  live: boolean;
  prUrl: string | undefined;
  stopping: boolean;
  onStop: () => void;
}) {
  const badge = headerBadge(run.status);
  const stoppable = run.status === "running" || run.status === "paused" || run.status === "pending";
  return (
    <header className="live-run-head">
      <div className="live-run-head-main">
        <div className="live-run-head-top">
          <StateBadge status={badge.status} label={badge.label} />
          <span className="mono live-run-id">{run.id}</span>
        </div>
        <h1 className="live-run-title">
          {run.issue && <span className="mono live-run-issue-num">#{run.issue.num} </span>}
          {run.issue?.title ?? run.workflow_id ?? "Run"}
        </h1>
        <div className="live-run-meta">
          {run.workflow_id && <span className="live-run-meta-item">{run.workflow_id}</span>}
          {run.agent && <span className="live-run-meta-item">{run.agent}</span>}
          {run.model && <span className="mono live-run-meta-item">{run.model}</span>}
          <span className="live-run-meta-item">
            <BranchIcon size={12} /> <span className="mono">{run.branch}</span>
          </span>
        </div>
      </div>
      <div className="live-run-actions">
        {/* FR-04-1 `⋯` menu (G7): exec / keep-alive (info) / state-dependent
            Retry (failed) + View PR (completed). Exec + Retry are state-changing
            POSTs through the CSRF-safe client (INV-1); no token in any URL (INV-2). */}
        <RunActionsMenu
          runId={run.id}
          status={run.status}
          live={live}
          prNum={run.pr?.num ?? null}
          prUrl={prUrl ?? null}
          onExec={execInContainer}
          onRetry={retryRun}
        />
        {stoppable && (
          <button
            type="button"
            className="btn btn-danger live-run-stop"
            onClick={onStop}
            disabled={stopping}
          >
            <StopIcon size={15} /> {stopping ? "Stopping…" : "Stop"}
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
    <div className="live-run-state">
      <div className="run-bar live-run-loading-bar" />
      <p className="cap">Loading run…</p>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="live-run-state" role="alert">
      <h2 className="live-run-state-title">Couldn&rsquo;t load the run</h2>
      <p className="cap">We hit a snag reaching the control plane.</p>
      <button type="button" className="btn btn-soft" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}
