import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

const COOKIE = "access_token=test-session-token";

vi.mock("next/headers", () => ({
  headers: async () => new Headers({ cookie: COOKIE }),
}));

const REPO = {
  id: "3f1a8c2e-0b44-4d19-9a7e-2c5f6b8d1e30",
  repo_number: 7,
  name: "sample-project",
  status: "ready",
  primary_language: "python",
  architecture_summary: "A tiny service.",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("getRepositories", () => {
  it("returns the list", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository`, () => HttpResponse.json([REPO])),
    );
    const { getRepositories } = await import("@/api/repository");

    await expect(getRepositories()).resolves.toEqual([REPO]);
  });

  it("requests the collection without a trailing slash", async () => {
    // The backend mounts `POST/GET` on `""` under the `/api/v1/repository` prefix, so a
    // trailing slash is a 307 at best and a 404 at worst depending on the client.
    let path = "";
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository`, ({ request }) => {
        path = new URL(request.url).pathname;
        return HttpResponse.json([]);
      }),
    );
    const { getRepositories } = await import("@/api/repository");

    await getRepositories();

    expect(path).toBe("/api/v1/repository");
  });

  it("forwards the cookie", async () => {
    let cookie: string | null = null;
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository`, ({ request }) => {
        cookie = request.headers.get("cookie");
        return HttpResponse.json([]);
      }),
    );
    const { getRepositories } = await import("@/api/repository");

    await getRepositories();

    expect(cookie).toBe(COOKIE);
  });

  it("returns an empty array rather than throwing for a new account", async () => {
    server.use(http.get(`${BACKEND_URL}/api/v1/repository`, () => HttpResponse.json([])));
    const { getRepositories } = await import("@/api/repository");

    await expect(getRepositories()).resolves.toEqual([]);
  });

  it("throws on a failure", async () => {
    server.use(http.get(`${BACKEND_URL}/api/v1/repository`, () => new HttpResponse(null, { status: 500 })));
    const { getRepositories } = await import("@/api/repository");

    await expect(getRepositories()).rejects.toThrow("Failed to fetch repositories");
  });
});

describe("GetRepository", () => {
  it("returns the repository", async () => {
    server.use(http.get(`${BACKEND_URL}/api/v1/repository/7`, () => HttpResponse.json(REPO)));
    const { GetRepository } = await import("@/api/repository");

    await expect(GetRepository(7)).resolves.toEqual(REPO);
  });

  it("addresses the repository by its number, not its uuid", async () => {
    // The route is keyed on the user-scoped integer. Passing the UUID here would 422, and
    // the mistake is easy to make because every other client uses the UUID.
    let path = "";
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/:id`, ({ request }) => {
        path = new URL(request.url).pathname;
        return HttpResponse.json(REPO);
      }),
    );
    const { GetRepository } = await import("@/api/repository");

    await GetRepository(7);

    expect(path).toBe("/api/v1/repository/7");
  });

  it("includes the status in the error so a caller can tell 404 from 500", async () => {
    server.use(http.get(`${BACKEND_URL}/api/v1/repository/7`, () => new HttpResponse(null, { status: 404 })));
    const { GetRepository } = await import("@/api/repository");

    await expect(GetRepository(7)).rejects.toThrow("Repository not found: 404");
  });
});
