import path from "path";
import { configDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The FastAPI app (`uv run sensibility serve`). In dev, Vite serves the SPA
// and forwards everything server-side to it, so the session cookie and the
// API are same-origin from the browser's point of view.
const backend = process.env.SENSIBILITY_BACKEND ?? "http://127.0.0.1:8000";
const serverSide = ["/api", "/auth", "/login", "/logout", "/health"];

export default defineConfig({
  // FastAPI serves the build from the root (src/sensibility/web/spa.py),
  // with the hashed files at /assets/.
  base: "/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    proxy: Object.fromEntries(serverSide.map((p) => [p, backend])),
  },
  test: {
    globals: true,
    // Nested agent worktrees under .claude/ carry their own copy of every
    // test (and node_modules); never collect them.
    exclude: [...configDefaults.exclude, "**/.claude/**"],
    // src/lib is pure logic and runs without a DOM; everything else
    // (components, routes, the API client) runs in jsdom.
    projects: [
      {
        extends: true,
        test: {
          name: "lib",
          environment: "node",
          include: ["src/lib/**/*.test.{ts,tsx}"],
        },
      },
      {
        extends: true,
        test: {
          name: "dom",
          environment: "jsdom",
          setupFiles: ["./src/test/setup.ts"],
          include: ["src/**/*.test.{ts,tsx}"],
          exclude: [
            ...configDefaults.exclude,
            "**/.claude/**",
            "src/lib/**/*.test.{ts,tsx}",
          ],
        },
      },
    ],
  },
});
