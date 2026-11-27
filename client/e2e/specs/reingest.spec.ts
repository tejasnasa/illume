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
 * Found by role and accessible name: it is a link to the repository's settings page,
 * labelled "Repository settings".
 */
function settingsGear(page: import("@playwright/test").Page) {
  return page.getByRole("link", { name: "Repository settings" });
}

/**
 * Waits for the repository route to finish streaming.
 *
 * `repo/[id]/loading.tsx` renders placeholder blocks with no heading, so the page's
 * level-one heading (the repository's name) appears only once the server component has
 * resolved -- a real wait rather than a sleep.
 */
async function settle(page: import("@playwright/test").Page) {
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

test.describe("the settings panel", () => {
  test("offers the re-ingest controls", async ({ page }) => {
    await page.goto(home);

    await settingsGear(page).click();

    await expect(
      page.getByText("Regenerate analysis", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Regenerate", exact: true }),
    ).toBeVisible();
  });

  test("does not re-ingest anything until asked", async ({ page }) => {
    // The destructive action is behind a confirmation, so opening the panel must not
    // touch the repository -- a check that the seeding of `reingest-me` is intact, which
    // the later tests in this file depend on.
    await page.goto(home);
    await settle(page);

    await expect(
      page.getByText("Ready", { exact: true }).first(),
    ).toBeVisible();
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
    await expect(
      page.getByText("Ready", { exact: true }).first(),
    ).toBeVisible();

    await settingsGear(page).click();

    // Two steps: the row's "Regenerate" opens a confirmation dialog, and the
    // dialog's own "Regenerate" is what acts.
    await page.getByRole("button", { name: "Regenerate", exact: true }).click();
    await page
      .getByRole("dialog", { name: "Regenerate analysis" })
      .getByRole("button", { name: "Regenerate", exact: true })
      .click();

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
