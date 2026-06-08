import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Phase 1: Vite serves the real screens (Connect now; Board in slice 1.5).
export default defineConfig({
  plugins: [react()],
  server: {
    // Loopback only; mirrors the backend's loopback bind (INV-1).
    host: "127.0.0.1",
    port: 5173,
  },
  test: {
    globals: true,
    // jsdom for component render tests (Connect flow, theme).
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Keep the empty-suite gate green for slices that ship no frontend tests.
    passWithNoTests: true,
    // CSS imports are side-effect-only in tests; let vitest no-op them.
    css: false,
  },
});
