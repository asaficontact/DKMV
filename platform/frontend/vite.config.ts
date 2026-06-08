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
    environment: "node",
  },
});
