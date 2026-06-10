/**
 * Live-run `⋯` run-actions menu (FR-04-1, §5.5; ship-gap G7). Ported from the
 * `Menu` in `run.jsx` and hardened into an **accessible** dropdown.
 *
 * Renders, next to the header Stop control, the state-dependent run actions:
 *
 *   - **Run a command in the container** (live runs) — a one-shot `execute_in_container`
 *     (`POST /runs/{id}/exec`), NOT an interactive PTY (the engine doesn't expose one).
 *     Opens an inline panel: a command input + Run button + the server-**redacted**
 *     stdout (INV-4 — secrets are scrubbed *before* the response leaves the backend).
 *   - **Keep alive on finish** (live runs) — a LAUNCH-time option (`POST /runs` body
 *     `keep_alive`); there is **no** post-launch toggle endpoint, so this surfaces
 *     **honestly** as a disabled, informational item reflecting how the run was
 *     launched (kept-alive vs not), never a non-functional control.
 *   - **Retry run** (failed / interrupted / timed-out) — `POST /runs/{id}/retry`.
 *   - **View PR #{pr}** (completed, when a PR is linked) — an external link to
 *     `https://github.com/{repo}/pull/{pr_num}`.
 *
 * **Accessibility (NFR-A11Y-1 / INV-14).** A `role="menu"` popup with arrow-key
 * roving focus, Home/End, Escape-to-close (focus returns to the trigger), and
 * outside-click dismissal; every item is an icon **+ text label** (state never by
 * color alone). No hex literals — all color is from `tokens.css` (INV-14).
 *
 * **INV-1/INV-2.** Exec/Retry are state-changing POSTs via the CSRF-safe `apiPost`
 * client (passed in as `onExec`/`onRetry`); a token is never placed in any URL.
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { DotsIcon, ExtIcon, PrIcon, RetryIcon, TerminalIcon } from "./icons";
import type { ExecRunResponse, RetryRunResponse } from "../api/runs";

export interface RunActionsMenuProps {
  /** The platform UUID of the run (the exec/retry target). */
  runId: string;
  /** The engine run status (drives which items show). */
  status: string;
  /** Whether the run is live (running/pending/stopping/paused) — exec + keep-alive. */
  live: boolean;
  /** Whether the run was launched keep-alive (the honest informational indicator). */
  keepAlive?: boolean;
  /** The linked PR number (completed runs), or null. */
  prNum?: number | null;
  /** The fully-built GitHub PR URL (`https://github.com/{repo}/pull/{n}`), or null. */
  prUrl?: string | null;
  /** One-shot container exec → redacted stdout (`POST /runs/{id}/exec`). */
  onExec: (runId: string, command: string) => Promise<ExecRunResponse>;
  /** Enqueue a retry for a failed/interrupted run (`POST /runs/{id}/retry`). */
  onRetry: (runId: string) => Promise<RetryRunResponse>;
}

/** Statuses for which "Retry run" is offered (FR-04-1 — failed family). */
const RETRYABLE = new Set(["failed", "timed_out", "interrupted"]);

export default function RunActionsMenu({
  runId,
  status,
  live,
  keepAlive,
  prNum,
  prUrl,
  onExec,
  onRetry,
}: RunActionsMenuProps) {
  const [open, setOpen] = useState(false);
  const [execOpen, setExecOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  const s = status.toLowerCase();
  const retryable = RETRYABLE.has(s);
  const completed = s === "completed";
  const showPr = completed && prNum != null && !!prUrl;

  const closeMenu = useCallback((restoreFocus = true) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  // Outside-click dismissal (does not steal focus — matches the prototype Menu).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  // Focus the first menu item when the menu opens (keyboard entry).
  useEffect(() => {
    if (!open) return;
    const first = menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]');
    first?.focus();
  }, [open]);

  // Roving arrow-key focus within the open menu (WAI-ARIA menu pattern).
  const onMenuKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeMenu();
        return;
      }
      const items = Array.from(
        menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
      );
      if (items.length === 0) return;
      const current = items.indexOf(document.activeElement as HTMLElement);
      let next = current;
      if (e.key === "ArrowDown") next = current + 1;
      else if (e.key === "ArrowUp") next = current - 1;
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = items.length - 1;
      else return;
      e.preventDefault();
      const clamped = Math.max(0, Math.min(items.length - 1, next));
      items[clamped]?.focus();
    },
    [closeMenu],
  );

  const onTriggerKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setOpen(true);
    }
  }, []);

  const handleExecItem = useCallback(() => {
    closeMenu(false);
    setExecOpen(true);
  }, [closeMenu]);

  const handleRetryItem = useCallback(async () => {
    closeMenu(false);
    setRetrying(true);
    try {
      await onRetry(runId);
    } catch {
      // Best-effort; the run detail re-fetch reflects reality. No destructive UI.
    } finally {
      setRetrying(false);
    }
  }, [closeMenu, onRetry, runId]);

  const hasItems = live || retryable || showPr;
  if (!hasItems) return null;

  return (
    <div className="run-actions" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="btn btn-soft btn-icon run-actions-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label="Run actions"
        onClick={() => setOpen((o) => !o)}
        onKeyDown={onTriggerKeyDown}
      >
        <DotsIcon size={17} />
      </button>

      {open && (
        <div
          ref={menuRef}
          id={menuId}
          role="menu"
          aria-label="Run actions"
          className="card fade-in run-actions-menu"
          onKeyDown={onMenuKeyDown}
        >
          {live && (
            <button
              type="button"
              role="menuitem"
              className="run-actions-item"
              onClick={handleExecItem}
            >
              <TerminalIcon size={15} />
              Run a command in the container
            </button>
          )}
          {live && (
            <div
              role="menuitem"
              aria-disabled="true"
              className="run-actions-item is-info"
              tabIndex={-1}
            >
              <TerminalIcon size={15} />
              {keepAlive
                ? "Keep alive on finish · on (set at launch)"
                : "Keep alive on finish · set at launch"}
            </div>
          )}
          {retryable && (
            <button
              type="button"
              role="menuitem"
              className="run-actions-item"
              onClick={() => void handleRetryItem()}
              disabled={retrying}
            >
              <RetryIcon size={15} />
              {retrying ? "Retrying…" : "Retry run"}
            </button>
          )}
          {showPr && (
            <a
              role="menuitem"
              className="run-actions-item"
              href={prUrl ?? undefined}
              target="_blank"
              rel="noreferrer"
              onClick={() => closeMenu(false)}
            >
              <PrIcon size={15} />
              View PR #{prNum}
              <ExtIcon size={13} className="run-actions-ext" />
            </a>
          )}
        </div>
      )}

      {execOpen && (
        <ExecPanel runId={runId} onExec={onExec} onClose={() => setExecOpen(false)} />
      )}
    </div>
  );
}

interface ExecPanelProps {
  runId: string;
  onExec: (runId: string, command: string) => Promise<ExecRunResponse>;
  onClose: () => void;
}

type ExecPhase = "idle" | "running" | "done" | "error";

/**
 * The one-shot exec panel: a command input, a Run button, and the server-redacted
 * stdout. Modal-ish inline panel (the prototype renders this as a popover); Escape
 * closes it, and the input is auto-focused on open for keyboard operability.
 */
function ExecPanel({ runId, onExec, onClose }: ExecPanelProps) {
  const [command, setCommand] = useState("");
  const [output, setOutput] = useState("");
  const [phase, setPhase] = useState<ExecPhase>("idle");
  const inputRef = useRef<HTMLInputElement>(null);
  const headingId = useId();

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const run = useCallback(async () => {
    const cmd = command.trim();
    if (!cmd || phase === "running") return;
    setPhase("running");
    try {
      const res = await onExec(runId, cmd);
      setOutput(res.output);
      setPhase("done");
    } catch {
      setOutput("");
      setPhase("error");
    }
  }, [command, onExec, phase, runId]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    },
    [onClose],
  );

  return (
    <div
      className="card fade-in run-exec-panel"
      role="dialog"
      aria-modal="false"
      aria-labelledby={headingId}
      onKeyDown={onKeyDown}
    >
      <div className="run-exec-head">
        <h3 id={headingId} className="run-exec-title">
          <TerminalIcon size={14} /> Run a command in the container
        </h3>
        <button
          type="button"
          className="btn btn-soft btn-sm"
          onClick={onClose}
          aria-label="Close"
        >
          Close
        </button>
      </div>
      <p className="run-exec-note cap">
        One-shot exec (a single command) — not an interactive shell. Output is redacted.
      </p>
      <form
        className="run-exec-form"
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
      >
        <input
          ref={inputRef}
          className="input mono run-exec-input"
          type="text"
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          placeholder="e.g. ls -la /workspace"
          aria-label="Command to run in the container"
        />
        <button
          type="submit"
          className="btn btn-primary run-exec-run"
          disabled={phase === "running" || command.trim().length === 0}
        >
          {phase === "running" ? "Running…" : "Run"}
        </button>
      </form>
      {phase === "error" && (
        <p className="run-exec-error" role="alert">
          The command could not run (the container may not be running).
        </p>
      )}
      {phase === "done" && (
        <pre className="mono run-exec-output" aria-label="Command output">
          {output.length > 0 ? output : "(no output)"}
        </pre>
      )}
    </div>
  );
}
