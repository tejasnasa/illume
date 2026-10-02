/**
 * Configuration for the production smoke suite, resolved and validated at load time.
 *
 * `playwright.config.ts` imports this module, so anything wrong here -- a target that is
 * not allowlisted, a missing credential -- throws while Playwright is still reading the
 * config, before a browser or a request context exists. That is the point: a suite that
 * writes to production should refuse to start rather than fail halfway through.
 *
 * Values come from the environment first and `client/.env.smoke` second, never the other
 * way round, so the repository secrets CI provides always win over a stale local file.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

import { assertAllowedTarget } from "./guard";

/** Assigns `KEY=value` lines without overwriting anything already in the environment. */
function loadDotEnvSmoke(): void {
  let contents: string;
  try {
    contents = readFileSync(path.resolve(__dirname, "..", ".env.smoke"), "utf-8");
  } catch {
    // Absent is the normal case in CI, which supplies the same values as real variables.
    return;
  }

  for (const line of contents.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    const separator = trimmed.indexOf("=");
    if (separator === -1) continue;

    const key = trimmed.slice(0, separator).trim();
    let value = trimmed.slice(separator + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    process.env[key] ??= value;
  }
}

loadDotEnvSmoke();

const REQUIRED = [
  "SMOKE_BASE_URL",
  "SMOKE_API_URL",
  "SMOKE_EMAIL",
  "SMOKE_PASSWORD",
  "SMOKE_REPO_NAME",
] as const;

const missing = REQUIRED.filter((name) => !process.env[name]);
if (missing.length > 0) {
  // One message naming all of them: reporting the first and failing again on the next
  // turns provisioning into a guessing game.
  throw new Error(
    `Missing required production-smoke variables: ${missing.join(", ")}. Provide them as ` +
      "repository secrets and variables in CI, or in an untracked client/.env.smoke locally " +
      "(see client/.env.smoke.example).",
  );
}

export const SMOKE_BASE_URL = process.env.SMOKE_BASE_URL as string;
export const SMOKE_API_URL = process.env.SMOKE_API_URL as string;
export const SMOKE_EMAIL = process.env.SMOKE_EMAIL as string;
export const SMOKE_PASSWORD = process.env.SMOKE_PASSWORD as string;
export const SMOKE_REPO_NAME = process.env.SMOKE_REPO_NAME as string;

/** Comma-separated overrides, so a domain move does not require a code change. */
function hostSet(raw: string | undefined, fallback: string): Set<string> {
  return new Set(
    (raw ?? fallback)
      .split(",")
      .map((host) => host.trim().toLowerCase())
      .filter(Boolean),
  );
}

export const SMOKE_WEB_HOSTS = hostSet(process.env.SMOKE_ALLOWED_HOSTS, "illume.tejasnasa.me");
export const SMOKE_API_HOSTS = hostSet(
  process.env.SMOKE_ALLOWED_API_HOSTS,
  "illume-api.tejasnasa.me",
);

/**
 * What the session cookie's `Domain` must cover.
 *
 * The API sets it from `DOMAIN` on the droplet. Both hosts have to be able to see it --
 * the API because it authenticates the request, the web origin because the Next proxy
 * gates `/dashboard` and `/repo` on the cookie being present there.
 */
export const SMOKE_COOKIE_DOMAIN = (
  process.env.SMOKE_COOKIE_DOMAIN ?? "tejasnasa.me"
).replace(/^\./, "");

assertAllowedTarget({
  baseUrl: SMOKE_BASE_URL,
  apiUrl: SMOKE_API_URL,
  webHosts: SMOKE_WEB_HOSTS,
  apiHosts: SMOKE_API_HOSTS,
});

/** Logged on load so a report shows which origin and repository a run actually targeted. */
console.log(
  `production smoke: web=${SMOKE_BASE_URL} api=${SMOKE_API_URL} repo=${SMOKE_REPO_NAME}`,
);
