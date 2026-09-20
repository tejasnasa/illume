import { expect, test } from "@playwright/test";

import { readSeed } from "../fixtures";

/**
 * The auth gate, and what the login route actually offers.
 *
 * This spec does **not** test a credential login, because there is not one to test: the
 * login route renders a single "Continue with GitHub" button and no email or password
 * fields, and no `/signup` route exists. That is asserted here rather than assumed, so
 * the day a credential form is added this file fails and has to be updated.
 *
 * The signed-in side of the gate is covered by every other spec, all of which run with a
 * stored session.
 */

test.describe("an unauthenticated visitor", () => {
  // A context with no storage state, rather than clearing cookies on the shared one --
  // the shared context is reused across tests in this file.
  test.use({ storageState: { cookies: [], origins: [] } });

  test("is redirected away from the dashboard", async ({ page }) => {
    await page.goto("/dashboard");

    await expect(page).toHaveURL(/\/login/);
  });

  test("is redirected away from a repository", async ({ page }) => {
    const seed = readSeed();
    const repo = seed.repos[0];

    await page.goto(`/repo/${repo.repo_num}`);

    await expect(page).toHaveURL(/\/login/);
  });

  test("is redirected away from a nested repository route", async ({ page }) => {
    // The gate matches by prefix, so a sub-route is a separate case worth pinning.
    const seed = readSeed();
    const repo = seed.repos[0];

    await page.goto(`/repo/${repo.repo_num}/graph`);

    await expect(page).toHaveURL(/\/login/);
  });

  test("can still read the homepage", async ({ page }) => {
    const response = await page.goto("/");

    expect(response?.status()).toBe(200);
    await expect(page).not.toHaveURL(/\/login/);
  });
});

test.describe("the login route", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("offers GitHub and nothing else", async ({ page }) => {
    // The finding, pinned. `LoginForm` has no credential fields and no other route
    // offers them, so password sign-in is unreachable from the UI even though
    // `POST /api/v1/auth/login` works and `useLoginForm` implements the validation for
    // a form that is never rendered.
    await page.goto("/login");

    await expect(page.getByRole("button", { name: /Continue with GitHub/i })).toBeVisible();
    await expect(page.locator('input[type="email"]')).toHaveCount(0);
    await expect(page.locator('input[type="password"]')).toHaveCount(0);
  });

  test("sends the browser to the backend OAuth start URL", async ({ page }) => {
    // Asserted on the href the handler builds rather than by clicking: clicking would
    // leave the origin for github.com and make the test depend on a third party.
    const seed = readSeed();
    await page.goto("/login");

    const button = page.getByRole("button", { name: /Continue with GitHub/i });
    await expect(button).toBeVisible();

    // The click assigns `window.location.href`; intercept the navigation instead of
    // following it so the assertion is about the URL, not about GitHub being reachable.
    const navigated = page.waitForRequest(
      (request) => request.url().includes("/api/v1/auth/github"),
      { timeout: 5000 },
    );
    await button.click();

    expect((await navigated).url()).toContain(`${seed.base_url}/api/v1/auth/github`);
  });

  test("has no signup route to fall back on", async ({ page }) => {
    // `/signup` is the obvious thing to try for a new account; `SignupForm` exists but
    // nothing mounts it, so the route 404s.
    const response = await page.goto("/signup");

    expect(response?.status()).toBe(404);
  });
});

test.describe("a signed-in user", () => {
  test("reaches the dashboard", async ({ page }) => {
    await page.goto("/dashboard");

    await expect(page).toHaveURL(/\/dashboard/);
  });

  test("is sent to login after logging out", async ({ page }) => {
    // Logout sits behind the navbar's options menu, whose trigger is the avatar image,
    // so the menu has to be opened first. That the item is reachable at all is part of
    // what this asserts.
    await page.goto("/dashboard");

    // The dashboard renders a Suspense fallback while its async server component
    // resolves. The fallback itself must not render <Navbar /> (it does not), but
    // the swap is not synchronised with goto returning, so wait for exactly one
    // avatar before clicking -- Playwright's getByAltText runs in strict mode.
    await expect(page.getByAltText("User Avatar")).toHaveCount(1);
    await page.getByAltText("User Avatar").click();
    await page.getByRole("button", { name: "Logout" }).click();

    await expect(page).toHaveURL(/\/login/);

    // And the session is genuinely gone, not just this navigation.
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });
});
