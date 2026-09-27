import { expect, test } from "@playwright/test";

import {
  readSeed,
  REINGEST_REPO_NAME,
  repoNamed,
  type SeededRepo,
} from "../fixtures";

/**
 * Re-ingest: choosing a version and handing the repository back to the pipeline.
 *
 * Runs against a repository of its own (`reingest-me`), because the endpoint **deletes the
 * repository row and recreates it**, cascading away every file, symbol, guide, and chat
 * turn. If this spec targeted the browsing fixture, the rest of the suite would pass or
 * fail depending on whether Playwright happened to run this file first.
 *
 * The free-tier quota gate refuses re-ingest for keyless users (the seeded user is
 * keyless; the chat suite shares the same account, and pre-seeding a key would break
 * the chat spec's free-tier flow). The UI flow that used to live in this file -- click
 * Regenerate, observe the row move to ``pending`` on the dashboard -- is therefore
 * asserted at the gate instead: the keyless user gets the 402 message and stays on the
 * page. The full BYOK path is tested by the backend's integration suite
 * (``tests/integration/api/test_free_tier.py``); the E2E contribution here is that the
 * gate fires end-to-end and the dashboard render is not torn down by an action that
 * will not actually run.
 */

/**
 * Resolved in `beforeEach`, not at module scope -- Playwright loads every spec file to
 * build its test list before any project runs, so reading the seed artifact here throws on
 * a clean checkout and takes the run down during collection. See `seeded-browse.spec.ts`.
 */
let repo: SeededRepo;
let home: string;

test.beforeEach(() => {
  repo = repoNamed(readSeed(), REINGEST_REPO_NAME);
  home = `/repo/${repo.repo_num}`;
});

/**
 * The settings gear in the repository navbar.
 *
 * Found by role and accessible name. That is only possible because `Modal`'s trigger is
 * now a real `<button aria-label="Repository settings">` rather than a bare `<div
 * onClick>`: a control with no role, no name and no tab stop can only be addressed by a
 * class selector, which is what this helper used to do. Driving it by name here is the
 * end-to-end proof that the fix reaches a real browser.
 */
function settingsGear(page: import("@playwright/test").Page) {
  return page.getByRole("button", { name: "Repository settings" });
}

/**
 * Waits for the repository route to finish streaming.
 *
 * `repo/[id]/loading.tsx` renders a pulsing skeleton that carries the same "Processing
 * Status" label as the real page, so while the server component is resolving a bare
 * locator for that text matches **two** elements and Playwright raises a strict-mode
 * violation. Waiting for the count to reach one is the settled state, and it is a real
 * wait rather than a sleep -- the skeleton disappears when the page arrives.
 */
async function settle(page: import("@playwright/test").Page) {
  await expect(page.getByText("Processing Status")).toHaveCount(1);
}

test.describe("the settings panel", () => {
  test("offers the re-ingest controls", async ({ page }) => {
    await page.goto(home);

    await settingsGear(page).click();

    await expect(page.getByText(/Regenerate Repository/i)).toBeVisible();
  });

  test("does not re-ingest anything until asked", async ({ page }) => {
    // The destructive action is behind a confirmation, so opening the panel must not
    // touch the repository -- a check that the seeding of `reingest-me` is intact, which
    // the later tests in this file depend on.
    await page.goto(home);
    await settle(page);

    await expect(page.getByText(/^ready$/).first()).toBeVisible();
  });
});

test.describe("re-ingesting", () => {
  test("refuses for a keyless user and stays on the repo page", async ({
    page,
  }) => {
    // The seeded user is keyless (the chat suite shares the account and needs
    // the free-tier counter at zero to drive the chat budget; pre-seeding a
    // BYOK key would mask that). The route gates re-ingest on ``has_ai_key``,
    // so the destructive action is refused and the page never navigates --
    // which is what keeps the dashboard render intact.
    await page.goto(home);
    await settle(page);
    await expect(page.getByText(/^ready$/).first()).toBeVisible();

    await settingsGear(page).click();

    // Two steps: the panel's "Regenerate" opens a confirmation, and the
    // confirmation's "REGENERATE" is what acts. Matched exactly, since
    // the two labels differ only in case.
    await page.getByRole("button", { name: "Regenerate", exact: true }).click();
    await page.getByRole("button", { name: "REGENERATE", exact: true }).click();

    // The route returns 402 and the action throws a generic error -- the
    // observable outcome is that the page never navigates to /dashboard.
    // If the gate regressed and re-ingest went through, the dashboard would
    // briefly hide the ``reingest-me`` card mid-flight and the rest of the
    // suite would see an unexpected "repository not found". Give the
    // server-action redirect a moment to fire (or not) before asserting.
    await page.waitForTimeout(2_000);
    await expect(page).toHaveURL(/\/repo\//);
    await expect(page).not.toHaveURL(/\/dashboard/);
  });
});
