import { expect, test } from "@playwright/test";

import { readSeed } from "../fixtures";

/**
 * Proves the stack is wired up at all, before any spec that asserts behaviour.
 *
 * If these fail, nothing else in the suite means anything: every other failure would be
 * downstream of a server that is not serving, a build that is stale, or an API that
 * cannot reach its database.
 */

test.describe("the homepage", () => {
  test("renders a heading", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  });

  test("is not the framework error screen", async ({ page }) => {
    // A server component that threw produces Next's default error page, which still
    // returns 200 in some configurations. Asserting on the absence of its copy is what
    // catches that.
    const response = await page.goto("/");
    await expect(page.getByText(/Application error|Internal Server Error/i)).toHaveCount(0);
    expect(response?.status()).toBe(200);
  });
});

test.describe("the API", () => {
  test("answers its health check", async ({ request }) => {
    const seed = readSeed();

    const response = await request.get(`${seed.base_url}/healthz`);

    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({ status: "ok" });
  });
});

test.describe("a route that does not exist", () => {
  test("renders the not-found page", async ({ page }) => {
    // Deliberately a path that no dynamic segment can swallow, so this is Next's 404
    // rather than a repository lookup for a repository called "no-such-page".
    const response = await page.goto("/definitely-not-a-route");

    expect(response?.status()).toBe(404);
  });
});
