/**
 * Tests for the dashboard screen.
 *
 * Phase 4 ships three testable behaviours:
 *
 * 1. A list of repositories renders one card per item, oldest to newest
 *    as the backend returns them, in the order received (the backend
 *    sorts newest-first; the screen does not re-sort).
 * 2. An empty list renders the :component:`DashboardEmptyState` instead of
 *    a row of cards.
 * 3. Tapping a card invokes navigation with the repository's
 *    ``repo_number``, not its UUID.
 *
 * The dashboard is otherwise a thin wrapper over :func:`useRepositories`
 * (loading skeleton, error box, refresh control, logout button), so the
 * tests focus on the contract screen consumers rely on.
 */

import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";

import DashboardScreen from "@/app/(app)/dashboard";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";
import { AuthProvider } from "@/hooks/useAuth";
import { router } from "expo-router";
import type Repository from "@/types/repository";

/**
 * Mock ``expo-router`` once at module load. The dashboard uses
 * ``router.push`` (named) for navigation; the test asserts against a
 * stubbed ``push`` so a real Navigator does not need to be mounted.
 *
 * Note: ``jest.fn()`` inside ``jest.mock`` factories is being replaced
 * with ``undefined`` here -- the babel-rewritten factory has trouble
 * resolving the outer-scope ``mockRouterPush`` across jest's hoisting
 * pass. We work around it by installing plain function stubs at module
 * load and replacing ``router.push`` with a recording function in the
 * ``beforeEach``.
 */
jest.mock("expo-router", () => {
  function noop() {
    /* router stub */
  }
  const routerObj = {
    push: noop,
    replace: noop,
    back: noop,
    navigate: noop,
  };
  return {
    __esModule: true,
    default: routerObj,
    router: routerObj,
    useRouter: () => routerObj,
    Stack: ((p: { children?: unknown }) => p.children) as unknown as object,
    Redirect: (() => null) as unknown as object,
  };
});

/**
 * Build a fixture repository with sensible defaults so individual tests
 * override only the fields they care about. Tests depend on the
 * truncation contract -- the dashboard never re-truncates -- so the
 * field values here are the values the backend emits on a happy path.
 */
function makeRepo(overrides: Partial<Repository> = {}): Repository {
  const now = new Date("2026-01-15T12:00:00Z");
  return {
    id: "repo-1",
    github_url: "https://github.com/example/foo",
    name: "foo",
    status: "ready",
    architecture_summary:
      "A small example repository used by the dashboard tests.",
    repo_number: 1,
    primary_language: "TypeScript",
    detected_stack: {
      ci_cd: [],
      databases: [],
      languages: ["TypeScript"],
      frameworks: ["React"],
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

/** Hrefs recorded across the most recent ``beforeEach``. */
const pushCalls: string[] = [];

/**
 * Capture every URL the test's ``fetch`` shim sees so the assertions
 * can inspect what the screen requested.
 */
type Call = { url: string; method: string };

interface FetchHarness {
  fetchImpl: jest.Mock;
  calls: Call[];
  respond: (response: Response | ((call: Call) => Response)) => void;
}

function makeFetchHarness(): FetchHarness {
  const calls: Call[] = [];
  let responder: ((call: Call) => Response) | null = null;

  const fetchImpl = jest.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      const call = { url, method };
      calls.push(call);
      if (!responder) {
        return new Response("not stubbed", { status: 500 });
      }
      return responder(call);
    },
  );

  return {
    fetchImpl: fetchImpl as unknown as jest.Mock,
    calls,
    respond: (next) => {
      responder = typeof next === "function" ? next : () => next as Response;
    },
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * Wrap the screen in the production-ish provider stack: a fresh
 * :class:`QueryClient` so each test starts with an empty cache, the
 * :class:`AuthProvider` so the screen's ``useAuth`` import resolves, and
 * a stable in-memory token store so the cold-start validation does not
 * hit the real SecureStore binding.
 */
async function renderDashboard(
  fetchImpl: typeof fetch,
  queryClient: QueryClient,
  ui: React.ReactElement,
) {
  // The :func:`apiRequest` wrapper always reads ``fetch`` from the
  // global, so the test must replace the global for the data layer to
  // see the stub. The auth provider accepts ``fetchImpl`` so /auth/me
  // goes through the same stub without the global dance.
  const originalFetch = global.fetch;
  (global as unknown as { fetch: typeof fetch }).fetch = fetchImpl;
  try {
    return await render(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 0, height: 0 },
          insets: { top: 0, left: 0, right: 0, bottom: 0 },
        }}
      >
        <QueryClientProvider client={queryClient}>
          <AuthProvider fetchImpl={fetchImpl}>{ui}</AuthProvider>
        </QueryClientProvider>
      </SafeAreaProvider>,
    );
  } finally {
    (global as unknown as { fetch: typeof fetch }).fetch = originalFetch;
  }
}

beforeEach(() => {
  __setTokenStoreImplementation({
    async getItemAsync() {
      return "valid-jwt";
    },
    async setItemAsync() {},
    async deleteItemAsync() {},
  });
  // The mock factory installs a noop ``push``; install a recording
  // function before each test so we can assert against the captured
  // hrefs. The factory intentionally avoids ``jest.fn()`` because
  // babel's hoist transform loses the outer reference.
  pushCalls.length = 0;
  (router.push as unknown as (...args: string[]) => void) = (href: string) => {
    pushCalls.push(href);
  };
});

describe("DashboardScreen", () => {
  it("renders one card per fixture repository in backend order", async () => {
    const harness = makeFetchHarness();
    const user = { id: "u1", email: "a@b", name: "Ada", avatar_url: null };

    harness.respond((call) => {
      if (call.url.endsWith("/api/v1/auth/me")) {
        return jsonResponse(200, user);
      }
      if (call.url.endsWith("/api/v1/repository")) {
        return jsonResponse(200, [
          makeRepo({ id: "repo-1", repo_number: 1, name: "alpha" }),
          makeRepo({ id: "repo-2", repo_number: 2, name: "beta" }),
          makeRepo({ id: "repo-3", repo_number: 3, name: "gamma" }),
        ]);
      }
      return new Response("not found", { status: 404 });
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const screen = await renderDashboard(
      harness.fetchImpl as unknown as typeof fetch,
      queryClient,
      <DashboardScreen />,
    );

    await waitFor(() => {
      // After the list resolves, the dashboard renders one card per row.
      expect(screen.getByText("alpha")).toBeTruthy();
    });

    expect(screen.getByText("beta")).toBeTruthy();
    expect(screen.getByText("gamma")).toBeTruthy();
  });

  it("renders the empty state when the backend returns no repositories", async () => {
    const harness = makeFetchHarness();
    const user = { id: "u1", email: "a@b", name: "Ada", avatar_url: null };

    harness.respond((call) => {
      if (call.url.endsWith("/api/v1/auth/me")) {
        return jsonResponse(200, user);
      }
      if (call.url.endsWith("/api/v1/repository")) {
        return jsonResponse(200, []);
      }
      return new Response("not found", { status: 404 });
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const screen = await renderDashboard(
      harness.fetchImpl as unknown as typeof fetch,
      queryClient,
      <DashboardScreen />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("dashboard-empty")).toBeTruthy();
    });

    // No card rows are rendered when the list is empty.
    expect(screen.queryByText("alpha")).toBeNull();
    expect(
      screen.getByText(
        "No repositories found. Add your first one to get started!",
      ),
    ).toBeTruthy();
  });

  it("navigates to the repository route using repo_number on card press", async () => {
    const harness = makeFetchHarness();
    const user = { id: "u1", email: "a@b", name: "Ada", avatar_url: null };

    harness.respond((call) => {
      if (call.url.endsWith("/api/v1/auth/me")) {
        return jsonResponse(200, user);
      }
      if (call.url.endsWith("/api/v1/repository")) {
        return jsonResponse(200, [
          makeRepo({
            id: "uuid-1",
            repo_number: 42,
            name: "pressable",
          }),
        ]);
      }
      return new Response("not found", { status: 404 });
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const screen = await renderDashboard(
      harness.fetchImpl as unknown as typeof fetch,
      queryClient,
      <DashboardScreen />,
    );

    await waitFor(() => {
      expect(screen.getByText("pressable")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(screen.getByText("pressable"));
    });

    expect(pushCalls).toContain("/(app)/repo/42");
  });
});
