import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/dom";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { server } from "./msw/server";

/**
 * Gives `waitFor` and `findBy*` more headroom than the 1s default.
 *
 * A full-suite run executes every file in parallel, and the tests that wait on an
 * IntersectionObserver callback landing and then on an MSW round trip to render were
 * observed missing the 1s default by ~85ms under that load -- passing in isolation and
 * failing in the full run, which is the least useful kind of failure.
 *
 * Deliberately below vitest's 5s `testTimeout`: a wait longer than the test's own budget
 * cannot report which assertion was still unsatisfied, it just times the test out.
 */
configure({ asyncUtilTimeout: 3000 });

/**
 * Marks happy-dom's animation promises as handled before they are cancelled.
 *
 * `Animation#cancel()` rejects the instance's `finished` promise with an `AbortError`,
 * and framer-motion cancels every animation it owns while unmounting without ever
 * attaching a handler to that promise -- so each motion-bearing component that unmounts
 * leaves an unhandled rejection behind. Vitest reports those at the end of a run, and a
 * genuine unhandled rejection in product code would look identical to this noise.
 *
 * Attaching the no-op catch here rather than awaiting `finished` in each test keeps the
 * suppression in one place. It is a workaround for the DOM shim, not for the components:
 * in a real browser a cancelled animation's promise is not a rejection anyone is expected
 * to observe either.
 */
if (typeof window !== "undefined" && window.Animation) {
  const cancel = window.Animation.prototype.cancel;
  window.Animation.prototype.cancel = function (this: Animation) {
    this.finished?.catch(() => {});
    return cancel.call(this);
  };
}

/**
 * The backend base URL, for every module that builds an absolute request to it.
 *
 * Vitest loads `.env` into `import.meta.env` but only exposes `VITE_`-prefixed names
 * there, and leaves `process.env` alone -- so a `NEXT_PUBLIC_*` variable is undefined in
 * tests even though it is set for `next dev` and `next build`. Without this, every client
 * requests `undefined/api/v1/...` and fails with a URL parse error rather than anything
 * that points at the cause.
 *
 * Assigned rather than defaulted with `??=` only against the handlers' own default: the
 * two must agree, so `handlers.ts` reads the same variable.
 */
if (!process.env.NEXT_PUBLIC_BACKEND_URL) {
  process.env.NEXT_PUBLIC_BACKEND_URL = "http://localhost:8000";
}

// `next/image` cannot render outside a Next.js build: it calls getImgProps, which
// throws on a plain Vite transform. Any component using an image would fail to mount.
vi.mock("next/image", async () => {
  const mod = await import("./mocks/next-image");
  return { default: mod.default };
});

/**
 * Runs for every test in both projects.
 *
 * `cleanup` is called unconditionally rather than behind a DOM check: importing it in
 * the `node` project is harmless, and guarding on `document` would silently stop
 * unmounting in the `dom` project if the environment were ever misconfigured.
 */
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  cleanup();
});

afterAll(() => {
  server.close();
});
