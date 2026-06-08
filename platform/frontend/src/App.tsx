import { Routes, Route, Navigate } from "react-router-dom";

/**
 * Phase 0 scaffold App.
 *
 * Router stub only — the real Screens 01-07 (Connect, Board, Issue, Run,
 * History, Workflows, Settings) land in Phase 1+. This component exists so the
 * Vite app boots, the router resolves, and `tsc --noEmit` is green. It renders
 * no design-token-driven chrome yet (DESIGN_FIDELITY is n/a in Phase 0).
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ScaffoldHome />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function ScaffoldHome() {
  return (
    <main>
      <h1>DKMV Platform</h1>
      <p>Scaffold is running. Screens land in Phase 1.</p>
    </main>
  );
}
