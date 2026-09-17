import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

/**
 * Two projects, split by environment rather than by directory.
 *
 * Pure logic (API clients, utils, validators, the auth middleware) needs no DOM, so it
 * runs in the faster `node` environment. Anything that renders or mounts a hook needs a
 * DOM, and gets `happy-dom`.
 *
 * The split is load-bearing: importing a component under the `node` environment fails
 * with a confusing "document is not defined" rather than a clear error, so a new
 * component test belongs in the `dom` project's include list.
 */
export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  test: {
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.d.ts",
        "src/**/__tests__/**",
        // Route-level files that only re-export or hold no logic worth asserting on.
        "src/app/**/loading.tsx",
        "src/app/**/error.tsx",
      ],
    },
    projects: [
      {
        test: {
          name: "node",
          environment: "node",
          include: [
            "tests/unit/api/**/*.test.ts",
            "tests/unit/utils/**/*.test.ts",
            "tests/unit/types/**/*.test.ts",
            "tests/unit/*.test.ts",
          ],
        },
      },
      {
        test: {
          name: "dom",
          environment: "happy-dom",
          include: [
            "tests/unit/hooks/**/*.test.{ts,tsx}",
            // `lib/use-toast` is React state, not pure logic, so it needs a DOM even
            // though it holds no JSX. Everything else under `unit/` is environment-free.
            "tests/unit/lib/**/*.test.{ts,tsx}",
            "src/**/__tests__/**/*.test.{ts,tsx}",
          ],
        },
      },
    ],
  },
});
