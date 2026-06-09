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
 * **Decision card slot (slice boundary).** When the run is `paused` this renders a
 * `<section data-slot="decision-card">` placeholder with a minimal "Decision
 * required" message. It does **NOT** import `PauseCard` — slice 2.5 builds
 * `PauseCard` standalone; mounting it into this slot is a documented POST-MERGE
 * integration step. The slot is the seam; the card lands later.
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
import { type RunDetailResponse, getRun, stopRun } from "../api/runs";
import { type RuntimeEvent, subscribeRunEvents } from "../api/sse";
import AppLayout from "../chrome/AppLayout";
import EventFeed from "../components/EventFeed";
import { BranchIcon, StopIcon } from "../components/icons";
import MetersRow from "../components/MetersRow";
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

            {/* DECISION-CARD SLOT (slice boundary). 2.5 builds PauseCard and mounts
                it here as a POST-MERGE step. This is a marked placeholder ONLY — it
                does NOT import PauseCard. */}
            {run.status === "paused" && (
              <section className="decision-card-slot" data-slot="decision-card">
                <span className="badge decision-slot-badge">PAUSED</span>
                <span className="decision-slot-text">
                  Decision required — this run needs your decision to continue.
                </span>
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

/** The run header: status badge + id + issue title + workflow/agent/branch + Stop. */
function RunHeader({
  run,
  stopping,
  onStop,
}: {
  run: RunDetailResponse;
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
