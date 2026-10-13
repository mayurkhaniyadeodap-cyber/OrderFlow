import { readFileSync } from "node:fs";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

/** Backend port: PORT env var, else PORT= in backend/.env, else 8000 (same order as the start scripts). */
function backendPort(): string {
  if (process.env.PORT) return process.env.PORT;
  try {
    const env = readFileSync(new URL("../backend/.env", import.meta.url), "utf-8");
    const match = /^\s*PORT\s*=\s*(\d+)\s*$/m.exec(env);
    if (match) return match[1];
  } catch {
    /* no .env yet */
  }
  return "8000";
}

const apiTarget = process.env.ORDERFLOW_API || `http://127.0.0.1:${backendPort()}`;

// The dev server proxies /api to the FastAPI backend, so the browser talks to one origin.
// ORDERFLOW_BASE: sub-path the built app is served under on a live server (e.g. /orderflow/); default "/".
export default defineConfig({
  base: process.env.ORDERFLOW_BASE || "/",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": { target: apiTarget, changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: false },
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], css: false },
});
