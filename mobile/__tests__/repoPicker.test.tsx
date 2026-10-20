/**
 * Tests for the repository creation flow.
 *
 * The picker is the screen a user spends money on -- the ingest either
 * happens or it does not. These tests drive the real component against a
 * stubbed backend and assert the three things that matter:
 *
 * 1. The GitHub repo list renders, and picking a repo advances to the
 *    version step.
 * 2. Choosing a branch and confirming creates the repository and starts
 *    the ingest.
 * 3. A spent free-tier allowance produces a clear message, not a crash.
 */

import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { router } from "expo-router";

import { RepoPickerModal } from "@/components/RepoPickerModal";
import { AuthProvider } from "@/hooks/useAuth";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";

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

/** Hrefs pushed since the last reset. */
let pushCalls: string[] = [];

/** Repo numbers reported to ``onClose`` since the last reset. */
let closedWith: (number | null)[] = [];

const REPOS = [
  {
    full_name: "owner/illume",
    name: "illume",
    private: false,
    default_branch: "main",
    description: "The onboarding tool.",
    language: "TypeScript",
    updated_at: "2026-01-15T12:00:00Z",
    html_url: "https://github.com/owner/illume",
    stargazers_count: 3,
  },
  {
    full_name: "owner/other",
    name: "other",
    private: true,
    default_branch: "trunk",
    description: null,
    language: null,
    updated_at: "2026-01-14T12:00:00Z",
    html_url: "https://github.com/owner/other",
    stargazers_count: 0,
  },
];

const BRANCHES = [
  { name: "main", sha: "aaa1111", is_default: true },
  { name: "feature", sha: "bbb2222", is_default: false },
];

const COMMITS = [
  {
    sha: "aaa1111aaaa",
    short_sha: "aaa1111",
    message: "Add the ingest endpoint",
    author_name: "Ada",
    author_avatar: null,
    authored_at: "2026-01-15T10:00:00Z",
    parents: [],
    branches: ["main"],
  },
  {
    sha: "bbb2222bbbb",
    short_sha: "bbb2222",
    message: "Start the feature branch",
    author_name: "Ada",
    author_avatar: null,
    authored_at: "2026-01-14T10:00:00Z",
    parents: ["aaa1111aaaa"],
    branches: ["feature"],
  },
];

/**
 * A backend stub that answers the three GitHub endpoints and the create
 * endpoint, recording the creation body.
 */
function makeBackend(createResponse: () => Response) {
  const creations: unknown[] = [];

  const fetchImpl = jest.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();

      if (url.includes("/api/v1/github/repos?")) {
        return new Response(JSON.stringify(REPOS), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.includes("/branches")) {
        return new Response(JSON.stringify(BRANCHES), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.includes("/commits-multibranch")) {
        return new Response(JSON.stringify(COMMITS), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith("/api/v1/repository") && method === "POST") {
        creations.push(JSON.parse(String(init?.body ?? "{}")));
        return createResponse();
      }
      if (url.endsWith("/api/v1/auth/me")) {
        return new Response(
          JSON.stringify({
            id: "u1",
            email: "a@b",
            name: "Ada",
            avatar_url: null,
            github_id: "1",
            ai_provider: null,
            ai_model: null,
            has_ai_key: true,
            free_ingestions_used: 0,
            free_chat_messages_used: 0,
            free_ingestions_limit: 3,
            free_chat_messages_limit: 10,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      return new Response("not found", { status: 404 });
    },
  );

  return { fetchImpl, creations };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * Wait until the timeline has both branches and commits.
 *
 * The ingest button is disabled until commits arrive, so a test that
 * pressed it before the query settled would silently do nothing. Waiting
 * on a commit row -- the thing the button is gated on -- makes the
 * press deterministic.
 */
async function waitForTimeline(screen: {
  getByTestId: (id: string) => unknown;
}) {
  await waitFor(() => {
    expect(screen.getByTestId("gitgraph-commit-aaa1111")).toBeTruthy();
  });
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

/**
 * Render the picker with the provider stack the app uses.
 */
async function renderPicker(fetchImpl: typeof fetch) {
  return render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 0, height: 0 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      <QueryClientProvider client={makeClient()}>
        <AuthProvider fetchImpl={fetchImpl}>
          <RepoPickerModal
            onClose={(repoNum) => {
              closedWith.push(repoNum);
            }}
          />
        </AuthProvider>
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

beforeEach(() => {
  pushCalls = [];
  closedWith = [];
  __setTokenStoreImplementation({
    async getItemAsync() {
      return null;
    },
    async setItemAsync() {},
    async deleteItemAsync() {},
  });
  (router.push as unknown as (...args: string[]) => void) = (href: string) => {
    pushCalls.push(href);
  };
});

/**
 * Point the global ``fetch`` at a backend stub for the duration of a test.
 *
 * The transport layer always reads the global ``fetch``, and React Query
 * fires its requests *after* the render returns -- so the swap has to
 * outlive the render, not be scoped to it.
 */
function useBackend(createResponse: () => Response) {
  const backend = makeBackend(createResponse);
  const originalFetch = global.fetch;
  (global as unknown as { fetch: typeof fetch }).fetch =
    backend.fetchImpl as unknown as typeof fetch;
  return {
    backend,
    restore: () => {
      (global as unknown as { fetch: typeof fetch }).fetch = originalFetch;
    },
  };
}

describe("RepoPickerModal", () => {
  it("lists the user's GitHub repositories", async () => {
    const { backend, restore } = useBackend(() =>
      jsonResponse(202, { repo_num: 1 }),
    );
    try {
      const screen = await renderPicker(
        backend.fetchImpl as unknown as typeof fetch,
      );

      await waitFor(() => {
        expect(screen.getByText("illume")).toBeTruthy();
      });
      expect(screen.getByText("other")).toBeTruthy();
      // The description falls back to web's copy when GitHub has none.
      expect(screen.getByText("No description provided.")).toBeTruthy();
    } finally {
      restore();
    }
  });

  it("filters the list by the search term", async () => {
    const { backend, restore } = useBackend(() =>
      jsonResponse(202, { repo_num: 1 }),
    );
    try {
      const screen = await renderPicker(
        backend.fetchImpl as unknown as typeof fetch,
      );

      await waitFor(() => {
        expect(screen.getByText("illume")).toBeTruthy();
      });

      await act(async () => {
        fireEvent.changeText(screen.getByTestId("repo-picker-search"), "other");
      });

      await waitFor(() => {
        expect(screen.queryByText("illume")).toBeNull();
      });
      expect(screen.getByText("other")).toBeTruthy();
    } finally {
      restore();
    }
  });

  it("advances to the version step when a repository is picked", async () => {
    const { backend, restore } = useBackend(() =>
      jsonResponse(202, { repo_num: 1 }),
    );
    try {
      const screen = await renderPicker(
        backend.fetchImpl as unknown as typeof fetch,
      );

      await waitFor(() => {
        expect(screen.getByText("illume")).toBeTruthy();
      });

      await act(async () => {
        fireEvent.press(screen.getByText("illume"));
      });

      await waitFor(() => {
        expect(
          screen.getByText("Configure Version for owner/illume"),
        ).toBeTruthy();
      });
      // The branch chips are the mobile addition -- the branch to ingest is
      // chosen explicitly rather than implied by the default.
      await waitFor(() => {
        expect(screen.getByTestId("gitgraph-branch-main")).toBeTruthy();
      });
    } finally {
      restore();
    }
  });

  it("creates the repository with the chosen branch", async () => {
    const { backend, restore } = useBackend(() =>
      jsonResponse(202, { repo_id: "uuid-1", repo_num: 42 }),
    );
    try {
      const screen = await renderPicker(
        backend.fetchImpl as unknown as typeof fetch,
      );

      await waitFor(() => {
        expect(screen.getByText("illume")).toBeTruthy();
      });

      await act(async () => {
        fireEvent.press(screen.getByText("illume"));
      });

      await waitFor(() => {
        expect(screen.getByTestId("gitgraph-branch-feature")).toBeTruthy();
      });
      await waitForTimeline(screen);

      // Pick the feature branch, then confirm the ingest.
      await act(async () => {
        fireEvent.press(screen.getByTestId("gitgraph-branch-feature"));
      });

      await act(async () => {
        fireEvent.press(screen.getByTestId("gitgraph-ingest"));
      });

      await waitFor(() => {
        expect(backend.creations).toHaveLength(1);
      });

      expect(backend.creations[0]).toEqual({
        github_url: "https://github.com/owner/illume",
        branch: "feature",
        commit_sha: null,
      });
      // The picker reports the new repository; the route turns that into
      // the navigation, because the picker itself is a modal route.
      expect(closedWith).toEqual([42]);
    } finally {
      restore();
    }
  });

  it("shows a clear message when the free-tier allowance is spent", async () => {
    const { backend, restore } = useBackend(() =>
      jsonResponse(402, {
        detail:
          "Add your own API key to ingest another repository. Configure one in your account settings.",
      }),
    );
    try {
      const screen = await renderPicker(
        backend.fetchImpl as unknown as typeof fetch,
      );

      await waitFor(() => {
        expect(screen.getByText("illume")).toBeTruthy();
      });

      await act(async () => {
        fireEvent.press(screen.getByText("illume"));
      });

      await waitFor(() => {
        expect(screen.getByTestId("gitgraph-ingest")).toBeTruthy();
      });
      await waitForTimeline(screen);

      await act(async () => {
        fireEvent.press(screen.getByTestId("gitgraph-ingest"));
      });

      // The error is surfaced, and it points at Settings rather than
      // looking like a generic failure.
      await waitFor(() => {
        expect(
          screen.getByText(/Add your own API key to ingest another repository/),
        ).toBeTruthy();
      });
      expect(screen.getByText(/Add your own API key in Settings/)).toBeTruthy();
      // No navigation happened -- the repository was not created.
      expect(closedWith).toEqual([]);
    } finally {
      restore();
    }
  });

  it("rejects an external URL that is not a GitHub repository", async () => {
    const { backend, restore } = useBackend(() =>
      jsonResponse(202, { repo_num: 1 }),
    );
    try {
      const screen = await renderPicker(
        backend.fetchImpl as unknown as typeof fetch,
      );

      await act(async () => {
        fireEvent.press(screen.getByTestId("repo-picker-tab-external"));
      });

      await act(async () => {
        fireEvent.changeText(
          screen.getByTestId("repo-picker-external-url"),
          "https://gitlab.com/owner/name",
        );
      });

      await act(async () => {
        fireEvent.press(screen.getByTestId("repo-picker-external-continue"));
      });

      await waitFor(() => {
        expect(
          screen.getByText(
            "Please enter a valid GitHub repository URL (e.g. https://github.com/user/repo)",
          ),
        ).toBeTruthy();
      });
      // Still on the picker step.
      expect(screen.getByTestId("repo-picker-external-url")).toBeTruthy();
    } finally {
      restore();
    }
  });

  it("accepts a valid external URL and advances to the version step", async () => {
    const { backend, restore } = useBackend(() =>
      jsonResponse(202, { repo_num: 1 }),
    );
    try {
      const screen = await renderPicker(
        backend.fetchImpl as unknown as typeof fetch,
      );

      await act(async () => {
        fireEvent.press(screen.getByTestId("repo-picker-tab-external"));
      });

      await act(async () => {
        fireEvent.changeText(
          screen.getByTestId("repo-picker-external-url"),
          "https://github.com/owner/external-repo",
        );
      });

      await act(async () => {
        fireEvent.press(screen.getByTestId("repo-picker-external-continue"));
      });

      await waitFor(() => {
        expect(
          screen.getByText("Configure Version for owner/external-repo"),
        ).toBeTruthy();
      });
    } finally {
      restore();
    }
  });
});
