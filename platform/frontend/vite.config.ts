import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Phase 0 scaffold: Vite boots, router stub only. Real screens land in Phase 1.
export default defineConfig({
  plugins: [react()],
  server: {
    // Loopback only; mirrors the backend's loopback bind (INV-1).
    host: "127.0.0.1",
    port: 5173,
  },
  test: {
    globals: true,
    // Scaffold-only: no jsdom/testing-library yet — the first Phase-1 UI slice
    // adds the browser env + setup. Keep `node` here so we don't pull speculative
    // deps now.
    environment: "node",
    // The canonical shared gate is `npx vitest run` (_conventions.md). Phase 0
    // ships no frontend tests yet, so without this the gate exits 1 with
    // "No test files found" and hard-fails every slice before its first test
    // lands. passWithNoTests makes an empty suite a green gate.
    passWithNoTests: true,
  },
});
