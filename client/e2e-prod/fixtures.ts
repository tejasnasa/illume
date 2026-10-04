/**
 * Artifacts and types shared by the production smoke specs.
 *
 * The setup project resolves the smoke repository once and writes it here, so the specs
 * read identifiers rather than each re-querying the API. It also records the account's
 * free-tier counter, which the chat spec compares against after its one billed-by-BYOU
 * question.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

/** Written at runtime and gitignored; kept beside the suite so nothing is shared with `e2e/`. */
export const ARTIFACT_DIR = path.join(__dirname, ".auth");
export const STORAGE_STATE = path.join(ARTIFACT_DIR, "user.json");
export const SMOKE_INFO = path.join(ARTIFACT_DIR, "smoke.json");

export interface SmokeRepo {
  id: string;
  name: string;
  repoNumber: number;
}

export interface SmokeInfo {
  repo: SmokeRepo;
  /**
   * The account's free-chat counter as setup found it.
   *
   * The suite's one chat question must not move this. If it does, the account has lost its
   * own key and is quietly spending the ten-message lifetime allowance the free tier
   * grants -- which would exhaust the account within a week of nightly runs.
   */
  freeChatMessagesUsed: number;
}

/** Reads the setup artifact, failing with the command to run if it is missing. */
export function readSmokeInfo(): SmokeInfo {
  try {
    return JSON.parse(readFileSync(SMOKE_INFO, "utf-8")) as SmokeInfo;
  } catch {
    throw new Error(
      `no smoke artifact at ${SMOKE_INFO}. The "setup" project writes it; run ` +
        "`npx playwright test --config=e2e-prod/playwright.config.ts --project=setup` first, " +
        "or just run the whole suite.",
    );
  }
}

/** The repository route for the smoke repository. */
export function repoHome(info: SmokeInfo): string {
  return `/repo/${info.repo.repoNumber}`;
}

/** The chat endpoints for the smoke repository, on the API origin. */
export function chatUrls(apiUrl: string, info: SmokeInfo) {
  const base = `${apiUrl}/api/v1/repository/${info.repo.id}/chat`;
  return { history: `${base}/history`, send: base, clear: base };
}
