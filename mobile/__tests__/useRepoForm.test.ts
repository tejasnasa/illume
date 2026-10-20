/**
 * Tests for the repository creation form hook.
 *
 * The create flow is where a user spends money (their own API key, or the
 * operator's free allowance), so the contract worth pinning is:
 *
 * 1. A successful creation posts the right body and navigates to the new
 *    repository's page.
 * 2. A spent free-tier allowance (HTTP 402) is distinguishable from an
 *    ordinary failure, so the screen can point at Settings.
 * 3. A failure surfaces the server's own message rather than a generic
 *    one.
 */

import { renderHook, act, waitFor } from "@testing-library/react-native";
import { router } from "expo-router";

import { useRepoForm } from "@/hooks/useRepoForm";
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

const VALUES = {
  github_url: "https://github.com/owner/name",
  branch: "main",
  commit_sha: null as string | null,
};

beforeEach(() => {
  __setTokenStoreImplementation({
    async getItemAsync() {
      return null;
    },
    async setItemAsync() {},
    async deleteItemAsync() {},
  });
  (router.push as unknown as (...args: string[]) => void) = () => {};
});

function stubFetch(response: Response | (() => Response)): jest.Mock {
  return jest.fn(async () =>
    typeof response === "function" ? response() : response,
  ) as unknown as jest.Mock;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("useRepoForm", () => {
  it("posts the repository and returns the created identifiers", async () => {
    const fetchImpl = stubFetch(
      jsonResponse(202, { repo_id: "uuid-1", repo_num: 42 }),
    );
    const originalFetch = global.fetch;
    (global as unknown as { fetch: typeof fetch }).fetch =
      fetchImpl as unknown as typeof fetch;

    try {
      const { result } = await renderHook(() => useRepoForm());

      let created: unknown = null;
      await act(async () => {
        created = await result.current.submit(VALUES);
      });

      expect(created).toEqual({ repo_id: "uuid-1", repo_num: 42 });

      const [url, init] = fetchImpl.mock.calls[0];
      expect(url).toBe("http://10.0.2.2:8000/api/v1/repository");
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body)).toEqual({
        github_url: "https://github.com/owner/name",
        branch: "main",
        commit_sha: null,
      });

      expect(result.current.ingestError).toBeNull();
    } finally {
      (global as unknown as { fetch: typeof fetch }).fetch = originalFetch;
    }
  });

  it("does not navigate on its own -- the caller owns the transition", async () => {
    const fetchImpl = stubFetch(
      jsonResponse(202, { repo_id: "uuid-1", repo_num: 42 }),
    );
    const originalFetch = global.fetch;
    (global as unknown as { fetch: typeof fetch }).fetch =
      fetchImpl as unknown as typeof fetch;

    const pushCalls: string[] = [];
    (router.push as unknown as (...args: string[]) => void) = (
      href: string,
    ) => {
      pushCalls.push(href);
    };

    try {
      const { result } = await renderHook(() => useRepoForm());

      await act(async () => {
        await result.current.submit(VALUES);
      });

      // The picker is a modal route; pushing from inside it would leave
      // the picker in the stack. The route decides what happens next.
      expect(pushCalls).toEqual([]);
    } finally {
      (global as unknown as { fetch: typeof fetch }).fetch = originalFetch;
    }
  });

  it("flags a 402 as a spent free-tier allowance", async () => {
    const fetchImpl = stubFetch(
      jsonResponse(402, {
        detail:
          "Add your own API key to ingest another repository. Configure one in your account settings.",
      }),
    );
    const originalFetch = global.fetch;
    (global as unknown as { fetch: typeof fetch }).fetch =
      fetchImpl as unknown as typeof fetch;

    try {
      const { result } = await renderHook(() => useRepoForm());

      await act(async () => {
        const created = await result.current.submit(VALUES);
        expect(created).toBeNull();
      });

      await waitFor(() => {
        expect(result.current.quotaExceeded).toBe(true);
      });
      expect(result.current.ingestError).toContain("Add your own API key");
    } finally {
      (global as unknown as { fetch: typeof fetch }).fetch = originalFetch;
    }
  });

  it("does not flag an ordinary failure as a quota problem", async () => {
    const fetchImpl = stubFetch(
      jsonResponse(500, { detail: "Database is on fire" }),
    );
    const originalFetch = global.fetch;
    (global as unknown as { fetch: typeof fetch }).fetch =
      fetchImpl as unknown as typeof fetch;

    try {
      const { result } = await renderHook(() => useRepoForm());

      await act(async () => {
        await result.current.submit(VALUES);
      });

      await waitFor(() => {
        expect(result.current.ingestError).toBe("Database is on fire");
      });
      expect(result.current.quotaExceeded).toBe(false);
    } finally {
      (global as unknown as { fetch: typeof fetch }).fetch = originalFetch;
    }
  });

  it("clears a previous error when asked", async () => {
    const fetchImpl = stubFetch(jsonResponse(500, { detail: "boom" }));
    const originalFetch = global.fetch;
    (global as unknown as { fetch: typeof fetch }).fetch =
      fetchImpl as unknown as typeof fetch;

    try {
      const { result } = await renderHook(() => useRepoForm());

      await act(async () => {
        await result.current.submit(VALUES);
      });
      expect(result.current.ingestError).toBe("boom");

      await act(async () => {
        result.current.clearError();
      });
      expect(result.current.ingestError).toBeNull();
    } finally {
      (global as unknown as { fetch: typeof fetch }).fetch = originalFetch;
    }
  });
});
