import { expect, test } from "@playwright/test";

import { PRIMARY_REPO_NAME, readSeed, repoNamed, type SeededRepo } from "../fixtures";

/**
 * The RAG chat flow, end to end.
 *
 * This is the one spec that exercises a real LLM call path -- through the API, out to
 * `scripts/openai_stub_server.py`. Nothing about the *text* is asserted (the stub returns
 * one fixed sentence); what is under test is the chain: the question reaches
 * `answer_question`, the query embeds, the vector search runs against real pgvector, an
 * answer comes back, and the client renders it with its sources.
 *
 * The seeded repository has one persisted turn, which is what the history assertions read.
 * The specs that ask questions add turns, and none of them are cleaned up: the seed
 * deletes and rebuilds the user's repositories before every run, so a run always starts
 * from one turn, and every assertion here is on the presence of specific text rather than
 * on a count.
 */

/**
 * Resolved in `beforeEach`, not at module scope -- Playwright loads every spec file to
 * build its test list before any project runs, so reading the seed artifact here throws on
 * a clean checkout and takes the run down during collection. Registered before the
 * navigation hook below, so `home` is set by the time that one reads it.
 */
let repo: SeededRepo;
let home: string;

test.beforeEach(() => {
  repo = repoNamed(readSeed(), PRIMARY_REPO_NAME);
  home = `/repo/${repo.repo_num}`;
});

/** The composer, found by its placeholder rather than by position. */
function composer(page: import("@playwright/test").Page) {
  return page.getByPlaceholder(/Ask about the codebase/);
}

/**
 * Turns accumulate within a run: the seed resets the repository once, and every spec that
 * asks a question persists another turn. So a locator matching answer text matches every
 * turn so far, and assertions use `.last()` -- the newest turn is appended last. Asserting
 * on a count instead would make the suite order-dependent.
 */
test.beforeEach(async ({ page }) => {
  await page.goto(home);
  await expect(page.getByRole("heading", { name: /Chat with Codebase/i })).toBeVisible();
});

test.describe("history", () => {
  test("loads the persisted turn", async ({ page }) => {
    await expect(page.getByText("What does func_0 do?").last()).toBeVisible();
  });

  test("renders the persisted answer", async ({ page }) => {
    await expect(page.getByText(/the first function in the fixture/).last()).toBeVisible();
  });

  test("offers a clear action once a turn exists", async ({ page }) => {
    await expect(page.getByTitle("Clear Chat History")).toBeVisible();
  });
});

test.describe("asking a question", () => {
  test("shows the question before the answer arrives", async ({ page }) => {
    // The optimistic bubble. Asserted immediately after send, before the round trip --
    // which is why the assertion is on the question text rather than on a settled state.
    await composer(page).fill("What is module_1?");
    await page.getByRole("button", { name: /^Send$/ }).click();

    await expect(page.getByText("What is module_1?").last()).toBeVisible();
  });

  test("renders the answer", async ({ page }) => {
    await composer(page).fill("What is module_1?");
    await page.getByRole("button", { name: /^Send$/ }).click();

    // The stub's sentence, arriving through the real retrieval pipeline.
    await expect(page.getByText(/Based on the indexed sources/).last()).toBeVisible({
      timeout: 30_000,
    });
  });

  test("renders the citation for the answer", async ({ page }) => {
    await composer(page).fill("What does func_0 do?");
    await page.getByRole("button", { name: /^Send$/ }).click();
    await expect(page.getByText(/Based on the indexed sources/).last()).toBeVisible({
      timeout: 30_000,
    });

    // The seeded embeddings make `func_0` the nearest symbol, and the card renders its
    // name.
    await expect(page.getByText(/Sources Cited/).last()).toBeVisible();
  });

  test("clears the composer after sending", async ({ page }) => {
    await composer(page).fill("What is module_1?");
    await page.getByRole("button", { name: /^Send$/ }).click();

    await expect(composer(page)).toHaveValue("");
  });

  test("is disabled for an empty question", async ({ page }) => {
    await expect(page.getByRole("button", { name: /^Send$/ })).toBeDisabled();
  });
});

test.describe("persistence", () => {
  test("keeps a new turn across a reload", async ({ page }) => {
    await composer(page).fill("Does this survive a refresh?");
    await page.getByRole("button", { name: /^Send$/ }).click();
    await expect(page.getByText(/Based on the indexed sources/).last()).toBeVisible({
      timeout: 30_000,
    });

    await page.reload();

    // The answer is read back from `chat_messages.sources`, so a turn that only lived in
    // client state would disappear here.
    await expect(page.getByText("Does this survive a refresh?").last()).toBeVisible();
  });
});
