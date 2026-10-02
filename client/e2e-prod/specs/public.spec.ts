import { expect, test } from "@playwright/test";

import { SMOKE_API_URL } from "../env";

/**
 * What is checkable without a session.
 *
 * This project has no dependencies, so it still runs when signing in breaks -- which is
 * exactly when you most want to know whether the site is up at all.
 */

test.describe("the deployed site", () => {
  test("serves the homepage", async ({ page }) => {
    const response = await page.goto("/");

    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    // A server component that threw produces Next's error page, which can still return
    // 200, so the status alone would not catch it.
    await expect(page.getByText(/Application error|Internal Server Error/i)).toHaveCount(0);
    expect(response?.status()).toBe(200);
  });

  test("renders its not-found page for an unknown route", async ({ page }) => {
    const response = await page.goto("/definitely-not-a-route");

    expect(response?.status()).toBe(404);
  });

  test("renders the contact form, without submitting it", async ({ page }) => {
    const response = await page.goto("/contact");

    expect(response?.status()).toBe(200);
    // Rendered, never submitted: a submit is a live send through Resend, and whether the
    // mail actually arrives is not something this suite can observe.
    await expect(page.getByRole("button", { name: /Send message/i })).toBeVisible();
  });
});

test.describe("the auth gate", () => {
  test("redirects an anonymous visitor away from the dashboard", async ({ page }) => {
    await page.goto("/dashboard");

    await expect(page).toHaveURL(/\/login/);
  });

  test("offers GitHub sign-in and no password route", async ({ page }) => {
    await page.goto("/login");

    await expect(page.getByRole("button", { name: /Continue with GitHub/i })).toBeVisible();
    await expect(page.locator('input[type="password"]')).toHaveCount(0);
  });

  test("points sign-in at the deployed API", async ({ page }) => {
    // The config-wiring check for the whole suite: `NEXT_PUBLIC_BACKEND_URL` is inlined
    // when the client is built, so a stale or wrong build is visible here and nowhere else
    // until an authenticated spec fails for a reason that looks like a cookie problem.
    await page.goto("/login");

    const button = page.getByRole("button", { name: /Continue with GitHub/i });
    const navigated = page.waitForRequest(
      (request) => request.url().includes("/api/v1/auth/github"),
      { timeout: 5000 },
    );
    await button.click();

    expect((await navigated).url()).toContain(`${SMOKE_API_URL}/api/v1/auth/github`);
  });
});

test.describe("the deployed API", () => {
  test("reports its dependencies as healthy", async ({ request }) => {
    const response = await request.get(`${SMOKE_API_URL}/healthz`);

    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.status).toBe("ok");
    // The point of probing this rather than just hitting the API: it is the only check
    // that separates "the application is serving" from "Postgres and Redis are reachable
    // from inside the container".
    expect(body.checks).toEqual({ database: "ok", redis: "ok" });
  });

  test("refuses an unauthenticated request", async ({ request }) => {
    const response = await request.get(`${SMOKE_API_URL}/api/v1/repository`);

    expect(response.status()).toBe(401);
  });

  test("is reachable from the page's own origin", async ({ page }) => {
    // The browser-enforced half of the CORS story. The `request` fixture above is a
    // server-side client and simply does not apply CORS, so it would pass just as happily
    // with `FRONTEND_URL` pointing somewhere else entirely.
    await page.goto("/");

    const result = await page.evaluate(
      async (url: string) => {
        try {
          const response = await fetch(url, { credentials: "include" });
          return { ok: response.ok, failure: undefined as string | undefined };
        } catch (error) {
          // A blocked cross-origin request rejects the fetch rather than resolving, so
          // this branch is what a stale allow-list looks like from inside the page.
          return { ok: false, failure: String(error) };
        }
      },
      `${SMOKE_API_URL}/healthz`,
    );

    expect(result.failure, `cross-origin fetch failed: ${result.failure}`).toBeUndefined();
    expect(result.ok).toBe(true);
  });
});
