import { http, HttpResponse } from "msw";

/**
 * Backend base URL as the browser sees it.
 *
 * Components and API clients build absolute URLs from this value, so the handlers below
 * must key on it rather than on a relative path. Defaults to the dev server when the
 * variable is unset.
 */
export const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

/**
 * Shared request handlers.
 *
 * These are intentionally empty of per-test behaviour: handlers added here apply to
 * every test, and anything scenario-specific belongs in the test that needs it via
 * `server.use(...)`. Tests run with `onUnhandledRequest: "error"`, so a request that
 * reaches the network is a failure rather than a silent real call.
 */
export const handlers = [
  http.get(`${BACKEND_URL}/healthz`, () =>
    HttpResponse.json({ status: "ok" }),
  ),
];
