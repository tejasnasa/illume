import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

const COOKIE = "access_token=test-session-token";

vi.mock("next/headers", () => ({
  headers: async () => new Headers({ cookie: COOKIE }),
}));

const REPO_ID = "3f1a8c2e-0b44-4d19-9a7e-2c5f6b8d1e30";

const PAGE = {
  entries: [
    { id: "1", name: "Cache", definition: "Stores values.", file_path: "a.py", line_number: 1, symbol_id: null },
  ],
  total: 1,
  page: 1,
  page_size: 50,
};

/** Records the query string of the next glossary request. */
function captureQuery() {
  const captured = { query: "" };
  server.use(
    http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/glossary`, ({ request }) => {
      captured.query = new URL(request.url).search;
      return HttpResponse.json(PAGE);
    }),
  );
  return captured;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GetGlossary", () => {
  it("returns the page", async () => {
    captureQuery();
    const { GetGlossary } = await import("@/api/glossary");

    await expect(GetGlossary(REPO_ID, 1, 50)).resolves.toEqual(PAGE);
  });

  it("sends the page and page size", async () => {
    const captured = captureQuery();
    const { GetGlossary } = await import("@/api/glossary");

    await GetGlossary(REPO_ID, 3, 25);

    expect(captured.query).toContain("page=3");
    expect(captured.query).toContain("page_size=25");
  });

  it("forwards the cookie", async () => {
    let cookie: string | null = null;
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/glossary`, ({ request }) => {
        cookie = request.headers.get("cookie");
        return HttpResponse.json(PAGE);
      }),
    );
    const { GetGlossary } = await import("@/api/glossary");

    await GetGlossary(REPO_ID, 1, 50);

    expect(cookie).toBe(COOKIE);
  });

  it("throws on a failure", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/glossary`, () =>
        new HttpResponse(null, { status: 404 }),
      ),
    );
    const { GetGlossary } = await import("@/api/glossary");

    await expect(GetGlossary(REPO_ID, 1, 50)).rejects.toThrow("Failed to fetch repo glossary");
  });
});

/**
 * `GetGlossarySearchResults` has no caller anywhere in `client/src`, and it addresses the
 * browse endpoint rather than the search one -- the backend's `q` parameter lives on
 * `/glossary/search`, so `/glossary?q=...` returns the unfiltered list.
 *
 * These tests pin both facts. They exist so the function cannot quietly acquire a caller
 * and start returning wrong results, and so the shape of the fix is obvious when someone
 * wires it up; nothing calls it today.
 */
describe("GetGlossarySearchResults (unreachable and misaddressed)", () => {
  it("requests /glossary, not /glossary/search", async () => {
    let path = "";
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/glossary`, ({ request }) => {
        path = new URL(request.url).pathname;
        return HttpResponse.json(PAGE);
      }),
    );
    const { GetGlossarySearchResults } = await import("@/api/glossary");

    await GetGlossarySearchResults(REPO_ID, "cache", 1, 20);

    expect(path).toBe(`/api/v1/repository/${REPO_ID}/glossary`);
    expect(path).not.toContain("/search");
  });

  it("returns whatever the browse endpoint gives it, ignoring the query", async () => {
    // The backend's browse handler takes no `q`, so an unknown parameter is dropped by
    // FastAPI and the full unfiltered page comes back. Verified here rather than assumed.
    const unfiltered = { ...PAGE, total: 99 };
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/glossary`, () =>
        HttpResponse.json(unfiltered),
      ),
    );
    const { GetGlossarySearchResults } = await import("@/api/glossary");

    await expect(GetGlossarySearchResults(REPO_ID, "nothing-matches-this", 1, 20)).resolves.toEqual(
      unfiltered,
    );
  });

  it("encodes the search term", async () => {
    const captured = captureQuery();
    const { GetGlossarySearchResults } = await import("@/api/glossary");

    await GetGlossarySearchResults(REPO_ID, "a b&c=d", 1, 20);

    expect(captured.query).toContain(`q=${encodeURIComponent("a b&c=d")}`);
  });
});
