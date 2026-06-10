import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// The frontend talks to the loopback control plane over a same-origin `/api/v1`
// base (see src/api/client.ts). In dev the Vite server (:5173) and the backend
// (:8787) are different origins, so we proxy `/api` → the backend here. This is
// the single seam that wires the browser to the API for `npm run dev`.
export default defineConfig(({ mode }) => {
  // Node-side env (NOT the browser bundle). Read from the shell / frontend `.env`
  // (no VITE_ prefix filter) so the local control-plane token is injected by the
  // proxy server-side and never ships in the client bundle (INV-1).
  const env = loadEnv(mode, process.cwd(), "");
  const backendOrigin = env.DKMV_BACKEND_ORIGIN || "http://127.0.0.1:8787";
  const platformToken = env.DKMV_PLATFORM_TOKEN || "";

  return {
    plugins: [react()],
    server: {
      // Loopback only; mirrors the backend's loopback bind (INV-1).
      host: "127.0.0.1",
      port: 5173,
      proxy: {
        // Proxy the API to the backend so the browser's relative `/api/v1`
        // requests (and the SSE `EventSource`) reach the control plane.
        "/api": {
          target: backendOrigin,
          // changeOrigin is LEFT OFF on purpose: the backend's access-control
          // middleware requires a loopback `Host` header (127.0.0.1/::1/localhost,
          // port-agnostic). Keeping the browser's `127.0.0.1:5173` Host passes that
          // gate; rewriting it to a compose service name (`backend:8787`) would 403.
          changeOrigin: false,
          // Inject the local control-plane token (INV-1) SERVER-SIDE so it never
          // ships in the browser bundle. `EventSource` can't set headers, so SSE
          // relies on the HttpOnly cookie the backend sets on the first
          // authenticated POST (e.g. `POST /runs`); this header covers every other
          // `/api` call. Set `DKMV_PLATFORM_TOKEN` in the shell or frontend `.env`.
          configure: (proxy) => {
            if (!platformToken) return;
            proxy.on("proxyReq", (proxyReq) => {
              if (!proxyReq.getHeader("authorization")) {
                proxyReq.setHeader("authorization", `Bearer ${platformToken}`);
              }
            });
          },
        },
      },
    },
    test: {
      globals: true,
      // jsdom for component render tests (Connect flow, theme).
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      // Co-located component tests in src/** PLUS the cross-screen a11y suite under
      // tests/ (slice 5.3 / AC-10 — the axe + keyboard-drag render test).
      include: ["src/**/*.{test,spec}.{ts,tsx}", "tests/**/*.{test,spec}.{ts,tsx}"],
      // Keep the empty-suite gate green for slices that ship no frontend tests.
      passWithNoTests: true,
      // CSS imports are side-effect-only in tests; let vitest no-op them.
      css: false,
    },
  };
});
