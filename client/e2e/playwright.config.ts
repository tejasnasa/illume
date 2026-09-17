import { defineConfig, devices } from "@playwright/test";

import { API_PORT, API_URL, CLIENT_PORT, CLIENT_URL, serverEnv, STUB_URL } from "./env";
import { STORAGE_STATE } from "./fixtures";

/**
 * End-to-end configuration.
 *
 * `API_URL` is `localhost`, not `127.0.0.1`, and that is load-bearing: the API sets its
 * session cookie with `Domain=localhost`, so a browser request to `127.0.0.1` would be a
 * different host and the cookie would not be sent. It has to be the same spelling on the
 * browser side, the CORS allow-list (`FRONTEND_URL`), and the cookie domain.
 *
 * Runs against a **real stack**: a migrated Postgres and Redis, the actual FastAPI app,
 * and a production Next build. The only thing faked is OpenAI, which is pointed at
 * `server/scripts/openai_stub_server.py` -- an E2E run must never make a billed call, and
 * the answer text is not what these specs are asserting.
 *
 * Three web servers, started by Playwright in the order listed and each polled until it
 * answers its `url`:
 *
 * `cwd` for each is resolved from **this file's directory**, not the shell's -- which is
 * why the server paths climb two levels and the client's climbs one.
 *
 * 1. the OpenAI stub on :8099
 * 2. the API on :8000, against the **test** database on :5433 and Redis on :6380 --
 *    deliberately the same services the backend suite uses, so a machine that can run one
 *    can run the other
 * 3. the client on :3000, from `next build` output rather than `next dev`
 *
 * Deliberately absent: a Celery worker. Nothing in these specs waits for an ingestion to
 * complete; the seeded repository is inserted directly, and the pipeline itself is covered
 * by the eager Celery tests on the backend side.
 */
export default defineConfig({
  testDir: ".",
  // Both are relative to this file, so the artifacts land under `e2e/` rather than
  // beside the client's source.
  outputDir: "test-results",
  // The seeded database is shared and `reingest.spec.ts` mutates a repository, so the
  // specs cannot run concurrently. File order is not relied on for correctness either --
  // re-ingest targets a repository of its own -- but keeping them serial makes a failure
  // easier to read.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 2,
  reporter: process.env.CI
    ? [["html", { open: "never" }], ["github"], ["list"]]
    : [["html", { open: "never" }], ["list"]],
  timeout: 60_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: CLIENT_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    {
      /**
       * Migrations, registration, and the seeded rows.
       *
       * `seed_e2e.py` is run as a test rather than from `globalSetup` because it needs the
       * API to be listening, and Playwright guarantees a dependency project runs after
       * every web server is up.
       */
      name: "seed",
      testMatch: /seed\.setup\.ts/,
    },
    {
      /** Signs in once and writes the cookie state every other project reuses. */
      name: "auth",
      testMatch: /auth\.setup\.ts/,
      dependencies: ["seed"],
    },
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        storageState: STORAGE_STATE,
        launchOptions: {
          // WebGL on a headless run with no GPU. SwiftShader is the software rasteriser
          // Chromium ships for exactly this; `--enable-unsafe-swiftshader` is what
          // silences the newer builds' refusal to use it without an explicit opt-in.
          args: [
            "--use-gl=angle",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
            "--disable-gpu-sandbox",
          ],
        },
      },
      dependencies: ["auth"],
    },
  ],

  webServer: [
    {
      command: "uv run python scripts/openai_stub_server.py",
      cwd: "../../server",
      url: `${STUB_URL}/healthz`,
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
      timeout: 120_000,
    },
    {
      command: `uv run python -m uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT}`,
      cwd: "../../server",
      url: `${API_URL}/healthz`,
      env: serverEnv,
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
      timeout: 120_000,
    },
    {
      /**
       * Builds and then serves. The build is part of the command rather than a step the
       * caller is trusted to have run, because `NEXT_PUBLIC_BACKEND_URL` is inlined at
       * build time -- passing it to `next start` would do nothing, and a build made
       * against a different URL fails in the browser as a CORS or connection error,
       * which reads nothing like "your build is stale".
       */
      command: "npm run build && npm run start",
      cwd: "..",
      url: CLIENT_URL,
      // `PORT` is how `next start` is told which port to bind; the override in `env.ts`
      // would otherwise only move the *polling* URL and the server would still take 3000.
      env: { NEXT_PUBLIC_BACKEND_URL: API_URL, PORT: String(CLIENT_PORT) },
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
      timeout: 300_000,
    },
  ],
});
