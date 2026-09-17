import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "../../msw/server";
import { BACKEND_URL } from "../../msw/handlers";

/**
 * `next/headers` only exists inside a Next.js request scope, so it is stubbed here with
 * the value the real `headers()` would return -- the incoming request's cookie header.
 *
 * The value is asserted on rather than merely stubbed: these are server-side clients, and
 * forwarding the cookie is the entire reason they do not set `credentials: "include"`.
 * If the forward were dropped, every server component would silently render as signed
 * out rather than failing.
 */
const COOKIE = "access_token=test-session-token";

vi.mock("next/headers", () => ({
  headers: async () => new Headers({ cookie: COOKIE }),
}));

const USER = {
  id: "3f1a8c2e-0b44-4d19-9a7e-2c5f6b8d1e30",
  email: "ada@example.com",
  name: "Ada Lovelace",
  avatar_url: null,
  github_id: null,
};

describe("GetMyData", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns the user", async () => {
    server.use(http.get(`${BACKEND_URL}/api/v1/auth/me`, () => HttpResponse.json(USER)));
    const { default: GetMyData } = await import("@/api/auth");

    await expect(GetMyData()).resolves.toEqual(USER);
  });

  it("requests the me endpoint with a GET", async () => {
    let method = "";
    server.use(
      http.get(`${BACKEND_URL}/api/v1/auth/me`, ({ request }) => {
        method = request.method;
        return HttpResponse.json(USER);
      }),
    );
    const { default: GetMyData } = await import("@/api/auth");

    await GetMyData();

    expect(method).toBe("GET");
  });

  it("forwards the incoming cookie", async () => {
    let forwarded: string | null = null;
    server.use(
      http.get(`${BACKEND_URL}/api/v1/auth/me`, ({ request }) => {
        forwarded = request.headers.get("cookie");
        return HttpResponse.json(USER);
      }),
    );
    const { default: GetMyData } = await import("@/api/auth");

    await GetMyData();

    expect(forwarded).toBe(COOKIE);
  });

  it("throws on a 401", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/auth/me`, () =>
        HttpResponse.json({ detail: "Not authenticated" }, { status: 401 }),
      ),
    );
    const { default: GetMyData } = await import("@/api/auth");

    await expect(GetMyData()).rejects.toThrow("Failed to fetch my data");
  });

  it("throws on a 500", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/auth/me`, () => new HttpResponse(null, { status: 500 })),
    );
    const { default: GetMyData } = await import("@/api/auth");

    await expect(GetMyData()).rejects.toThrow("Failed to fetch my data");
  });

  it("does not surface the backend's error text", async () => {
    // The thrown message is what a visitor to a broken page could end up seeing. The
    // backend's `detail` can name internal state, so it is deliberately not included.
    server.use(
      http.get(`${BACKEND_URL}/api/v1/auth/me`, () =>
        HttpResponse.json({ detail: "internal column users.github_access_token" }, { status: 500 }),
      ),
    );
    const { default: GetMyData } = await import("@/api/auth");

    await expect(GetMyData()).rejects.not.toThrow(/github_access_token/);
  });

  it("returns the payload as-is rather than reshaping it", async () => {
    // The server component renders these fields directly, so a renamed key would show up
    // as a blank profile rather than an error.
    const withExtras = { ...USER, unknown_field: "kept" };
    server.use(
      http.get(`${BACKEND_URL}/api/v1/auth/me`, () => HttpResponse.json(withExtras)),
    );
    const { default: GetMyData } = await import("@/api/auth");

    await expect(GetMyData()).resolves.toEqual(withExtras);
  });
});
