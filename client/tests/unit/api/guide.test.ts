import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

const COOKIE = "access_token=test-session-token";

vi.mock("next/headers", () => ({
  headers: async () => new Headers({ cookie: COOKIE }),
}));

const REPO_ID = "3f1a8c2e-0b44-4d19-9a7e-2c5f6b8d1e30";

const GUIDE = {
  repository_id: REPO_ID,
  reading_order: [
    { position: 1, file_path: "src/a.py", annotation: "Start here.", fan_in: 7 },
  ],
  critical_files: [
    {
      file_path: "src/hot.py",
      criticality: "critical",
      reasons: ["high fan-in"],
      fan_in: 42,
      change_frequency: 9.5,
      has_tests: false,
    },
  ],
  architecture_brief: null,
  pdf_ready: false,
};

const STATS = {
  repository_id: REPO_ID,
  total_files: 3,
  total_loc: 30,
  language_breakdown: [{ language: "python", file_count: 3, loc_count: 30 }],
  total_contributors: 2,
  top_contributors: [{ name: "Ada Lovelace", files_owned: 2 }],
  knowledge_silo_count: 1,
  total_dependencies: 2,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GetGuide", () => {
  it("returns the guide", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/guide`, () => HttpResponse.json(GUIDE)),
    );
    const { GetGuide } = await import("@/api/guide");

    await expect(GetGuide(REPO_ID)).resolves.toEqual(GUIDE);
  });

  it("preserves the reading order as sent", async () => {
    // The backend sorts by position before serializing, and the page renders the array in
    // order. Re-sorting here would hide a backend regression rather than surfacing it.
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/guide`, () => HttpResponse.json(GUIDE)),
    );
    const { GetGuide } = await import("@/api/guide");

    const guide = await GetGuide(REPO_ID);

    expect(guide.reading_order.map((item) => item.position)).toEqual([1]);
  });

  it("forwards the cookie", async () => {
    let cookie: string | null = null;
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/guide`, ({ request }) => {
        cookie = request.headers.get("cookie");
        return HttpResponse.json(GUIDE);
      }),
    );
    const { GetGuide } = await import("@/api/guide");

    await GetGuide(REPO_ID);

    expect(cookie).toBe(COOKIE);
  });

  it("throws when no guide has been generated", async () => {
    // A 404 here is the ordinary "ingestion has not finished" state, not a bug.
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/guide`, () =>
        HttpResponse.json({ detail: "Onboarding guide not generated yet." }, { status: 404 }),
      ),
    );
    const { GetGuide } = await import("@/api/guide");

    await expect(GetGuide(REPO_ID)).rejects.toThrow("Failed to fetch repo guide");
  });
});

describe("GetGuideStats", () => {
  it("returns the stats", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/stats`, () => HttpResponse.json(STATS)),
    );
    const { GetGuideStats } = await import("@/api/guide");

    await expect(GetGuideStats(REPO_ID)).resolves.toEqual(STATS);
  });

  it("addresses the stats route, not the guide route", async () => {
    let path = "";
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/stats`, ({ request }) => {
        path = new URL(request.url).pathname;
        return HttpResponse.json(STATS);
      }),
    );
    const { GetGuideStats } = await import("@/api/guide");

    await GetGuideStats(REPO_ID);

    expect(path).toBe(`/api/v1/repository/${REPO_ID}/stats`);
  });

  it("keeps zero-valued totals rather than coercing them", async () => {
    // The dashboard divides by some of these; a null would render as NaN.
    const empty = { ...STATS, total_files: 0, total_loc: 0, total_dependencies: 0 };
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/stats`, () => HttpResponse.json(empty)),
    );
    const { GetGuideStats } = await import("@/api/guide");

    const stats = await GetGuideStats(REPO_ID);

    expect(stats.total_files).toBe(0);
    expect(stats.total_loc).toBe(0);
  });

  it("throws on a failure", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/stats`, () =>
        new HttpResponse(null, { status: 500 }),
      ),
    );
    const { GetGuideStats } = await import("@/api/guide");

    await expect(GetGuideStats(REPO_ID)).rejects.toThrow("Failed to fetch repo stats");
  });
});
