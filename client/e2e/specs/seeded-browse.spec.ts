import { expect, test } from "@playwright/test";

import { PRIMARY_REPO_NAME, readSeed, repoNamed, type SeededRepo } from "../fixtures";

/**
 * Every read path the seeded repository can be browsed through.
 *
 * This is the spec that would catch a broken server component, a route that 404s, or an
 * API shape change -- the class of failure the unit suites cannot see, because they mock
 * the very boundary that would be wrong.
 *
 * The repository is inserted directly by the seed, so nothing here waits on ingestion.
 */

/**
 * Resolved in `beforeEach`, not at module scope.
 *
 * Playwright loads every spec file to build its test list **before** any project runs, so
 * a module-scope `readSeed()` throws on a clean checkout -- the `seed` project has not had
 * the chance to write the artifact yet -- and takes the whole run down during collection.
 * It only ever looked correct because `.auth/seed.json` survived from an earlier run;
 * CI always starts clean, so it would have failed every time.
 *
 * `smoke.spec.ts` and `auth.spec.ts` already read it inside the test for this reason.
 */
let repo: SeededRepo;
let home: string;

test.beforeEach(() => {
  repo = repoNamed(readSeed(), PRIMARY_REPO_NAME);
  home = `/repo/${repo.repo_num}`;
});

/**
 * Waits for the repository route to finish streaming.
 *
 * `repo/[id]/loading.tsx` renders a pulsing skeleton carrying the same "Processing Status"
 * label as the real page, so while the server component resolves, a bare locator for that
 * text matches **two** elements and Playwright raises a strict-mode violation. Waiting for
 * the count to reach one is the settled state -- a real wait, not a sleep.
 */
async function settle(page: import("@playwright/test").Page) {
  await expect(page.getByText("Processing Status")).toHaveCount(1);
}

test.describe("the dashboard", () => {
  test("lists the seeded repository", async ({ page }) => {
    await page.goto("/dashboard");

    await expect(page.getByText(repo.name).first()).toBeVisible();
  });

  test("shows it as ready", async ({ page }) => {
    // Not cosmetic: `ready` is the gate on the graph endpoint (409 otherwise) and on
    // whether the repository page renders the guide or a log stream.
    await page.goto("/dashboard");

    const card = page.locator("div").filter({ hasText: repo.name }).first();
    await expect(card.getByText("ready")).toBeVisible();
  });
});

test.describe("the repository overview", () => {
  test("renders without error", async ({ page }) => {
    const response = await page.goto(home);

    expect(response?.status()).toBe(200);
    await settle(page);
    await expect(page.getByText(/Application error/i)).toHaveCount(0);
  });

  test("names the repository", async ({ page }) => {
    await page.goto(home);

    await expect(page.getByText(repo.name).first()).toBeVisible();
  });

  test("reports the processing status", async ({ page }) => {
    await page.goto(home);
    await settle(page);

    await expect(page.getByText(/^ready$/).first()).toBeVisible();
  });

  test("renders the architecture summary", async ({ page }) => {
    // The "AI Architecture Overview" section reads `Repository.architecture_summary`, not
    // the guide's `architecture_brief` -- two fields with similar names, of which only the
    // first reaches this page. The seed sets both, so this is checking the one that is
    // actually rendered.
    await page.goto(home);

    await expect(page.getByText("AI Architecture Overview")).toBeVisible();
    await expect(page.getByText(/A small fixture repository used by the end-to-end/)).toBeVisible();
  });

  test("renders the chat panel", async ({ page }) => {
    await page.goto(home);

    await expect(page.getByRole("heading", { name: /Chat with Codebase/i })).toBeVisible();
  });
});

test.describe("the explorer", () => {
  test("renders the file tree", async ({ page }) => {
    await page.goto(`${home}/explorer`);

    await expect(page.getByRole("heading", { name: "File Explorer" })).toBeVisible();
  });

  test("lists the seeded files immediately", async ({ page }) => {
    // No expansion needed: `ExplorerClient` seeds `expandedDirs` with every top-level
    // directory, so the tree is useful on arrival. Asserting the file is visible without
    // a click is what pins that -- and the first version of this test clicked `src`
    // first, which *collapsed* the already-open directory.
    await page.goto(`${home}/explorer`);
    await expect(page.getByRole("heading", { name: "File Explorer" })).toBeVisible();

    await expect(page.getByText("module_0.py").first()).toBeVisible();
  });

  test("collapses and re-expands a directory", async ({ page }) => {
    await page.goto(`${home}/explorer`);
    const src = page.getByRole("button", { name: "src" });
    await expect(page.getByText("module_0.py").first()).toBeVisible();

    await src.click();
    await expect(page.getByText("module_0.py")).toHaveCount(0);

    await src.click();
    await expect(page.getByText("module_0.py").first()).toBeVisible();
  });

  test("opens a detail card with ownership for a selected file", async ({ page }) => {
    // Exercises the whole chain: tree click -> ownership fetch -> detail card. The
    // seeded owners are Ada Lovelace and Grace Hopper.
    await page.goto(`${home}/explorer`);
    await page.getByText("module_0.py").first().click();

    await expect(page.getByText("Ada Lovelace").first()).toBeVisible();
    await expect(page.getByText(/python/i).first()).toBeVisible();
  });
});

test.describe("the glossary", () => {
  test("lists the seeded terms", async ({ page }) => {
    await page.goto(`${home}/glossary`);

    await expect(page.getByText(/Showing \d+ of \d+ entries/)).toBeVisible();
    await expect(page.getByText("func_0").first()).toBeVisible();
  });

  test("narrows the list on a submitted search", async ({ page }) => {
    // Search runs on **submit**, not on keystroke -- `useGlossarySearch` wires it to
    // `form.handleSubmit`, with no debounce and no watcher. So `fill` alone changes
    // nothing and the assertion has to be about the result count, which the two views
    // report differently: the default view shows every seeded term, the search view shows
    // the matches.
    await page.goto(`${home}/glossary`);
    await expect(page.getByText(/Showing 4 of 4 entries/)).toBeVisible();

    const box = page.getByPlaceholder("Search definitions...");
    await box.fill("func_1");
    await box.press("Enter");

    await expect(page.getByText(/Showing 1 of 1 entries/)).toBeVisible();
    await expect(page.getByText("func_3")).toHaveCount(0);
  });

  test("reports an empty result set", async ({ page }) => {
    // The search hits `/glossary/search`; a query nothing matches must say so rather than
    // render an empty list, which is indistinguishable from a failure to load.
    await page.goto(`${home}/glossary`);

    const box = page.getByPlaceholder("Search definitions...");
    await box.fill("definitely-not-a-term");
    await box.press("Enter");

    await expect(
      page.getByText(/No glossary entries found matching your query/i),
    ).toBeVisible();
  });
});

test.describe("the dependency graph", () => {
  /**
   * Counts the distinct colours in the composited canvas.
   *
   * `toDataURL` is not usable here: three.js creates its WebGL context without
   * `preserveDrawingBuffer`, so reading the drawing buffer after the frame is composited
   * returns blank. A Playwright element screenshot captures what the compositor actually
   * put on screen, and decoding it back inside the page needs no image library.
   *
   * A blank or unrendered canvas is one or two colours; a force graph with antialiased
   * nodes, links, and text is in the hundreds. `> 50` is far above the noise floor and
   * far below a real render, so it fails only when nothing was drawn.
   */
  async function distinctCanvasColours(page: import("@playwright/test").Page) {
    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeVisible();

    const shot = await canvas.screenshot();

    return page.evaluate(async (base64) => {
      const response = await fetch(`data:image/png;base64,${base64}`);
      const bitmap = await createImageBitmap(await response.blob());
      const offscreen = new OffscreenCanvas(bitmap.width, bitmap.height);
      const context = offscreen.getContext("2d")!;
      context.drawImage(bitmap, 0, 0);

      const { data } = context.getImageData(0, 0, bitmap.width, bitmap.height);
      const seen = new Set<string>();
      for (let i = 0; i < data.length; i += 4) {
        seen.add(`${data[i]},${data[i + 1]},${data[i + 2]}`);
      }
      return seen.size;
    }, shot.toString("base64"));
  }

  test("paints the canvas", async ({ page }) => {
    // WebGL in a headless container relies on the SwiftShader flags in the config; if
    // those regress, this is the test that says so rather than a blank graph shipping.
    await page.goto(`${home}/graph`);
    await expect(page.getByText(/Size ∝ LOC/)).toBeVisible();

    expect(await distinctCanvasColours(page)).toBeGreaterThan(50);
  });

  test("switches between file and symbol level", async ({ page }) => {
    await page.goto(`${home}/graph`);
    await expect(page.getByRole("button", { name: "Symbol Level" })).toBeVisible();

    await page.getByRole("button", { name: "Symbol Level" }).click();

    // The level is a route query, so the assertion is that the navigation happened and
    // the page came back rather than erroring.
    await expect(page).toHaveURL(/level=symbol/);
    await expect(page.getByText(/Application error/i)).toHaveCount(0);
    expect(await distinctCanvasColours(page)).toBeGreaterThan(0);
  });

  test("walks the reading order and opens the inspector", async ({ page }) => {
    // The most valuable assertion on this page, because it exercises the join the whole
    // feature rests on: `guide.reading_order` holds file *paths*, the graph holds nodes,
    // and the two are matched at render time. The seeded guide names module_0 and
    // module_3, so the pager reports two steps.
    //
    // The next arrow is enabled before the order is walked (`disabled` is
    // `pageIndex !== null && ...`), and its handler resolves `(null ?? -1) + 1` to 0 --
    // the first step.
    await page.goto(`${home}/graph`);
    await expect(page.getByText("Reading Order:")).toBeVisible();
    await expect(page.getByText(/— \/ 2/)).toBeVisible();

    // Scoped to the pager's own section: the navigation bar carries buttons too, and the
    // arrows are the only unlabelled ones -- the level toggle beside them has text.
    const pager = page.locator("section").filter({ hasText: "Reading Order:" });
    await pager.getByRole("button").last().click();

    // The counter is one-based, and selecting the node renders the inspector with the
    // guide's annotation for that file.
    await expect(page.getByText(/1 \/ 2/)).toBeVisible();
    await expect(page.getByText("Start here.")).toBeVisible();
  });

  test("filters nodes by search", async ({ page }) => {
    await page.goto(`${home}/graph`);
    const search = page.getByPlaceholder("Search nodes...");
    await expect(search).toBeVisible();

    await search.fill("module_0");

    // The legend grows a match count once there is a query.
    await expect(page.getByText(/Match/)).toBeVisible();
  });
});
