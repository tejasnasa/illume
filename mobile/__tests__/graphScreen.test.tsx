/**
 * Tests for the dependency graph screen.
 *
 * The drawing itself needs a GPU and is exercised on a device; what is
 * pinned here is the screen around it -- the controls it offers, the
 * search, and the reading-order tour -- because those are the parts a
 * reader interacts with.
 */

import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";

import GraphScreen from "@/app/(app)/repo/[id]/graph";
import { AuthProvider } from "@/hooks/useAuth";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";
import type Repository from "@/types/repository";

/** The route parameters the stubbed router reports. */
let mockParams: Record<string, string> = { id: "42" };

jest.mock("expo-router", () => {
  function noop() {
    /* router stub */
  }
  const routerObj = {
    push: noop,
    replace: noop,
    back: noop,
    navigate: noop,
    dismiss: noop,
    dismissAll: noop,
    dismissTo: noop,
  };
  return {
    __esModule: true,
    default: routerObj,
    router: routerObj,
    useRouter: () => routerObj,
    useGlobalSearchParams: () => mockParams,
    useSegments: () => ["repo", "42"],
    usePathname: () => "/repo/42/graph",
    Stack: ((p: { children?: unknown }) => p.children) as unknown as object,
    Redirect: (() => null) as unknown as object,
  };
});

/**
 * Build a fixture repository with sensible defaults.
 *
 * @param overrides - The fields the test cares about.
 * @returns The fixture.
 */
function makeRepo(overrides: Partial<Repository> = {}): Repository {
  const now = new Date("2026-01-15T12:00:00Z");
  return {
    id: "repo-1",
    github_url: "https://github.com/example/foo",
    name: "foo",
    status: "ready",
    architecture_summary: "A summary.",
    repo_number: 42,
    primary_language: "TypeScript",
    detected_stack: {
      ci_cd: [],
      databases: [],
      languages: ["TypeScript"],
      frameworks: [],
      infrastructure: [],
    },
    entry_points: null,
    ingested_branch: "main",
    ingested_commit_sha: "abcdef1234567890",
    analysis_commit_sha: null,
    created_at: now,
    updated_at: now,
    auto_update_enabled: true,
    auto_update_interval_hours: 6,
    next_sync_at: null,
    last_synced_at: null,
    sync_status: "idle",
    last_sync_error: null,
    consecutive_sync_failures: 0,
    last_sync_summary: null,
    sync_available: false,
    ...overrides,
  };
}

/** The graph the stubbed backend answers with. */
const graphPayload = {
  nodes: [
    {
      id: "a",
      label: "server.ts",
      path: "src/server.ts",
      group: "src",
      kind: "file",
      loc: 120,
      criticality: "critical",
      criticality_score: 100,
      language: "TypeScript",
      fan_in: 4,
      fan_out: 2,
    },
    {
      id: "b",
      label: "client.ts",
      path: "src/client.ts",
      group: "src",
      kind: "file",
      loc: 80,
      criticality: "safe",
      criticality_score: 25,
      language: "TypeScript",
      fan_in: 1,
      fan_out: 3,
    },
  ],
  links: [{ source: "a", target: "b", type: "imports", weight: 1 }],
  metadata: { total_nodes: 2, total_edges: 1, clusters: 1 },
};

const guidePayload = {
  repository_id: "repo-1",
  reading_order: [
    { position: 1, file_path: "src/server.ts", annotation: "start here" },
    { position: 2, file_path: "src/client.ts", annotation: "then this" },
  ],
  critical_files: [],
  architecture_brief: null,
};

/** The fetch stub the last render installed. */
let stubbedFetch: typeof fetch | null = null;

beforeEach(() => {
  mockParams = { id: "42" };
  __setTokenStoreImplementation({
    async getItemAsync() {
      return "valid-jwt";
    },
    async setItemAsync() {},
    async deleteItemAsync() {},
  });
});

afterEach(() => {
  if (stubbedFetch) {
    (global as unknown as { fetch: typeof fetch }).fetch = stubbedFetch;
    stubbedFetch = null;
  }
});

/**
 * Render the graph screen against a stubbed backend.
 *
 * @returns The rendered screen.
 */
async function renderGraph() {
  const fetchImpl = jest.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });

    if (url.endsWith("/api/v1/auth/me")) {
      return json({ id: "u1", email: "a@b", name: "Ada" });
    }
    if (url.includes("/graph")) return json(graphPayload);
    if (url.includes("/guide")) return json(guidePayload);
    if (url.endsWith("/api/v1/repository/42")) return json(makeRepo());
    return new Response("not found", { status: 404 });
  });

  const originalFetch = global.fetch;
  stubbedFetch = originalFetch;
  (global as unknown as { fetch: typeof fetch }).fetch =
    fetchImpl as unknown as typeof fetch;

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  // The layout runs in chunks and reports progress as it goes, so the
  // screen keeps re-rendering after the initial one. Holding the act scope
  // open across that keeps React from warning about updates it did not
  // expect.
  let screen!: Awaited<ReturnType<typeof render>>;
  await act(async () => {
    screen = await render(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 0, height: 0 },
          insets: { top: 0, left: 0, right: 0, bottom: 0 },
        }}
      >
        <QueryClientProvider client={queryClient}>
          <AuthProvider fetchImpl={fetchImpl as unknown as typeof fetch}>
            <GraphScreen />
          </AuthProvider>
        </QueryClientProvider>
      </SafeAreaProvider>,
    );

    await new Promise((resolve) => setTimeout(resolve, 200));
  });

  return screen;
}

describe("GraphScreen", () => {
  it("offers both levels of the graph", async () => {
    const screen = await renderGraph();

    await waitFor(() => {
      expect(screen.getByTestId("graph-level-file")).toBeTruthy();
    });
    expect(screen.getByTestId("graph-level-symbol")).toBeTruthy();
  });

  it("lays the graph out and draws it", async () => {
    const screen = await renderGraph();

    await waitFor(
      () => {
        expect(screen.getByTestId("graph-renderer")).toBeTruthy();
      },
      { timeout: 10_000 },
    );
  });

  it("offers a search box", async () => {
    const screen = await renderGraph();

    await waitFor(() => {
      expect(screen.getByTestId("graph-search")).toBeTruthy();
    });
  });

  it("walks the reading order", async () => {
    const screen = await renderGraph();

    await waitFor(() => {
      expect(screen.getByTestId("graph-tour-next")).toBeTruthy();
    });

    expect(screen.getByTestId("graph-tour-previous")).toBeTruthy();

    fireEvent.press(screen.getByTestId("graph-tour-next"));

    await waitFor(() => {
      expect(screen.getByTestId("graph-inspector")).toBeTruthy();
    });
    expect(screen.getByTestId("graph-inspector-label")).toHaveTextContent(
      "server.ts",
    );
  });
});
