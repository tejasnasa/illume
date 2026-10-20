/**
 * Tests for the repository overview screen.
 *
 * The screen has two jobs: describe a repository that has been indexed,
 * and say what is happening to one that has not. Both are checked here
 * against the same fixture, so a change to the status copy or to a
 * missing field shows up as a failing assertion rather than as a screen
 * that quietly renders less than it used to.
 */

import React from "react";
import { render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";

import RepoIndexScreen from "@/app/(app)/repo/[id]/index";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";
import { AuthProvider } from "@/hooks/useAuth";
import type Repository from "@/types/repository";
import type { default as Guide } from "@/types/guide";

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
    dismissAll: noop,
    dismissTo: noop,
  };
  return {
    __esModule: true,
    default: routerObj,
    router: routerObj,
    useRouter: () => routerObj,
    useLocalSearchParams: () => mockParams,
    useSegments: () => ["repo", "42"],
    usePathname: () => "/repo/42",
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
    architecture_summary:
      "Illume clones a repository, parses every file and maps the connections between them.",
    repo_number: 42,
    primary_language: "TypeScript",
    detected_stack: {
      ci_cd: ["GitHub Actions"],
      databases: ["PostgreSQL"],
      languages: ["TypeScript", "Python"],
      frameworks: ["FastAPI", "Next.js"],
      infrastructure: ["Docker"],
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

/**
 * Build a fixture guide.
 *
 * @returns The fixture.
 */
function makeGuide(): Guide {
  return {
    repository_id: "repo-1",
    reading_order: [],
    critical_files: [
      {
        file_path: "server/app/tasks/ingest.py",
        criticality: "critical",
        reasons: ["Entry point"],
        fan_in: 12,
        change_frequency: 4,
        has_tests: true,
      },
    ],
    architecture_brief: {
      entry_points: ["app/main.py"],
      directory_summary: null,
      external_integrations: ["stripe", "openai"],
      data_flow: [],
      module_edges: [],
      key_modules: [],
      ownership_summary: {
        file_id: "repo-1",
        bus_factor: 1,
        primary_owner: "tejas",
        is_knowledge_silo: false,
      },
    },
  };
}

/**
 * Render the overview screen against a repository fixture.
 *
 * @param repo - The repository the backend should answer with.
 * @returns The rendered screen.
 */
async function renderScreen(repo: Repository) {
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
    if (url.endsWith("/api/v1/repository/42")) return json(repo);
    if (url.endsWith("/api/v1/repository/repo-1/guide"))
      return json(makeGuide());
    return new Response("not found", { status: 404 });
  });

  const originalFetch = global.fetch;
  stubbedFetch = originalFetch;
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
        <AuthProvider fetchImpl={fetchImpl as unknown as typeof fetch}>
          <RepoIndexScreen />
        </AuthProvider>
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

/**
 * The fetch stub the last render installed.
 *
 * The stub has to stay installed for the whole test, not just for the
 * render: the repository's guide and statistics are separate requests that
 * only start once the repository itself has resolved, and the API client
 * reads ``fetch`` from the global at call time.
 */
let stubbedFetch: typeof fetch | null = null;

beforeEach(() => {
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

describe("RepoIndexScreen", () => {
  it("renders the fields the web repository page shows", async () => {
    const screen = await renderScreen(makeRepo());

    await waitFor(() => {
      expect(screen.getByTestId("repo-detail")).toBeTruthy();
    });

    // Identity: the owner/name label, the branch and the short sha.
    expect(screen.getByText("example/foo")).toBeTruthy();
    expect(screen.getByText("main")).toBeTruthy();
    expect(screen.getByText("@abcdef1")).toBeTruthy();

    // The processing status.
    expect(screen.getByTestId("repo-detail-status")).toBeTruthy();

    // The architecture overview.
    expect(screen.getByText("AI Architecture Overview")).toBeTruthy();
    expect(
      screen.getByText(
        "Illume clones a repository, parses every file and maps the connections between them.",
      ),
    ).toBeTruthy();

    // The detected stack, group by group.
    expect(screen.getByText("Tech Stack Detected")).toBeTruthy();
    expect(screen.getByText("Languages")).toBeTruthy();
    expect(screen.getByText("TypeScript")).toBeTruthy();
    expect(screen.getByText("Python")).toBeTruthy();
    expect(screen.getByText("Frameworks")).toBeTruthy();
    expect(screen.getByText("FastAPI")).toBeTruthy();
    expect(screen.getByText("Databases")).toBeTruthy();
    expect(screen.getByText("PostgreSQL")).toBeTruthy();
    expect(screen.getByText("Infrastructure")).toBeTruthy();
    expect(screen.getByText("Docker")).toBeTruthy();
    expect(screen.getByText("CI/CD And Infra")).toBeTruthy();
    expect(screen.getByText("GitHub Actions")).toBeTruthy();
  });

  it("renders the external integrations from the guide", async () => {
    const screen = await renderScreen(makeRepo());

    await waitFor(() => {
      expect(screen.getByText("Stripe")).toBeTruthy();
    });

    expect(screen.getByText("External")).toBeTruthy();
    // The web client capitalises the external integration names.
    expect(screen.getByText("Openai")).toBeTruthy();
  });

  it("says a repository that no worker has claimed is queued", async () => {
    const screen = await renderScreen(makeRepo({ status: "pending" }));

    await waitFor(() => {
      expect(screen.getByTestId("repo-status-view")).toBeTruthy();
    });

    expect(screen.getByTestId("repo-status-headline")).toHaveTextContent(
      "Queued — waiting for a worker",
    );
    expect(screen.queryByTestId("repo-detail")).toBeNull();
  });

  it("names the pipeline stage an indexing repository is at", async () => {
    const screen = await renderScreen(makeRepo({ status: "parsing" }));

    await waitFor(() => {
      expect(screen.getByTestId("repo-status-headline")).toBeTruthy();
    });

    expect(screen.getByTestId("repo-status-headline")).toHaveTextContent(
      "Parse files",
    );
    // The stage list below names the pipeline the repository is walking.
    expect(screen.getAllByText("Fetch Repo").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("repo-detail")).toBeNull();
  });

  it("says a failed repository is still retrying", async () => {
    const screen = await renderScreen(makeRepo({ status: "failed" }));

    await waitFor(() => {
      expect(screen.getByTestId("repo-status-headline")).toBeTruthy();
    });

    expect(screen.getByTestId("repo-status-headline")).toHaveTextContent(
      "Failed, retrying…",
    );
    expect(screen.queryByTestId("repo-detail")).toBeNull();
  });

  it("does not ask for the guide of an unindexed repository", async () => {
    const screen = await renderScreen(makeRepo({ status: "parsing" }));

    await waitFor(() => {
      expect(screen.getByTestId("repo-status-view")).toBeTruthy();
    });

    expect(screen.queryByText("External")).toBeNull();
  });
});
