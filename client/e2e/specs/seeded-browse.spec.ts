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
 * `repo/[id]/loading.tsx` renders placeholder blocks with no heading, so the page's
 * level-one heading (the repository's name) appears only once the server component has
 * resolved -- a real wait, not a sleep.
 */
async function settle(page: import("@playwright/test").Page) {
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
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

    // Scope the card by its role rather than by a wrapper div. A `div` filter matches
    // every ancestor that contains the name, so `.first()` resolves to the grid holding
    // *all* cards. Each card is one `<article>` holding a link named after the repository.
    const card = page
      .getByRole("article")
      .filter({ has: page.getByRole("link", { name: repo.name }) });
    await expect(card.getByText("Ready", { exact: true })).toBeVisible();
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

    // Text rather than accessible name: the last segment is a separately styled span,
    // and Chromium puts a space at that boundary when it computes the name.
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(repo.name);
  });

  test("reports the processing status", async ({ page }) => {
    await page.goto(home);
    await settle(page);

    await expect(page.getByText("Ready", { exact: true }).first()).toBeVisible();
  });

  test("renders the architecture summary", async ({ page }) => {
    // The "Architecture brief" card reads `Repository.architecture_summary`, not the
    // guide's `architecture_brief` -- two fields with similar names, of which only the
    // first reaches this card. The seed sets both, so this is checking the one that is
    // actually rendered.
    await page.goto(home);

    const brief = page.getByRole("region", { name: "Architecture brief" });
    await expect(brief).toBeVisible();
    await expect(brief.getByText(/A small fixture repository used by the end-to-end/)).toBeVisible();
  });

  test("links to the chat page instead of embedding the chat", async ({ page }) => {
    await page.goto(home);

    await expect(page.getByRole("heading", { name: /Chat with Codebase/i })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Chat", exact: true })).toHaveAttribute(
      "href",
      `${home}/chat`,
    );
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
    // Scoped to the tree: the explorer also lists files by path outside it.
    const tree = page.getByRole("navigation", { name: "Files" });
    const src = tree.getByRole("button", { name: "src", exact: true });
    await expect(tree.getByText("module_0.py")).toBeVisible();

    await src.click();
    await expect(tree.getByText("module_0.py")).toHaveCount(0);

    await src.click();
    await expect(tree.getByText("module_0.py")).toBeVisible();
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
      page.getByText(/No terms match/i),
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
    // The graph's own `<main>` sits inside the repository layout's, and only the WebGL
    // canvas lives there; the starfield and the background graph are canvases too.
    const canvas = page.locator("main main canvas").first();
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
    await expect(page.getByText(/[\d,]+ files · [\d,]+ edges/)).toBeVisible();

    expect(await distinctCanvasColours(page)).toBeGreaterThan(50);
  });

  test("switches between file and symbol level", async ({ page }) => {
    await page.goto(`${home}/graph`);
    const level = page.getByRole("group", { name: "Level" });
    await expect(level.getByRole("button", { name: "Symbols" })).toBeVisible();

    await level.getByRole("button", { name: "Symbols" }).click();

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
    // The next arrow is enabled before the order is walked, and its handler resolves
    // `(null ?? -1) + 1` to 0 -- the first step.
    await page.goto(`${home}/graph`);
    await expect(page.getByText("Reading order tour")).toBeVisible();
    await expect(page.getByText(/— \/ 2/)).toBeVisible();

    await page.getByRole("button", { name: "Next file" }).click();

    // The counter is one-based, and the annotation for that file shows both in the tour
    // panel and in the inspector the selection opens.
    await expect(page.getByText(/1 \/ 2/)).toBeVisible();
    await expect(page.getByText("Start here.", { exact: true })).toBeVisible();
    await expect(page.locator("p").filter({ hasText: "Start here." })).toBeVisible();
  });

  test("filters nodes by search", async ({ page }) => {
    await page.goto(`${home}/graph`);
    const search = page.getByRole("searchbox", { name: "Search files" });
    await expect(search).toBeVisible();

    await search.fill("module_0");

    // A match count appears under the box once there is a query.
    await expect(page.getByRole("status").filter({ hasText: /\d+ match/ })).toBeVisible();
  });
});
