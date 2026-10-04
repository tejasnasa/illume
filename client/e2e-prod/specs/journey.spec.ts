import { expect, test, type Page } from "@playwright/test";

import { SMOKE_API_URL } from "../env";
import { chatUrls, readSmokeInfo, repoHome, type SmokeInfo } from "../fixtures";

/**
 * The critical path, and the only project that writes anything in production.
 *
 * Exactly one thing is written: a single chat turn, which is deleted again afterwards. No
 * repository is created, re-ingested, or reconfigured -- re-ingest in particular destroys
 * and rebuilds the row, and the one free ingestion the account has is not something a
 * nightly job may spend.
 *
 * There is no janitor for this, and the reason it is safe is worth stating: the history has
 * a delete-all endpoint, the teardown below runs on failure as well as success, and setup
 * clears the same history before every run. A run killed before its teardown is therefore
 * cleaned up by the next one, which bounds accumulation to a single run's turns.
 *
 * This is also the one spec that makes a real, billed call -- the generation runs on the
 * smoke account's own key, and the query embedding runs on the operator's. That is why
 * there are no retries and why the whole journey is a single test: splitting it would
 * re-issue the call once per assertion.
 */

let info: SmokeInfo;

const QUESTION = "What does this repository do?";

test.beforeEach(async ({ page }) => {
  info = readSmokeInfo();
  await page.goto(repoHome(info));
  await expect(page.getByRole("heading", { name: /Chat with Codebase/i })).toBeVisible();
});

/**
 * Clears the repository's chat history, so a failure leaves nothing behind.
 *
 * Uses the browser context's request client rather than the `request` fixture: the former
 * shares the context's cookie jar, while the latter would need the session to be
 * re-established. The absolute API URL is required for the same reason -- the browser
 * reaches the backend only through `NEXT_PUBLIC_BACKEND_URL`, and a request against the web
 * origin would go to the client host and 404.
 */
test.afterEach(async ({ page }) => {
  const { clear } = chatUrls(SMOKE_API_URL, info);
  const response = await page.context().request.delete(clear);

  expect(response.status(), "clearing the chat history failed").toBe(204);
});

/** Polls the history endpoint until a turn with an answer has been persisted. */
async function waitForPersistedTurn(page: Page) {
  const { history } = chatUrls(SMOKE_API_URL, info);

  await expect
    .poll(
      async () => {
        const response = await page.context().request.get(history);
        if (response.status() !== 200) return 0;
        const turns = (await response.json()) as { answer: string }[];
        return turns.filter((turn) => turn.answer?.trim()).length;
      },
      {
        timeout: 90_000,
        message:
          "no answer was persisted. The question reached the API but neither the embedding " +
          "call nor the generation completed -- check the account's key and the operator's " +
          "OPENAI_API_KEY, which is what the query embedding runs on.",
      },
    )
    .toBeGreaterThan(0);
}

test("answers from the indexed sources and keeps the turn", async ({ page }) => {
  const composer = page.getByPlaceholder(/Ask about the codebase/);
  await composer.fill(QUESTION);
  await page.getByRole("button", { name: /^Send$/ }).click();

  // The optimistic bubble, asserted before the round trip.
  await expect(page.getByText(QUESTION).last()).toBeVisible();

  await waitForPersistedTurn(page);

  const { history } = chatUrls(SMOKE_API_URL, info);
  const turns = (await (await page.context().request.get(history)).json()) as {
    question: string;
    answer: string;
    sources: unknown[] | null;
  }[];
  const latest = turns[turns.length - 1];

  // Deliberately structural rather than about the text: the answer is generated, so only
  // its existence is stable. A turn that came back empty is the shape a silently-broken
  // provider call takes.
  expect(latest.question).toBe(QUESTION);
  expect(latest.answer.trim().length).toBeGreaterThan(0);
  expect(
    latest.sources?.length ?? 0,
    "the answer cited no sources, so retrieval found nothing in the index. That is either " +
      "an empty embedding table or an embedding/query mismatch, not a normal answer.",
  ).toBeGreaterThan(0);

  // The citation card is rendered from the persisted `sources` column.
  await expect(page.getByText(/Sources Cited/).last()).toBeVisible({ timeout: 30_000 });

  await page.reload();

  // Read back from the database rather than from client state, which is what makes this a
  // persistence assertion and not a rendering one.
  await expect(page.getByText(QUESTION).last()).toBeVisible({ timeout: 30_000 });
});

test("does not spend the account's free-tier allowance", async ({ page }) => {
  // Guards the premise the whole suite is built on: the account holds its own key, so chat
  // is unmetered. Without it the free path takes over and the ten-message lifetime
  // allowance would be gone within a week of nightly runs -- and the failure would be a 402
  // in some later run, pointing nowhere near the cause.
  const response = await page.context().request.get(`${SMOKE_API_URL}/api/v1/auth/me`);
  expect(response.status()).toBe(200);

  const account = (await response.json()) as { free_chat_messages_used: number };
  expect(account.free_chat_messages_used).toBe(info.freeChatMessagesUsed);
});

test("disables the composer for an empty question", async ({ page }) => {
  await expect(page.getByRole("button", { name: /^Send$/ })).toBeDisabled();
});
