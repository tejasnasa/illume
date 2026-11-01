/**
 * Tests for the glossary screen.
 *
 * The screen is where the reader meets the glossary: the search box, the
 * list of entries, and the way an entry expands to its full definition.
 * The tests here are about the screen's own drawing -- the transport is
 * stubbed, so what is under test is the screen's reading of the payload.
 *
 * The branch on the source link is pinned too. The web client hard-codes
 * ``master`` for that link, which sends a reader of a repository ingested
 * from ``main`` to a branch that does not exist; the mobile screen builds
 * the link from the repository's own record.
 */

import React from "react";
import { Linking } from "react-native";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import GlossaryScreen from "@/app/(app)/repo/[id]/glossary";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";
import type Repository from "@/types/repository";
import type { default as Glossary } from "@/types/glossary";

jest.mock("expo-router", () => ({
  useGlobalSearchParams: () => ({ id: "42" }),
  router: { push: jest.fn(), navigate: jest.fn(), replace: jest.fn() },
}));

/** The route parameters the stubbed router reports. */
const mockParams: Record<string, string> = { id: "42" };

/**
 * The repository the backend answers with.
 *
 * The branch is ``main``: a repository ingested from ``main`` is the case
 * the hard-coded ``master`` link gets wrong.
 */
const REPO: Repository = {
  id: "repo-uuid-1",
  github_url: "https://github.com/example/foo",
  name: "foo",
  status: "ready",
  architecture_summary: "A repository.",
  repo_number: 42,
  primary_language: "Python",
  detected_stack: {
    ci_cd: [],
    databases: [],
    languages: ["Python"],
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

/** A definition long enough to be folded away. */
const LONG_DEFINITION =
  "The ingestion task clones the repository, walks its tree, parses every file it finds and stores the symbols it recovers in the database. It then resolves the imports between those symbols so the dependency graph can be built, and finally scores each file by how many other files depend on it.";

/** The glossary the backend answers with. */
const GLOSSARY: Glossary = {
  entries: [
    {
      id: "entry-1",
      name: "ingest_repository",
      definition: "Queues and runs the ingestion task.",
      file_path: "app/tasks/ingest.py",
      line_number: 42,
      symbol_id: null,
    },
    {
      id: "entry-2",
      name: "scan_repository",
      definition: LONG_DEFINITION,
      file_path: "app/services/scanner.py",
      line_number: 118,
      symbol_id: null,
    },
  ],
  total: 2,
  page: 1,
  page_size: 20,
};

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

/**
 * The default backend: the repository and the glossary.
 *
 * @param url - The URL the client asked for.
 * @returns The response.
 */
function defaultHandler(url: string): Response {
  if (url.includes("/api/v1/repository/repo-uuid-1/glossary")) {
    return jsonResponse(GLOSSARY);
  }
  if (url.endsWith("/api/v1/repository/42")) {
    return jsonResponse(REPO);
  }
  return new Response("not found", { status: 404 });
}

/**
 * The fetch stub the last render installed.
 */
let stubbedFetch: typeof fetch | null = null;

/**
 * Let the list's own timers settle.
 *
 * A virtualised list schedules a cell-measurement timer of its own, and a
 * query that resolves after the last assertion would update the screen
 * outside React's ``act()``. Flushing the timers inside ``act()`` keeps the
 * run honest about what it rendered.
 */
async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

/**
 * Render the glossary screen against a stubbed backend.
 *
 * @param handler - Decides what the backend answers with.
 * @returns The rendered screen.
 */
async function renderScreen(
  handler: (url: string) => Response = defaultHandler,
) {
  const fetchImpl = jest.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    return handler(url);
  });

  stubbedFetch = global.fetch;
  (global as unknown as { fetch: typeof fetch }).fetch =
    fetchImpl as unknown as typeof fetch;

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  const screen = await render(
    <QueryClientProvider client={queryClient}>
      <GlossaryScreen />
    </QueryClientProvider>,
  );

  await settle();

  return screen;
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

afterEach(() => {
  if (stubbedFetch) {
    (global as unknown as { fetch: typeof fetch }).fetch = stubbedFetch;
    stubbedFetch = null;
  }
});

describe("GlossaryScreen", () => {
  it("lists the glossary entries", async () => {
    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByText("ingest_repository")).toBeTruthy();
    });

    expect(screen.getByText("scan_repository")).toBeTruthy();
    expect(
      screen.getByText("Queues and runs the ingestion task."),
    ).toBeTruthy();
    expect(screen.getByTestId("glossary-count")).toHaveTextContent(
      "Showing 2 of 2 entries",
    );

    await settle();
  });

  it("shows every definition in full, with no expand control", async () => {
    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByText("scan_repository")).toBeTruthy();
    });

    // The definition is not folded: the whole text is on screen, and there
    // is no toggle to reveal it.
    expect(screen.getByText(LONG_DEFINITION)).toBeTruthy();
    expect(screen.queryByTestId("glossary-entry-1-toggle")).toBeNull();

    await settle();
  });

  it("says a repository with no glossary has nothing to show", async () => {
    const screen = await renderScreen((url) =>
      url.includes("/api/v1/repository/repo-uuid-1/glossary")
        ? jsonResponse({ ...GLOSSARY, entries: [], total: 0 })
        : defaultHandler(url),
    );

    await waitFor(() => {
      expect(screen.getByTestId("glossary-empty")).toBeTruthy();
    });

    expect(screen.getByText("No glossary entries found.")).toBeTruthy();
    expect(screen.queryByTestId("glossary-error")).toBeNull();

    await settle();
  });

  it("links an entry to the branch the repository was ingested from", async () => {
    const openUrl = jest
      .spyOn(Linking, "openURL")
      .mockImplementation(async () => true);

    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByTestId("glossary-entry-0-link")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(screen.getByTestId("glossary-entry-0-link"));
    });

    expect(openUrl).toHaveBeenCalledWith(
      "https://github.com/example/foo/blob/main/app/tasks/ingest.py#L42",
    );

    openUrl.mockRestore();
    await settle();
  });

  it("never links to a branch the repository does not have", async () => {
    const openUrl = jest
      .spyOn(Linking, "openURL")
      .mockImplementation(async () => true);

    const screen = await renderScreen();

    await waitFor(() => {
      expect(screen.getByTestId("glossary-entry-0-link")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(screen.getByTestId("glossary-entry-0-link"));
    });

    const url = openUrl.mock.calls[0][0] as string;
    expect(url).toContain("/blob/main/");
    expect(url).not.toContain("master");

    openUrl.mockRestore();
    await settle();
  });

  it("says the glossary could not be loaded when the request fails", async () => {
    const screen = await renderScreen((url) =>
      url.includes("/api/v1/repository/repo-uuid-1/glossary")
        ? jsonResponse({ detail: "Failed to build glossary" }, 500)
        : defaultHandler(url),
    );

    await waitFor(() => {
      expect(screen.getByTestId("glossary-error")).toBeTruthy();
    });

    expect(screen.getByTestId("glossary-error")).toHaveTextContent(
      "Failed to build glossary",
    );

    await settle();
  });

  it("searches the glossary through the server's search route", async () => {
    const fetchImpl = jest.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/glossary/search")) {
        return jsonResponse({
          ...GLOSSARY,
          entries: [GLOSSARY.entries[0]],
          total: 1,
        });
      }
      return defaultHandler(url);
    });

    stubbedFetch = global.fetch;
    (global as unknown as { fetch: typeof fetch }).fetch =
      fetchImpl as unknown as typeof fetch;

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const screen = await render(
      <QueryClientProvider client={queryClient}>
        <GlossaryScreen />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("ingest_repository")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.changeText(screen.getByTestId("glossary-search"), "ingest");
    });

    // The search is debounced, so the request only goes out once the
    // reader has paused.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 500));
    });

    await waitFor(() => {
      expect(
        fetchImpl.mock.calls.some((call) =>
          String(call[0]).includes("/glossary/search?q=ingest"),
        ),
      ).toBe(true);
    });

    await settle();
  });
});
