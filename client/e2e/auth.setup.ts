import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test as setup } from "@playwright/test";

import { readSeed, STORAGE_STATE } from "./fixtures";

/**
 * Signs in once and saves the session for every other spec.
 *
 * **Through the API, not the login page**, and that is not a shortcut. The login route
 * renders `LoginForm`, which is a single "Continue with GitHub" button and no credential
 * fields at all -- there is no email/password form anywhere in the UI, and no `/signup`
 * route either (`SignupForm` and `useLoginForm` exist, but no route renders either one).
 * So an E2E run cannot authenticate the way a user with a password would, because no
 * such user can.
 *
 * The seeded user does have a password, and `POST /api/v1/auth/login` accepts it, so the
 * cookie this writes is a real session cookie from the real endpoint -- the same one the
 * browser would hold after an OAuth round trip. What is skipped is the GitHub redirect,
 * which needs live GitHub credentials and a third party that must not be in the critical
 * path of a nightly job.
 *
 * If a credential login form is ever added, this should drive it instead: what is being
 * avoided is inventing a session, not using the API.
 */
setup("authenticate", async ({ request }) => {
  const seed = readSeed();

  const response = await request.post(`${seed.base_url}/api/v1/auth/login`, {
    data: { email: seed.email, password: seed.password },
  });

  // A 401 here means the seed registered a user with a different password than the
  // artifact recorded, which is a seed bug rather than a test failure.
  expect(
    response.status(),
    `login failed: ${response.status()} ${await response.text()}`,
  ).toBe(200);

  mkdirSync(path.dirname(STORAGE_STATE), { recursive: true });
  await request.storageState({ path: STORAGE_STATE });
});
