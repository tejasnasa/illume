import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Page, type Route } from "@playwright/test";

import { CLIENT_URL, serverEnv } from "../env";
import { PRIMARY_REPO_NAME, readSeed, repoNamed, type SeededRepo } from "../fixtures";

/**
 * The repository chat, end to end.
 *
 * Two paths are covered, for different reasons:
 *
 * - **Classic through the real stream route.** The seeded user is on the free tier, so
 *   the picker starts on Classic and the question goes through `POST /chat/stream`, the
 *   retrieval pipeline against real pgvector, and out to `scripts/openai_stub_server.py`
 *   for the answer. Nothing about the text is asserted beyond the stub's fixed sentence.
 * - **Deep agent through a scripted stream.** An agent run needs a model that can call
 *   tools, and a key's requests go to its provider's own base URL, which the stub cannot
 *   stand in for. The account is given a key flag in the database so the preset is
 *   selectable, and the browser's request to the stream route is answered with a scripted
 *   event stream. That exercises the real page, picker, parser, reducer and activity block.
 *
 * Turns accumulate within a run, and none are cleaned up, so assertions use `.last()` or
 * the presence of specific text rather than counts.
 */

/** Resolved in `beforeEach`: the seed artifact does not exist while specs are collected. */
let repo: SeededRepo;
let home: string;
let chat: string;

test.beforeEach(() => {
  repo = repoNamed(readSeed(), PRIMARY_REPO_NAME);
  home = `/repo/${repo.repo_num}`;
  chat = `${home}/chat`;
});

function composer(page: Page) {
  return page.getByRole("textbox", { name: /Ask about the codebase/ });
}

async function send(page: Page, question: string) {
  await composer(page).fill(question);
  await page.getByRole("button", { name: "Send" }).click();
}

/** Opens the chat the way a user does: from the navbar. */
async function openFromNavbar(page: Page) {
  await page.goto(home);
  await page.getByRole("link", { name: "Chat", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${chat}$`));
  await expect(composer(page)).toBeVisible();
}

/**
 * Flips the "has an API key" and "model can call tools" flags on the seeded account, which
 * is what the picker reads to enable the agent presets. The key itself is a placeholder:
 * nothing in these specs sends it anywhere.
 */
function setAgentCapable(enabled: boolean) {
  const seed = readSeed();
  const code = [
    "import os, psycopg2",
    "c = psycopg2.connect(os.environ['SYNC_DATABASE_URL'])",
    "cur = c.cursor()",
    enabled
      ? "cur.execute(\"update users set ai_provider='openai', ai_model='gpt-4o-mini', ai_api_key='e2e-placeholder', ai_supports_tools=true where email=%s\", (os.environ['E2E_EMAIL'],))"
      : "cur.execute(\"update users set ai_provider=null, ai_model=null, ai_api_key=null, ai_supports_tools=null where email=%s\", (os.environ['E2E_EMAIL'],))",
    "c.commit()",
  ].join("\n");
  execFileSync(process.platform === "win32" ? "uv.exe" : "uv", ["run", "python", "-c", code], {
    cwd: path.resolve(__dirname, "../../../server"),
    stdio: "inherit",
    env: { ...process.env, ...serverEnv, E2E_EMAIL: seed.email },
  });
}

test.describe("opening the chat", () => {
  test("is a link in the navbar and no longer part of the home page", async ({ page }) => {
    await page.goto(home);
    await expect(page.getByRole("heading", { name: /Chat with Codebase/i })).toHaveCount(0);
    await openFromNavbar(page);
  });

  test("marks Chat as the current page", async ({ page }) => {
    await page.goto(chat);
    await expect(page.getByRole("link", { name: "Chat", exact: true })).toHaveClass(/font-semibold/);
  });
});

test.describe("history", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(chat);
  });

  test("loads the persisted turn and its answer", async ({ page }) => {
    await expect(page.getByText("What does func_0 do?").last()).toBeVisible();
    await expect(page.getByText(/the first function in the fixture/).last()).toBeVisible();
  });

  test("offers a clear action once a turn exists", async ({ page }) => {
    await page.getByRole("button", { name: "Chat options" }).click();
    await expect(page.getByRole("menuitem", { name: /Clear chat history/ })).toBeVisible();
  });
});

test.describe("asking a question (Classic, real backend)", () => {
  test("shows the activity block, the answer and its sources", async ({ page }) => {
    await openFromNavbar(page);
    await send(page, "What does func_0 do?");

    await expect(page.getByText("What does func_0 do?").last()).toBeVisible();
    await expect(page.getByText(/Based on the indexed sources/).last()).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByTestId("activity-block").last()).toBeVisible();
    await expect(page.getByRole("region", { name: "Sources cited" }).last()).toBeVisible();
  });

  test("clears the composer after sending and keeps the turn across a reload", async ({ page }) => {
    await page.goto(chat);
    await send(page, "Does this survive a refresh?");
    await expect(composer(page)).toHaveValue("");
    await expect(page.getByText(/Based on the indexed sources/).last()).toBeVisible({
      timeout: 30_000,
    });
    // The turn is saved when the run ends, not while its text streams in, so wait for
    // the run to settle (its figures then show under the answer) before reloading.
    await expect(page.getByTestId("turn").last().getByTestId("run-stats")).toBeVisible();

    await page.reload();
    await expect(page.getByText("Does this survive a refresh?").last()).toBeVisible();
  });

  test("keeps Send disabled for an empty question", async ({ page }) => {
    await page.goto(chat);
    await expect(page.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  test("disables the agent presets on the free tier", async ({ page }) => {
    await page.goto(chat);
    await page.getByTestId("preset-label").click();
    await expect(page.getByRole("menuitemradio", { name: /^Deep agent(?! \+)/ })).toBeDisabled();
    await expect(page.getByRole("menuitemradio", { name: /^Classic/ })).toBeEnabled();
  });
});

/** Events a Deep agent run would stream, in order. */
function scriptedRun(runId: string): string {
  const base = { run_id: runId, worker_id: null };
  let seq = 0;
  const frame = (type: string, data: Record<string, unknown>) => {
    seq += 1;
    const event = { seq, ts: new Date().toISOString(), type, data, ...base };
    return `event: ${type}\ndata: ${JSON.stringify(event)}\n\n`;
  };
  return [
    frame("run_started", {
      preset: "deep_agent",
      config_hash: "e2e",
      model: "scripted",
      execution: "agent",
    }),
    frame("tool_call", {
      call_id: "c1",
      tool: "grep_code",
      arguments: JSON.stringify({ pattern: "func_0" }),
    }),
    frame("tool_result", { call_id: "c1", tool: "grep_code", status: "ok", result_count: 1, latency_ms: 18 }),
    frame("nodes", { call_id: "c1", tool: "grep_code", paths: ["src/module_0.py"] }),
    frame("tool_call", {
      call_id: "c2",
      tool: "read_file",
      arguments: JSON.stringify({ path: "src/module_0.py", start_line: 1, end_line: 20 }),
    }),
    frame("tool_result", { call_id: "c2", tool: "read_file", status: "ok", result_count: 1, latency_ms: 31 }),
    frame("nodes", { call_id: "c2", tool: "read_file", paths: ["src/module_0.py"] }),
    frame("answer_delta", { text: "`func_0` lives in " }),
    frame("answer_delta", { text: "[F:src/module_0.py:1-3]." }),
    frame("done", {
      run_id: runId,
      answer: "`func_0` lives in [F:src/module_0.py:1-3].",
      citations: [
        {
          key: "F:src/module_0.py:1-3",
          source_type: "symbol",
          chunk_text: "def func_0(): ...",
          file_path: "src/module_0.py",
          symbol_name: "func_0",
          start_line: 1,
          end_line: 3,
        },
      ],
      unresolved: [],
      stop_reason: "finished",
      usage: { tool_calls: 2, iterations: 2, elapsed_seconds: 1.2 },
    }),
  ].join("");
}

/** Answers the stream route (and its CORS preflight) with a scripted body. */
async function scriptStream(page: Page, onRequest: (body: Record<string, unknown>) => void) {
  const cors = {
    "access-control-allow-origin": CLIENT_URL,
    "access-control-allow-credentials": "true",
    "access-control-allow-headers": "content-type, accept",
    "access-control-allow-methods": "POST, OPTIONS",
  };
  await page.route("**/chat/stream", async (route: Route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: cors });
      return;
    }
    onRequest(JSON.parse(request.postData() ?? "{}"));
    await route.fulfill({
      status: 200,
      headers: { ...cors, "content-type": "text/event-stream", "cache-control": "no-cache" },
      body: scriptedRun("00000000-0000-4000-8000-000000000001"),
    });
  });
}

test.describe("Deep agent (scripted stream)", () => {
  test.beforeAll(() => setAgentCapable(true));
  test.afterAll(() => setAgentCapable(false));

  test("runs from the navbar to an answer with an activity block and a citation", async ({
    page,
  }) => {
    let requested: Record<string, unknown> | null = null;
    await scriptStream(page, (body) => (requested = body));

    await openFromNavbar(page);
    await page.getByTestId("preset-label").click();
    await page.getByRole("menuitemradio", { name: /^Deep agent(?! \+)/ }).click();
    await expect(page.getByTestId("preset-label")).toHaveText("Deep agent");

    await send(page, "Where is func_0 defined?");

    // The steps sit inline above the answer, with the run's figures under it.
    const block = page.getByTestId("activity-block").last();
    await expect(block).toBeVisible();
    await expect(page.getByTestId("answer").last()).toContainText("func_0", { timeout: 15_000 });
    await expect(page.getByTestId("run-stats").last()).toContainText("2 tool calls");
    await expect(block.locator('[data-row="tool"]')).toHaveCount(2);
    await expect(block.getByText("func_0").first()).toBeVisible();

    // The answer: the key is a chip, not raw bracket text.
    const answer = page.getByTestId("answer").last();
    const chip = answer.getByRole("button", { name: "Source F:src/module_0.py:1-3" });
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(page.getByTestId("opened-citation").last()).toContainText("func_0");

    expect(requested).toMatchObject({ preset: "deep_agent", question: "Where is func_0 defined?" });
  });
});

test.describe("mobile viewport", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("works as a plain conversation, without the graph", async ({ page }) => {
    // Straight to the chat route: the ambient graph on other repo pages is a separate
    // thing, and this is about the page that would otherwise draw its own.
    await page.goto(chat);
    await expect(composer(page)).toBeVisible();
    await expect(page.getByTestId("graph-layer")).toHaveCount(0);
    await expect(page.locator("canvas")).toHaveCount(0);

    await send(page, "What is module_1?");
    await expect(page.getByText(/Based on the indexed sources/).last()).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByTestId("activity-block").last()).toBeVisible();
    await expect(page.locator("canvas")).toHaveCount(0);
  });
});
