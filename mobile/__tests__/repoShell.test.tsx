/**
 * Tests for the repository shell.
 *
 * The shell is the container every repository screen lives in: the identity
 * header, the section tabs, and the decision about what a repository that
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
    useLocalSearchParams: () => mockParams,
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
 * :component:`RepoTabBar` to render, so the bar itself is still exercised.
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
      index: 0,
      routes,
      type: "tab",
      key: "tab",
    };

    const navigation = {
      emit: () => ({ defaultPrevented: false }),
      navigate: () => {},
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
  it("shows the repository's name and status in the header", async () => {
    const screen = await renderShell(makeRepo({ name: "illume" }));

    await waitFor(() => {
      expect(screen.getByTestId("repo-name")).toBeTruthy();
    });

    expect(screen.getByText("illume")).toBeTruthy();
    expect(screen.getByTestId("repo-header-status")).toBeTruthy();
    expect(screen.getByText("ready")).toBeTruthy();
  });

  it("offers the four section tabs with the web client's labels", async () => {
    const screen = await renderShell(makeRepo());

    await waitFor(() => {
      expect(screen.getByTestId("repo-tab-index")).toBeTruthy();
    });

    expect(screen.getByText("Home")).toBeTruthy();
    expect(screen.getByText("Glossary")).toBeTruthy();
    expect(screen.getByText("Explorer")).toBeTruthy();
    expect(screen.getByText("Graph")).toBeTruthy();
  });

  it("hides the sections a repository that is not indexed cannot support", async () => {
    const screen = await renderShell(makeRepo({ status: "parsing" }));

    await waitFor(() => {
      expect(screen.getByTestId("repo-tab-index")).toBeTruthy();
    });

    expect(screen.getByText("Home")).toBeTruthy();
    expect(screen.queryByText("Glossary")).toBeNull();
    expect(screen.queryByText("Explorer")).toBeNull();
    expect(screen.queryByText("Graph")).toBeNull();
  });

  it("returns to the dashboard rather than leaving a broken stack", async () => {
    const screen = await renderShell(makeRepo());

    await waitFor(() => {
      expect(screen.getByTestId("repo-back")).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId("repo-back"));

    expect(dismissToCalls).toContain("/(app)/dashboard");
  });

  it("sends a deep link into an unavailable section back to the overview", async () => {
    mockPathname = "/repo/42/glossary";

    const screen = await renderShell(makeRepo({ status: "parsing" }));

    await waitFor(() => {
      expect(screen.getByTestId("repo-name")).toBeTruthy();
    });

    // The section tabs are gone, so the only thing on screen is the
    // overview's own header, and the reader is sent to the overview.
    expect(screen.queryByText("Glossary")).toBeNull();
    await waitFor(() => {
      expect(navigateCalls).toContain("/(app)/repo/42");
    });
  });

  it("leaves a reader on a section tab of an indexed repository alone", async () => {
    mockPathname = "/repo/42/glossary";

    const screen = await renderShell(makeRepo({ status: "ready" }));

    await waitFor(() => {
      expect(screen.getByTestId("repo-name")).toBeTruthy();
    });

    expect(navigateCalls).toHaveLength(0);
    expect(screen.getByText("Glossary")).toBeTruthy();
  });
});
