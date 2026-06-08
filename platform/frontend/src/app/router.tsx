/**
 * App router (FR-NAV-3) — finalizes the Phase-0 scaffold router.
 *
 * Phase 1 ships Screen 01 (Connect) at `/connect`. The board (Screen 02) is
 * slice 1.5; until it lands the `/board` route renders a minimal placeholder so
 * the connect → board handoff is exercised end-to-end without depending on 1.5.
 * The theme is applied at module load (dark/indigo default, persisted) so the
 * first paint is correctly skinned (INV-14).
 */

import { useCallback } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import Connect from "../screens/Connect";
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
 * Placeholder board (Screen 02 is slice 1.5). Renders only enough to confirm the
 * connect handoff resolved; 1.5 replaces this route with the real Board.
 */
function BoardPlaceholder() {
  return (
    <main className="board-placeholder">
      <h1>Board</h1>
      <p className="cap">The board (Screen 02) lands in slice 1.5.</p>
    </main>
  );
}

export default function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/connect" replace />} />
      <Route path="/connect" element={<ConnectRoute />} />
      <Route path="/board" element={<BoardPlaceholder />} />
      <Route path="*" element={<Navigate to="/connect" replace />} />
    </Routes>
  );
}
