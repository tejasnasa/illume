/**
 * Tests for the explorer screen.
 *
 * The screen is the one place where the tree, the detail card and the
 * ownership panel meet, so the tests here are about the seams between
 * them: the tree has to arrive before anything can be selected, selecting
 * a file has to bring up its details, and each of the three has to be able
 * to say that it has nothing yet.
 */

import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";

import ExplorerScreen from "@/app/(app)/repo/[id]/explorer";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";
import type Repository from "@/types/repository";

/** The route parameters the stubbed router reports. */
const mockParams: Record<string, string> = { id: "42" };

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
    dismissTo: noop,
  };
  return {
    __esModule: true,
    default: routerObj,
    router: routerObj,
    useRouter: () => routerObj,
    useGlobalSearchParams: () => mockParams,
    useSegments: () => ["repo", "42"],
    usePathname: () => "/repo/42/explorer",
    Stack: ((p: { children?: unknown }) => p.children) as unknown as object,
    Redirect: (() => null) as unknown as object,
  };
});

/**
 * Build a JSON response.
 *
 * @param body - The payload.
 * @param status - The HTTP status.
 * @returns The response.
 */
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** The repository the backend answers with. */
const REPO: Repository = {
  id: "repo-1",
  github_url: "https://github.com/example/foo",
  name: "foo",
  status: "ready",
  architecture_summary: "A repository.",
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
  created_at: new Date("2026-01-15T12:00:00Z"),
  updated_at: new Date("2026-01-15T12:00:00Z"),
  auto_update_enabled: true,
  auto_update_interval_hours: 6,
  next_sync_at: null,
  last_synced_at: null,
  sync_status: "idle",
  last_sync_error: null,
  consecutive_sync_failures: 0,
  last_sync_summary: null,
  sync_available: false,
};

/** The file-level graph the backend answers with. */
const GRAPH = {
  nodes: [
    {
      id: "1",
      label: "app.ts",
      path: "src/app.ts",
      group: "src",
      kind: "file",
      loc: 120,
      criticality: "critical",
      criticality_score: 100,
      language: "TypeScript",
      fan_in: 12,
      fan_out: 3,
    },
    {
      id: "2",
      label: "util.ts",
      path: "src/lib/util.ts",
      group: "src/lib",
      kind: "file",
      loc: 20,
      criticality: "safe",
      criticality_score: 25,
      language: "TypeScript",
      fan_in: 1,
      fan_out: 0,
    },
    {
      id: "3",
      label: "README.md",
      path: "README.md",
      group: "",
      kind: "file",
      loc: 40,
      criticality: "safe",
      criticality_score: 25,
      language: "Markdown",
      fan_in: 0,
      fan_out: 0,
    },
  ],
  links: [],
  metadata: { total_nodes: 3, total_edges: 0, clusters: 1 },
};

/** The ownership map the backend answers with. */
const OWNERSHIP = {
  files: [
    {
      file_id: "file-1",
      file_path: "src/app.ts",
      primary_owner: "Ada",
      contributors: [
        {
          name: "Ada",
          email: "ada@example.com",
          percentage: 72.5,
          last_commit: "abc1234",
        },
        {
          name: "Grace",
          email: "grace@example.com",
          percentage: 27.5,
          last_commit: "def5678",
        },
      ],
      bus_factor: 1,
      is_knowledge_silo: true,
    },
  ],
  total: 1,
};

/**
 * The default backend: the repository, the tree and the ownership map.
 *
 * @param url - The URL the client asked for.
 * @returns The response.
 */
function defaultHandler(url: string): Response {
  if (url.includes("/api/v1/repository/repo-1/graph")) {
    return jsonResponse(GRAPH);
  }
  if (url.includes("/api/v1/repository/repo-1/ownership")) {
    return jsonResponse(OWNERSHIP);
  }
  if (url.endsWith("/api/v1/repository/42")) {
    return jsonResponse(REPO);
  }
  return new Response("not found", { status: 404 });
}

/**
 * The fetch stub the last render installed.
 *
 * The stub has to stay installed for the whole test: the tree request only
 * starts once the repository itself has resolved, and the API client reads
 * ``fetch`` from the global at call time.
 */
let stubbedFetch: typeof fetch | null = null;

/**
 * Render the explorer against a stubbed backend.
 *
 * @param handler - Decides what the backend answers with.
 * @returns The rendered screen.
 */
async function renderScreen(
  handler: (url: string) => Response | Promise<Response> = defaultHandler,
) {
  const fetchImpl = jest.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    return await handler(url);
  });

  stubbedFetch = global.fetch;
  (global as unknown as { fetch: typeof fetch }).fetch =
    fetchImpl as unknown as typeof fetch;

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return await render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 0, height: 0 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      <QueryClientProvider client={queryClient}>
        <ExplorerScreen />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

beforeEach(() => {
  __setTokenStoreImplementation({
    async getItemAsync() {
      return "valid-jwt";
    },
    async setItemAsync() {},
    async deleteItemAsync() {},
  });
});

/**
 * Let the pending notifications settle.
 *
 * React Query batches its notifications on a timer and the virtualised
 * list schedules its own cell update on one, so a query that resolves
 * after the last assertion would update the screen outside React's
 * act(). Flushing the timers inside act() keeps the run honest about
 * what it rendered.
 */
async function settle(): Promise<void> {
  await act(async () => {
    // Two turns of the clock: the first lets an in-flight request settle,
    // the second lets the notification that follows it arrive.
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

afterEach(() => {
  if (stubbedFetch) {
    (global as unknown as { fetch: typeof fetch }).fetch = stubbedFetch;
    stubbedFetch = null;
  }
});

describe("ExplorerScreen", () => {
  it("draws the repository tree", async () => {
    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByTestId("file-tree-file-src-app-ts")).toBeTruthy();
    });

    // The top level is open, so its files are on screen; a directory
    // deeper in the tree is still closed.
    expect(screen.getByTestId("file-tree-dir-src")).toBeTruthy();
    expect(screen.getByTestId("file-tree-dir-src-lib")).toBeTruthy();
    expect(screen.getByTestId("file-tree-file-readme-md")).toBeTruthy();
    expect(screen.queryByTestId("file-tree-file-src-lib-util-ts")).toBeNull();

    await settle();
  });

  it("collapses a directory when its chevron is tapped", async () => {
    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByTestId("file-tree-file-src-app-ts")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(screen.getByTestId("file-tree-dir-src"));
    });

    await waitFor(() => {
      expect(screen.queryByTestId("file-tree-file-src-app-ts")).toBeNull();
    });
    // The directory itself stays; only its children go.
    expect(screen.getByTestId("file-tree-dir-src")).toBeTruthy();

    await settle();
  });

  it("shows the details of a file that is selected", async () => {
    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByTestId("file-tree-file-src-app-ts")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(screen.getByTestId("file-tree-file-src-app-ts"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("file-detail")).toBeTruthy();
    });

    expect(screen.getByTestId("file-detail-label")).toHaveTextContent("app.ts");
    expect(screen.getByTestId("file-detail-path")).toHaveTextContent(
      "src/app.ts",
    );
    expect(screen.getByTestId("file-detail-loc")).toHaveTextContent("120");
    expect(screen.getByTestId("file-detail-fan-in")).toHaveTextContent("12");
    // The link follows the branch the repository was ingested from.
    expect(screen.getByTestId("file-detail-branch")).toHaveTextContent("main");

    await settle();
  });

  it("shows the ownership of the selected file", async () => {
    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByTestId("file-tree-file-src-app-ts")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(screen.getByTestId("file-tree-file-src-app-ts"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("ownership-primary-owner")).toHaveTextContent(
        "Ada",
      );
    });

    expect(screen.getByTestId("ownership-bus-factor")).toHaveTextContent("1");
    expect(screen.getByTestId("ownership-contributor-count")).toHaveTextContent(
      "2",
    );
    expect(screen.getByTestId("ownership-silo-badge")).toBeTruthy();
    expect(
      screen.getByTestId("ownership-contributor-percentage-0"),
    ).toHaveTextContent("72.5%");

    await settle();
  });

  it("says the tree is still loading", async () => {
    const screen = await renderScreen(
      () => new Promise<Response>(() => undefined),
    );

    expect(screen.getByTestId("file-tree-loading")).toBeTruthy();
    expect(screen.queryByTestId("file-tree-empty")).toBeNull();

    await settle();
  });

  it("says a repository with no files has nothing to browse", async () => {
    const screen = await renderScreen((url) =>
      url.includes("/api/v1/repository/repo-1/graph")
        ? jsonResponse({ nodes: [], links: [], metadata: {} })
        : defaultHandler(url),
    );

    await waitFor(() => {
      expect(screen.getByTestId("file-tree-empty")).toBeTruthy();
    });

    expect(screen.queryByTestId("file-tree-loading")).toBeNull();
    expect(screen.queryByTestId("file-tree-error")).toBeNull();

    await settle();
  });

  it("says the tree could not be loaded", async () => {
    const screen = await renderScreen((url) =>
      url.includes("/api/v1/repository/repo-1/graph")
        ? jsonResponse({ detail: "Failed to build graph" }, 500)
        : defaultHandler(url),
    );

    await waitFor(() => {
      expect(screen.getByTestId("file-tree-error")).toBeTruthy();
    });

    // The server's own reason is what the reader is shown.
    expect(screen.getByTestId("file-tree-error")).toHaveTextContent(
      "Failed to build graph",
    );
    expect(screen.queryByTestId("file-tree-empty")).toBeNull();

    await settle();
  });
});
