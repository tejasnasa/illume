/**
 * Ports and environment for the E2E stack, in one place.
 *
 * Shared by `playwright.config.ts` (which owns the web servers) and `seed.setup.ts`
 * (which runs a script *against* them). Both have to agree on the database in
 * particular: the config starts the API against the test Postgres, and the seed inserts
 * rows the API must then read. Defining the environment twice is how those two drift
 * apart, and the failure looks like an empty dashboard rather than a misconfiguration.
 */

/**
 * Overridable so a run can coexist with a dev stack on the default ports. Both defaults
 * are the ports a developer is most likely to already have running, which would otherwise
 * make "run the E2E suite" and "run the app" mutually exclusive on one machine.
 */
export const CLIENT_PORT = Number(process.env.E2E_CLIENT_PORT ?? 3000);
export const API_PORT = Number(process.env.E2E_API_PORT ?? 8000);
export const STUB_PORT = Number(process.env.E2E_STUB_PORT ?? 8099);

export const CLIENT_URL = `http://localhost:${CLIENT_PORT}`;
/** `localhost`, not `127.0.0.1` -- see the note on the cookie domain below. */
export const API_URL = `http://localhost:${API_PORT}`;
export const STUB_URL = `http://127.0.0.1:${STUB_PORT}`;

/**
 * The environment every server-side process needs.
 *
 * Mirrors `server/.env.test.example`, and points at the same Postgres and Redis the
 * backend test suite uses -- so a machine that can run one suite can run the other.
 *
 * `DOMAIN=localhost` is not decoration: it is passed straight through as the session
 * cookie's `Domain` attribute, and the browser is on `localhost`. A value of
 * `127.0.0.1` here (or in `API_URL`) would make the cookie host-only for one spelling
 * and unsendable from the other, which presents as a login that silently does not
 * persist.
 */
export const serverEnv = {
  DATABASE_URL: "postgresql+asyncpg://illume:test@localhost:5433/illume_test",
  SYNC_DATABASE_URL: "postgresql://illume:test@localhost:5433/illume_test",
  REDIS_URL: "redis://localhost:6380/0",
  SECRET_KEY: "test-secret-key-not-for-production",
  ACCESS_TOKEN_EXPIRE_MINUTES: "1440",
  FRONTEND_URL: CLIENT_URL,
  ENVIRONMENT: "development",
  GITHUB_CLIENT_ID: "test-github-client-id",
  GITHUB_CLIENT_SECRET: "test-github-client-secret",
  GITHUB_REDIRECT_URL: `${API_URL}/api/v1/auth/github/callback`,
  DOMAIN: "localhost",
  // The seam. The OpenAI SDK reads OPENAI_BASE_URL from the environment, so every LLM
  // call the API makes lands on the stub with no code change.
  OPENAI_API_KEY: "stub-key-not-a-credential",
  OPENAI_BASE_URL: `${STUB_URL}/v1`,
  AI_MODEL: "gpt-4o-mini",
};
