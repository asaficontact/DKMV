import AppRouter from "./app/router";

/**
 * App root — delegates routing to {@link AppRouter} (Phase 1).
 *
 * The Phase-0 scaffold home is gone: `/` now redirects to the Connect screen
 * (Screen 01). The router also applies the dark/indigo default theme at load.
 */
export default function App() {
  return <AppRouter />;
}
