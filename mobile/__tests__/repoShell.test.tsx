/**
 * Tests for the repository shell.
 *
 * The shell is the container every repository screen lives in: the top bar,
 * the bottom dock, and the decision about what a repository that
 * is not ready yet is allowed to show.
 *
 * The tab navigator is stubbed rather than mounted. A real navigator needs
 * a navigation container and a native screen stack, and what is under test
 * here is the shell's contract -- which tabs exist, what they are called,
 * and which of them are available for a repository that has not been
 * indexed -- not the navigator's own behaviour.
 */

import React from "react";
import { fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { router } from "expo-router";

import RepoLayout from "@/app/(app)/repo/[id]/_layout";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";
import { AuthProvider } from "@/hooks/useAuth";
import type Repository from "@/types/repository";

/**
 * The route parameters the stubbed router reports.
 *
 * ``mock``-prefixed so the hoisted ``jest.mock`` factory is allowed to
 * close over them.
 */
let mockParams: Record<string, string> = { id: "42" };

/** The path the stubbed router reports. */
let mockPathname = "/repo/42";

/** The route the stubbed navigator reports as focused. */
let mockFocusedRoute = "index";

/** Routes the dock asked the navigator to switch to. */
const mockNavigated: string[] = [];

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
    canGoBack: () => true,
  };
  return {
    __esModule: true,
    default: routerObj,
    router: routerObj,
    useRouter: () => routerObj,
    useGlobalSearchParams: () => mockParams,
    useSegments: () => ["repo", "42"],
    usePathname: () => mockPathname,
    Stack: ((p: { children?: unknown }) => p.children) as unknown as object,
    Redirect: (() => null) as unknown as object,
  };
});

/**
 * A tab navigator stub.
 *
 * The real navigator needs a navigation container and a native screen
 * stack, and what is under test here is the shell's contract -- which tabs
 * exist, what they are called, and which of them are available for a
 * repository that has not been indexed -- not the navigator's own
 * behaviour. The stub builds just enough navigator state for the real
 * :component:`RepoDock` to render, so the dock itself is still exercised.
 */
jest.mock("expo-router/js-tabs", () => {
  const ReactLocal = require("react");

  const Tabs = ({ children, tabBar }: any) => {
    const screens = ReactLocal.Children.toArray(children) as {
      props: { name: string; options?: { title?: string } };
    }[];

    const routes = screens.map((screen) => ({
      key: screen.props.name,
      name: screen.props.name,
      params: {},
    }));

    const descriptors: Record<string, unknown> = {};
    screens.forEach((screen) => {
      descriptors[screen.props.name] = {
        options: screen.props.options ?? {},
      };
    });

    const state = {
      index: Math.max(
        0,
        routes.findIndex((r) => r.name === mockFocusedRoute),
      ),
      routes,
      type: "tab",
      key: "tab",
    };

    const navigation = {
      emit: () => ({ defaultPrevented: false }),
      navigate: (name: string) => {
        mockNavigated.push(name);
      },
    };

    return ReactLocal.createElement(
      ReactLocal.Fragment,
      null,
      tabBar
        ? tabBar({
            state,
            descriptors,
            navigation,
            insets: { top: 0, right: 0, bottom: 0, left: 0 },
          })
        : null,
    );
  };

  Tabs.Screen = () => null;

  return { __esModule: true, Tabs, default: Tabs };
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

/** Hrefs the shell asked the router to navigate to. */
const dismissToCalls: string[] = [];

/** Hrefs the shell asked the router to switch to. */
const navigateCalls: string[] = [];

/**
 * The fetch stub the last render installed.
 *
 * The stub stays installed for the whole test: the API client reads
 * ``fetch`` from the global at call time, and a refetch that the status
 * poller triggers lands after the render has returned.
 */
let stubbedFetch: typeof fetch | null = null;

beforeEach(() => {
  mockParams = { id: "42" };
  mockPathname = "/repo/42";
  mockFocusedRoute = "index";
  mockNavigated.length = 0;
  dismissToCalls.length = 0;
  navigateCalls.length = 0;

  (router.dismissTo as unknown as (...args: string[]) => void) = (
    href: string,
  ) => {
    dismissToCalls.push(href);
  };

  (router.navigate as unknown as (...args: string[]) => void) = (
    href: string,
  ) => {
    navigateCalls.push(href);
  };

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
 * Render the shell against a repository fixture.
 *
 * @param repo - The repository the backend should answer with.
 * @returns The rendered screen.
 */
async function renderShell(repo: Repository) {
  const fetchImpl = jest.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/api/v1/auth/me")) {
      return new Response(
        JSON.stringify({ id: "u1", email: "a@b", name: "Ada" }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (url.endsWith("/api/v1/repository/42")) {
      return new Response(JSON.stringify(repo), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
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
          <RepoLayout />
        </AuthProvider>
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

describe("RepoLayout", () => {
  it("shows the repository's owner, name and status in the top bar", async () => {
    const screen = await renderShell(makeRepo({
        name: "illume",
        github_url: "https://github.com/example/illume",
      }));

    await waitFor(() => {
      expect(screen.getByTestId("repo-name")).toBeTruthy();
    });

    expect(screen.getByText("example/")).toBeTruthy();
    expect(screen.getByText("illume")).toBeTruthy();
    expect(screen.getByTestId("repo-header-status")).toBeTruthy();
    expect(screen.getByText("READY · main @ abcdef1")).toBeTruthy();
  });

  it("lists the five dock slots for an indexed repository", async () => {
    const screen = await renderShell(makeRepo());

    await waitFor(() => {
      expect(screen.getByTestId("repo-dock")).toBeTruthy();
    });

    for (const label of ["Overview", "Graph", "Ask", "Files", "Terms"]) {
      expect(screen.getByLabelText(label)).toBeTruthy();
    }
    expect(screen.getAllByRole("tab")).toHaveLength(5);
    // Settings has no slot of its own.
    expect(screen.queryByTestId("repo-tab-settings")).toBeNull();
  });

  it("draws the slots in the dock's order with Ask in the centre", async () => {
    const screen = await renderShell(makeRepo());

    await waitFor(() => {
      expect(screen.getByTestId("repo-dock")).toBeTruthy();
    });

    const order = screen
      .getAllByRole("tab")
      .map((tab) => tab.props.testID as string);
    expect(order).toEqual([
      "repo-tab-index",
      "repo-tab-graph",
      "repo-tab-chat",
      "repo-tab-explorer",
      "repo-tab-glossary",
    ]);
  });

  it("opens the chat from the Ask slot", async () => {
    const screen = await renderShell(makeRepo());

    await waitFor(() => {
      expect(screen.getByTestId("repo-tab-chat")).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId("repo-tab-chat"));

    expect(mockNavigated).toEqual(["chat"]);
  });

  it("marks only the focused slot as selected", async () => {
    mockFocusedRoute = "chat";
    const screen = await renderShell(makeRepo());

    await waitFor(() => {
      expect(screen.getByTestId("repo-tab-chat")).toBeTruthy();
    });

    const selected = screen
      .getAllByRole("tab")
      .filter((tab) => tab.props.accessibilityState?.selected);
    expect(selected.map((tab) => tab.props.testID)).toEqual(["repo-tab-chat"]);
    expect(screen.getByTestId("repo-tab-active-chat")).toBeTruthy();
    expect(screen.queryByTestId("repo-tab-active-index")).toBeNull();
  });

  it("leaves every slot unselected while the settings screen is open", async () => {
    mockFocusedRoute = "settings";
    const screen = await renderShell(makeRepo());

    await waitFor(() => {
      expect(screen.getByTestId("repo-dock")).toBeTruthy();
    });

    const selected = screen
      .getAllByRole("tab")
      .filter((tab) => tab.props.accessibilityState?.selected);
    expect(selected).toHaveLength(0);
  });

  it("hides the sections a repository that is not indexed cannot support", async () => {
    const screen = await renderShell(makeRepo({ status: "parsing" }));

    await waitFor(() => {
      expect(screen.getByTestId("repo-tab-index")).toBeTruthy();
    });

    expect(screen.getAllByRole("tab")).toHaveLength(1);
    expect(screen.queryByLabelText("Ask")).toBeNull();
    expect(screen.queryByLabelText("Graph")).toBeNull();
    expect(screen.queryByLabelText("Files")).toBeNull();
    expect(screen.queryByLabelText("Terms")).toBeNull();
  });

  it("returns to the dashboard rather than leaving a broken stack", async () => {
    const screen = await renderShell(makeRepo());

    await waitFor(() => {
      expect(screen.getByTestId("repo-back")).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId("repo-back"));

    expect(dismissToCalls).toContain("/(app)/dashboard");
  });

  it("opens the repository's settings from the top bar", async () => {
    const pushed: string[] = [];
    (router.push as unknown as (...args: string[]) => void) = (href: string) => {
      pushed.push(href);
    };
    const screen = await renderShell(makeRepo());

    await waitFor(() => {
      expect(screen.getByTestId("repo-settings")).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId("repo-settings"));

    expect(pushed).toContain("/(app)/repo/42/settings");
  });

  it("sends a deep link into an unavailable section back to the overview", async () => {
    mockPathname = "/repo/42/glossary";

    const screen = await renderShell(makeRepo({ status: "parsing" }));

    await waitFor(() => {
      expect(screen.getByTestId("repo-name")).toBeTruthy();
    });

    expect(screen.queryByLabelText("Terms")).toBeNull();
    await waitFor(() => {
      expect(navigateCalls).toContain("/(app)/repo/42");
    });
  });

  it("sends a deep link into the chat of an unindexed repository to the overview", async () => {
    mockPathname = "/repo/42/chat";

    await renderShell(makeRepo({ status: "parsing" }));

    await waitFor(() => {
      expect(navigateCalls).toContain("/(app)/repo/42");
    });
  });

  it("leaves a reader on a section of an indexed repository alone", async () => {
    mockPathname = "/repo/42/glossary";

    const screen = await renderShell(makeRepo({ status: "ready" }));

    await waitFor(() => {
      expect(screen.getByTestId("repo-name")).toBeTruthy();
    });

    expect(navigateCalls).toHaveLength(0);
    expect(screen.getByLabelText("Terms")).toBeTruthy();
  });
});
