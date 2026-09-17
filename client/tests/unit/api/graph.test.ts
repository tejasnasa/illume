import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

const COOKIE = "access_token=test-session-token";

vi.mock("next/headers", () => ({
  headers: async () => new Headers({ cookie: COOKIE }),
}));

const REPO_ID = "3f1a8c2e-0b44-4d19-9a7e-2c5f6b8d1e30";

const GRAPH = {
  nodes: [
    {
      id: "1",
      label: "a.py",
      path: "src/a.py",
      group: "src",
      kind: "file",
      loc: 10,
      language: "python",
      fan_in: 0,
      fan_out: 1,
      criticality: "safe",
      criticality_score: 25,
    },
  ],
  links: [{ source: "1", target: "2", type: "imports", weight: 1 }],
  metadata: { total_nodes: 1, total_edges: 1, clusters: 1 },
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("getRepoGraph", () => {
  it("returns the graph", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/graph`, () => HttpResponse.json(GRAPH)),
    );
    const { getRepoGraph } = await import("@/api/graph");

    await expect(getRepoGraph(REPO_ID, "file")).resolves.toEqual(GRAPH);
  });

  it("passes the level through", async () => {
    let level: string | null = null;
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/graph`, ({ request }) => {
        level = new URL(request.url).searchParams.get("level");
        return HttpResponse.json(GRAPH);
      }),
    );
    const { getRepoGraph } = await import("@/api/graph");

    await getRepoGraph(REPO_ID, "symbol");

    expect(level).toBe("symbol");
  });

  it("requests the level it was asked for, not a default", async () => {
    // The backend defaults to `file` when `level` is absent, so a dropped parameter would
    // silently render the wrong granularity rather than erroring.
    const requested: string[] = [];
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/graph`, ({ request }) => {
        requested.push(new URL(request.url).searchParams.get("level") ?? "MISSING");
        return HttpResponse.json(GRAPH);
      }),
    );
    const { getRepoGraph } = await import("@/api/graph");

    await getRepoGraph(REPO_ID, "symbol");

    expect(requested).not.toContain("MISSING");
  });

  it("forwards the cookie", async () => {
    let cookie: string | null = null;
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/graph`, ({ request }) => {
        cookie = request.headers.get("cookie");
        return HttpResponse.json(GRAPH);
      }),
    );
    const { getRepoGraph } = await import("@/api/graph");

    await getRepoGraph(REPO_ID, "file");

    expect(cookie).toBe(COOKIE);
  });

  it("throws on a 409, which is the not-ready case", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/graph`, () =>
        HttpResponse.json({ detail: "Repository is not ready yet (status: parsing)" }, { status: 409 }),
      ),
    );
    const { getRepoGraph } = await import("@/api/graph");

    await expect(getRepoGraph(REPO_ID, "file")).rejects.toThrow("Failed to fetch repository");
  });

  it("returns an empty graph without throwing", async () => {
    // A ready repository with no files yields empty arrays and zeroed metadata; the
    // components branch on `nodes.length`, so this must not be treated as an error.
    const empty = { nodes: [], links: [], metadata: { total_nodes: 0, total_edges: 0, clusters: 0 } };
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/${REPO_ID}/graph`, () => HttpResponse.json(empty)),
    );
    const { getRepoGraph } = await import("@/api/graph");

    const graph = await getRepoGraph(REPO_ID, "file");

    expect(graph.nodes).toEqual([]);
    expect(graph.metadata.total_nodes).toBe(0);
  });
});
