import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

const COOKIE = "access_token=test-session-token";

vi.mock("next/headers", () => ({
  headers: async () => new Headers({ cookie: COOKIE }),
}));

const REPO_ID = "3f1a8c2e-0b44-4d19-9a7e-2c5f6b8d1e30";

const OWNERSHIP = {
  files: [
    {
      file_id: "1",
      file_path: "src/a.py",
      primary_owner: "Ada Lovelace",
      contributors: [{ name: "Ada Lovelace", email: "ada@example.com", percentage: 100, last_commit: "2026-01-01" }],
      bus_factor: 1,
      is_knowledge_silo: false,
    },
  ],
  total: 1,
};

const SILOS = { silos: [], total: 0 };

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GetOwnership", () => {
  it("returns the page", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/ownership`, () =>
        HttpResponse.json(OWNERSHIP),
      ),
    );
    const { GetOwnership } = await import("@/api/ownership");

    await expect(GetOwnership(REPO_ID, 1, 50)).resolves.toEqual(OWNERSHIP);
  });

  it("sends pagination and omits the file filter when absent", async () => {
    let query = "";
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/ownership`, ({ request }) => {
        query = new URL(request.url).search;
        return HttpResponse.json(OWNERSHIP);
      }),
    );
    const { GetOwnership } = await import("@/api/ownership");

    await GetOwnership(REPO_ID, 2, 25);

    expect(query).toContain("page=2");
    expect(query).toContain("page_size=25");
    expect(query).not.toContain("file_path");
  });

  it("encodes the file filter when given", async () => {
    // A real path contains a slash, and a query string built without encoding it would
    // still work by luck -- but a path with a space or an ampersand would not.
    let query = "";
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/ownership`, ({ request }) => {
        query = new URL(request.url).search;
        return HttpResponse.json(OWNERSHIP);
      }),
    );
    const { GetOwnership } = await import("@/api/ownership");

    await GetOwnership(REPO_ID, 1, 50, "src/my file&x.py");

    expect(query).toContain(`file_path=${encodeURIComponent("src/my file&x.py")}`);
  });

  it("forwards the cookie", async () => {
    let cookie: string | null = null;
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/ownership`, ({ request }) => {
        cookie = request.headers.get("cookie");
        return HttpResponse.json(OWNERSHIP);
      }),
    );
    const { GetOwnership } = await import("@/api/ownership");

    await GetOwnership(REPO_ID, 1, 50);

    expect(cookie).toBe(COOKIE);
  });

  it("throws on a failure", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/ownership`, () =>
        new HttpResponse(null, { status: 404 }),
      ),
    );
    const { GetOwnership } = await import("@/api/ownership");

    await expect(GetOwnership(REPO_ID, 1, 50)).rejects.toThrow("Failed to fetch repo ownership");
  });
});

describe("GetOwnershipSilos", () => {
  it("returns the silos", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/ownership/silos`, () =>
        HttpResponse.json(SILOS),
      ),
    );
    const { GetOwnershipSilos } = await import("@/api/ownership");

    await expect(GetOwnershipSilos(REPO_ID, 1, 50)).resolves.toEqual(SILOS);
  });

  it("addresses the silos route rather than the map", async () => {
    let path = "";
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/ownership/silos`, ({ request }) => {
        path = new URL(request.url).pathname;
        return HttpResponse.json(SILOS);
      }),
    );
    const { GetOwnershipSilos } = await import("@/api/ownership");

    await GetOwnershipSilos(REPO_ID, 1, 50);

    expect(path).toBe(`/api/v1/repository/${REPO_ID}/ownership/silos`);
  });

  it("sends pagination even though the endpoint ignores it", async () => {
    // The backend's silos handler takes no page parameters and returns every silo. The
    // client still sends them; harmless today, and worth knowing if the endpoint ever
    // gains paging, since the two would then agree without a client change.
    let query = "";
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/ownership/silos`, ({ request }) => {
        query = new URL(request.url).search;
        return HttpResponse.json(SILOS);
      }),
    );
    const { GetOwnershipSilos } = await import("@/api/ownership");

    await GetOwnershipSilos(REPO_ID, 3, 10);

    expect(query).toContain("page=3");
    expect(query).toContain("page_size=10");
  });

  it("throws on a failure", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/ownership/silos`, () =>
        new HttpResponse(null, { status: 500 }),
      ),
    );
    const { GetOwnershipSilos } = await import("@/api/ownership");

    await expect(GetOwnershipSilos(REPO_ID, 1, 50)).rejects.toThrow("Failed to fetch repo ownership");
  });
});
