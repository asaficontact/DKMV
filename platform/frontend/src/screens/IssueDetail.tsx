/**
 * Screen 03 — Issue detail & launch (FR-03, §5.4, AC-6/AC-7). The two-pane
 * launch screen (`minmax(0,1fr) 408px`): the **left** pane renders the issue
 * (number + state badge, branch caption + "Open on GitHub" when a run exists, H1
 * title, author row + GitHub label pills, the existing-run alert, the markdown
 * body, and the comments thread); the **right** pane is the {@link RunPanel}
 * ("Run this issue").
 *
 * Data: `GET /issues/{owner}/{name}/{num}` (slice 2.1) for the issue + active run,
 * and `GET /workflows` (slice 4.1) for the picker. Launch posts `POST /runs` and
 * navigates to the live run (FR-03-3). The global chrome (Sidebar + TopBar) wraps
 * the screen, matching the Board.
 *
 * All color is token-driven (INV-14); the GitHub label hex from the API is passed
 * as a CSS custom property (`--lc`) on the pill, not inlined as a style literal.
 */
import { useCallback, useEffect, useState } from "react";

import "./board.css";
import "./issue-detail.css";
import {
  type IssueDetailResponse,
  type WorkflowSummary,
  getIssueDetail,
  listWorkflows,
} from "../api/runs";
import { Avatar } from "../components/chips";
import ExistingRunAlert from "../components/ExistingRunAlert";
import { BranchIcon, ExtIcon, GitHubIcon } from "../components/icons";
import Markdown from "../components/Markdown";
import RunPanel from "../components/RunPanel";
import StateBadge from "../components/StateBadge";
import Sidebar from "../chrome/Sidebar";
import TopBar from "../chrome/TopBar";

type LoadPhase = "loading" | "ready" | "error";

export interface IssueDetailProps {
  /** The connected repo slug ("owner/name"). */
  repoSlug: string;
  /** The GitHub issue number. */
  issueNum: number;
  /** Navigate to the live run (routed by platform UUID — the live view is 2.4). */
  onOpenRun: (runId: string) => void;
  /** Back to the board. */
  onBack?: () => void;
}

/** Map the GitHub issue state + active-run status to a board-style badge state. */
function badgeState(issue: IssueDetailResponse): string {
  const status = issue.active_run?.status?.toLowerCase();
  if (status === "paused") return "needs_you";
  if (status === "running" || status === "pending" || status === "stopping") {
    return "in_progress";
  }
  // No active run → reflect the GitHub open/closed state.
  return issue.state === "closed" ? "done" : "backlog";
}

export default function IssueDetail({
  repoSlug,
  issueNum,
  onOpenRun,
  onBack,
}: IssueDetailProps) {
  const [issue, setIssue] = useState<IssueDetailResponse | null>(null);
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [phase, setPhase] = useState<LoadPhase>("loading");

  const load = useCallback(async () => {
    setPhase("loading");
    try {
      const [detail, flows] = await Promise.all([
        getIssueDetail(repoSlug, issueNum),
        listWorkflows(),
      ]);
      setIssue(detail);
      setWorkflows(flows);
      setPhase("ready");
    } catch {
      setPhase("error");
    }
  }, [repoSlug, issueNum]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="app-shell">
      <Sidebar repoSlug={repoSlug} aggregate={null} />
      <div className="app-main">
        <TopBar
          title={`${repoSlug} · #${issueNum}`}
          lastSyncedSeconds={null}
          onRefresh={() => void load()}
        />
        {phase === "loading" && <LoadingState />}
        {phase === "error" && <ErrorState onRetry={() => void load()} />}
        {phase === "ready" && issue && (
          <div className="issue-detail">
            <IssueColumn issue={issue} repoSlug={repoSlug} onOpenRun={onOpenRun} />
            <RunPanel
              issueNum={issue.num}
              issueTitle={issue.title}
              repo={repoSlug}
              workflows={workflows}
              onLaunched={onOpenRun}
              onQueueForLater={onBack}
            />
          </div>
        )}
      </div>
    </div>
  );
}

/** The left pane — the issue itself (§5.4 FR-03-1). */
function IssueColumn({
  issue,
  repoSlug,
  onOpenRun,
}: {
  issue: IssueDetailResponse;
  repoSlug: string;
  onOpenRun: (runId: string) => void;
}) {
  const hasRun = issue.active_run != null;
  const githubUrl = issue.url ?? `https://github.com/${repoSlug}/issues/${issue.num}`;
  const author = issue.author?.login ?? "unknown";
  const authorInitials = author.slice(0, 2).toUpperCase();

  return (
    <div className="issue-col">
      <div className="issue-col-inner">
        <div className="issue-head-row">
          <span className="mono issue-num">#{issue.num}</span>
          <StateBadge status={badgeState(issue)} />
          {hasRun && (
            <span className="cap issue-branch-cap">
              <BranchIcon size={12} />
              on <span className="mono">{issue.active_run?.run_id ?? "run"}</span>
            </span>
          )}
          <a
            className="btn btn-ghost btn-sm issue-gh-link"
            href={githubUrl}
            target="_blank"
            rel="noreferrer"
          >
            <GitHubIcon size={14} />
            Open on GitHub
            <ExtIcon size={13} />
          </a>
        </div>

        <h1 className="issue-h1">{issue.title}</h1>

        <div className="issue-author-row">
          <Avatar initials={authorInitials} size={26} />
          <span className="issue-author-text">
            <strong>{author}</strong> <span className="issue-author-muted">opened this issue</span>
          </span>
          {issue.labels.length > 0 && (
            <div className="issue-labels">
              {issue.labels.map((label) => (
                <IssueLabelPill key={label.name} name={label.name} color={label.color} />
              ))}
            </div>
          )}
        </div>

        {issue.active_run && (
          <ExistingRunAlert
            activeRun={issue.active_run}
            onOpen={(runId) => {
              if (runId) onOpenRun(runId);
            }}
          />
        )}

        <div className="card issue-body-card">
          <Markdown text={issue.body} />
        </div>

        {issue.comments.length > 0 && (
          <div className="issue-comments">
            <div className="cap issue-comments-head">
              {issue.comments.length} comment{issue.comments.length > 1 ? "s" : ""}
            </div>
            {issue.comments.map((comment, i) => {
              const cAuthor = comment.author?.login ?? "unknown";
              return (
                <div key={comment.id ?? i} className="issue-comment">
                  <Avatar initials={cAuthor.slice(0, 2).toUpperCase()} size={30} />
                  <div className="card issue-comment-card">
                    <div className="issue-comment-head">
                      <span className="issue-comment-author">{cAuthor}</span>
                      {comment.created_at && (
                        <span className="cap">{comment.created_at}</span>
                      )}
                    </div>
                    <div className="issue-comment-body">
                      <Markdown text={comment.body} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * A GitHub label pill. The label color is GitHub's own 6-hex (a data value, not a
 * design token), passed through the `--lc` CSS custom property the `.gh-label`
 * primitive already reads — so no hex literal is written into TSX (INV-14).
 */
function IssueLabelPill({ name, color }: { name: string; color: string | null }) {
  const lc = color ? `#${color}` : undefined;
  // `--lc` is a runtime data value (GitHub's label hex), not a design-token hue.
  const style = lc ? ({ ["--lc"]: lc } as React.CSSProperties) : undefined;
  return (
    <span className="gh-label" style={style}>
      {name}
    </span>
  );
}

function LoadingState() {
  return (
    <div className="issue-state">
      <div className="run-bar issue-loading-bar" />
      <p className="cap">Loading issue…</p>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="issue-state" role="alert">
      <h2 className="issue-state-title">Couldn&rsquo;t load the issue</h2>
      <p className="cap">We hit a snag reaching the control plane.</p>
      <button type="button" className="btn btn-soft" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}
