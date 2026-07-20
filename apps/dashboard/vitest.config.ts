import { defineConfig } from "vitest/config";
import path from "node:path";

// Lightweight unit-test harness for pure/proxy logic (route handlers, helpers).
// The e2e Playwright suite (./e2e) hits a live deployment and is excluded here.
export default defineConfig({
  test: {
    environment: "node",
    include: ["**/*.unit.test.ts"],
    exclude: ["node_modules", "e2e", ".next"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
