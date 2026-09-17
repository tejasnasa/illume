import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { API_URL, serverEnv } from "./env";
import { ARTIFACT_DIR, readSeed, SEED_FILE } from "./fixtures";

/**
 * Prepares the database the rest of the suite reads.
 *
 * A test rather than `globalSetup` because the seed talks to the API, and Playwright only
 * guarantees every `webServer` is listening before a project's tests run. In `globalSetup`
 * the seed would race the server it is calling.
 *
 * The script itself runs migrations, deletes the previous run's user, registers a fresh
 * one through the public endpoint, and inserts two fully-ingested repositories. See
 * `server/scripts/seed_e2e.py` for why two.
 */
test("seed the E2E database", () => {
  mkdirSync(ARTIFACT_DIR, { recursive: true });

  const serverRoot = path.resolve(__dirname, "../../server");
  const python = process.platform === "win32" ? "uv.exe" : "uv";

  execFileSync(
    python,
    ["run", "python", "scripts/seed_e2e.py"],
    {
      cwd: serverRoot,
      stdio: "inherit",
      // The seed writes rows the API has to read, so it needs the *same* database
      // environment the API was started with -- not whatever `server/.env` happens to
      // point at. Getting this wrong shows up as an empty dashboard, not an error.
      env: { ...process.env, ...serverEnv, E2E_BASE_URL: API_URL, E2E_SEED_OUTPUT: SEED_FILE },
    },
  );

  // The script exits non-zero on any failure, so reaching here means it ran; this checks
  // it produced the thing the specs read.
  expect(readSeed().repos.length).toBeGreaterThan(0);
});
