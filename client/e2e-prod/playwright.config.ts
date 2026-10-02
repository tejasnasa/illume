import { defineConfig } from "@playwright/test";

import { SMOKE_BASE_URL } from "./env";
import { STORAGE_STATE } from "./fixtures";

/**
 * End-to-end configuration for the production smoke suite.
 *
 * Deliberately a sibling of `e2e/` rather than a project inside it, because of what it
 * must *not* do: there is no `webServer` here and no `globalSetup`, so this config cannot
 * boot a local stack and cannot reach the local suite's seeding, which truncates the
 * database it runs against. Nothing in this file opens a database connection at all.
 *
 * Importing `./env` runs the target guard, so a non-https or non-allowlisted origin throws
 * while Playwright is still reading this file -- before a browser exists.
 *
 * Traces and video are off on purpose, not by omission. A trace records action parameters,
 * including the values typed into fields, and these artifacts are uploaded to anyone with
 * repository read. The password never goes through a field here (login is an API call), but
 * the rule is kept anyway so it cannot become wrong later. The failure screenshot stays:
 * the HTML report embeds it, and no credential is ever rendered on screen.
 */
export default defineConfig({
  testDir: ".",
  // Resolved against this file, so artifacts land under `e2e-prod/` rather than beside the
  // client's source -- and never in the local suite's `e2e/test-results`.
  outputDir: "test-results",
  // One account and one repository are shared, and the chat spec writes to it.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  // No retries: a retry would re-issue a real, billed LLM call.
  retries: 0,
  reporter: process.env.CI
    ? [
        // Named explicitly so this suite's report cannot overwrite the local suite's, which
        // is the default (`playwright-report`) and lands at the client root. An explicit
        // folder resolves against *this file* (`e2e-prod/`), so the report ends up in
        // `client/e2e-prod/playwright-report` -- the path the workflow uploads.
        ["html", { outputFolder: "playwright-report", open: "never" }],
        ["github"],
        ["list"],
      ]
    : [["html", { outputFolder: "playwright-report", open: "never" }], ["list"]],
  timeout: 90_000,
  expect: { timeout: 15_000 },

  use: {
    baseURL: SMOKE_BASE_URL,
    trace: "off",
    video: "off",
    screenshot: "only-on-failure",
    launchOptions: {
      // WebGL on a headless runner with no GPU. SwiftShader is the software rasteriser
      // Chromium ships for exactly this; `--enable-unsafe-swiftshader` is what silences the
      // newer builds' refusal to use it without an explicit opt-in. Without these the
      // dependency-graph canvas renders blank and the graph assertion fails for a reason
      // that has nothing to do with the deployed application.
      args: [
        "--use-gl=angle",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--disable-gpu-sandbox",
      ],
    },
  },

  projects: [
    {
      /** Signs in, verifies the cookie, checks the preconditions, clears the chat history. */
      name: "setup",
      testMatch: /auth\.setup\.ts/,
    },
    {
      /**
       * Anonymous checks, with **no dependencies**.
       *
       * If this depended on `setup`, a cookie-domain regression would skip the very specs
       * that would have reported the site is up, and the run would show one opaque "setup
       * failed" instead of a map of what broke.
       *
       * The empty storage state is belt-and-braces: no `storageState` is set in the
       * top-level `use`, because Playwright merges that into every project's contexts and
       * would silently sign in the anonymous specs.
       */
      name: "public",
      testMatch: /specs\/public\.spec\.ts/,
      retries: 1,
      use: { storageState: { cookies: [], origins: [] } },
    },
    {
      /** Read-only browsing of the deployed product with a real session. */
      name: "authenticated",
      testMatch: /specs\/authenticated\.spec\.ts/,
      dependencies: ["setup"],
      use: { storageState: STORAGE_STATE },
    },
    {
      /** The one project that writes anything in production. */
      name: "journey",
      testMatch: /specs\/journey\.spec\.ts/,
      dependencies: ["setup"],
      use: { storageState: STORAGE_STATE },
      retries: 0,
    },
  ],
});
