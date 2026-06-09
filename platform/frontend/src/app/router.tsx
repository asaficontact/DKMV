/**
 * App router (FR-NAV-3) — finalizes the Phase-0 scaffold router.
 *
 * Phase 1 ships Screen 01 (Connect) at `/connect` and Screen 02 (Board, slice
 * 1.5) at `/board`. The Connect → Board handoff carries the chosen repo slug in
 * the `?repo=` query; `/board` reads it and renders the real Board (with the
 * global chrome). The theme is applied at module load (dark/indigo default,
 * persisted) so the first paint is correctly skinned (INV-14).
 */

import { useCallback } from "react";
import {
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import Board from "../screens/Board";
import Connect from "../screens/Connect";
import IssueDetail from "../screens/IssueDetail";
import LiveRun from "../screens/LiveRun";
import { initTheme } from "./theme";

// Apply the persisted (or default dark/indigo) theme before the first render.
initTheme();

function ConnectRoute() {
  const navigate = useNavigate();
  const onDone = useCallback(
    (slug: string) => {
      navigate(`/board?repo=${encodeURIComponent(slug)}`);
    },
    [navigate],
  );
  return <Connect onDone={onDone} />;
}

/**
 * Board route (Screen 02). Reads the connected repo slug from `?repo=`; if it is
 * missing (a direct `/board` visit before connecting), send the operator back to
 * Connect to pick a project first.
 */
function BoardRoute() {
  const [params] = useSearchParams();
  const repo = params.get("repo");
  if (!repo) return <Navigate to="/connect" replace />;
  return <Board repoSlug={repo} />;
}

/**
 * Issue-detail / launch route (Screen 03, slice 2.2). The repo slug is carried in
 * the path (`/issues/:owner/:name/:num`); a successful launch navigates to the
 * live run by its platform UUID (`/runs/:id` — the live view is slice 2.4, so for
 * now the run id round-trips through the URL). "Queue for later" / back returns to
 * the board for the same repo.
 */
function IssueDetailRoute() {
  const navigate = useNavigate();
  const { owner, name, num } = useParams();
  const repoSlug = owner && name ? `${owner}/${name}` : null;
  const issueNum = num ? Number.parseInt(num, 10) : NaN;
  if (!repoSlug || Number.isNaN(issueNum)) {
    return <Navigate to="/connect" replace />;
  }
  return (
    <IssueDetail
      repoSlug={repoSlug}
      issueNum={issueNum}
      onOpenRun={(runId) =>
        navigate(`/runs/${encodeURIComponent(runId)}?repo=${encodeURIComponent(repoSlug)}`)
      }
      onBack={() => navigate(`/board?repo=${encodeURIComponent(repoSlug)}`)}
    />
  );
}

/**
 * Live-run route (Screen D, slice 2.4). The platform UUID is carried in the path
 * (`/runs/:id`); the connected repo slug rides `?repo=` (for the chrome + PR
 * links) — falling back to the run's own `repo` once the detail loads if absent
 * (a direct `/runs/:id` visit). This route is the recorded 2.2 gap: a launch
 * navigates here instead of falling through to `/connect`.
 */
function LiveRunRoute() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { id } = useParams();
  const repo = params.get("repo") ?? "";
  if (!id) return <Navigate to="/connect" replace />;
  return (
    <LiveRun
      runId={id}
      repoSlug={repo}
      onGoBoard={() => navigate(`/board?repo=${encodeURIComponent(repo)}`)}
    />
  );
}

export default function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/connect" replace />} />
      <Route path="/connect" element={<ConnectRoute />} />
      <Route path="/board" element={<BoardRoute />} />
      <Route path="/issues/:owner/:name/:num" element={<IssueDetailRoute />} />
      <Route path="/runs/:id" element={<LiveRunRoute />} />
      <Route path="*" element={<Navigate to="/connect" replace />} />
    </Routes>
  );
}
