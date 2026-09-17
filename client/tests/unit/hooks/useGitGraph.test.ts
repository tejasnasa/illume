import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

const BRANCHES = [
  { name: "main", sha: "a".repeat(40), is_default: true },
  { name: "develop", sha: "b".repeat(40), is_default: false },
];

const COMMITS = [
  {
    sha: "a".repeat(40),
    short_sha: "a".repeat(7),
    message: "feat: a thing",
    author_name: "Ada Lovelace",
    author_avatar: null,
    authored_at: "2026-01-02T00:00:00Z",
    parents: [],
    branches: ["main"],
  },
];

/** Registers handlers for both endpoints the hook calls. */
function stub({
  branches = BRANCHES,
  commits = COMMITS,
  branchStatus = 200,
  commitStatus = 200,
} = {}) {
  server.use(
    http.get(`${BACKEND_URL}/api/v1/github/repos/:owner/:repo/branches`, () =>
      HttpResponse.json(branches, { status: branchStatus }),
    ),
    http.get(`${BACKEND_URL}/api/v1/github/repos/:owner/:repo/commits-multibranch`, () =>
      HttpResponse.json(commits, { status: commitStatus }),
    ),
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("loading", () => {
  it("starts empty and not loading before the effects run", async () => {
    stub();
    const { useGitGraph } = await import("@/hooks/useGitGraph");

    const { result, unmount } = renderHook(() =>
      useGitGraph({ owner: "example", repo: "cool-project" }),
    );

    expect(result.current.branches).toEqual([]);
    expect(result.current.commits).toEqual([]);
    expect(result.current.error).toBeNull();
    unmount();
  });

  it("loads branches and commits", async () => {
    stub();
    const { useGitGraph } = await import("@/hooks/useGitGraph");

    const { result } = renderHook(() =>
      useGitGraph({ owner: "example", repo: "cool-project" }),
    );

    await waitFor(() => expect(result.current.commits).toHaveLength(1));
    expect(result.current.branches).toEqual(BRANCHES);
  });

  it("clears both loading flags once settled", async () => {
    stub();
    const { useGitGraph } = await import("@/hooks/useGitGraph");

    const { result } = renderHook(() =>
      useGitGraph({ owner: "example", repo: "cool-project" }),
    );

    await waitFor(() => expect(result.current.loadingCommits).toBe(false));
    expect(result.current.loadingBranches).toBe(false);
  });
});

describe("default branch", () => {
  it("prefers the branch flagged as default", async () => {
    stub();
    const { useGitGraph } = await import("@/hooks/useGitGraph");

    const { result } = renderHook(() =>
      useGitGraph({ owner: "example", repo: "cool-project" }),
    );

    await waitFor(() => expect(result.current.defaultBranch).toBe("main"));
  });

  it("falls back to the first branch when none is flagged", async () => {
    // GitHub always flags one, but the proxy's mapping is a transform that could drop it.
    stub({ branches: [{ name: "only", sha: "c".repeat(40), is_default: false }] });
    const { useGitGraph } = await import("@/hooks/useGitGraph");

    const { result } = renderHook(() =>
      useGitGraph({ owner: "example", repo: "cool-project" }),
    );

    await waitFor(() => expect(result.current.defaultBranch).toBe("only"));
  });

  it("falls back to main when there are no branches at all", async () => {
    stub({ branches: [] });
    const { useGitGraph } = await import("@/hooks/useGitGraph");

    const { result } = renderHook(() =>
      useGitGraph({ owner: "example", repo: "cool-project" }),
    );

    await waitFor(() => expect(result.current.loadingBranches).toBe(false));
    expect(result.current.defaultBranch).toBe("main");
  });
});

describe("errors", () => {
  it("surfaces a branch failure", async () => {
    stub({ branchStatus: 500 });
    const { useGitGraph } = await import("@/hooks/useGitGraph");

    const { result } = renderHook(() =>
      useGitGraph({ owner: "example", repo: "cool-project" }),
    );

    await waitFor(() => expect(result.current.error).toBe("Failed to fetch branches"));
  });

  it("surfaces a commit failure", async () => {
    stub({ commitStatus: 502 });
    const { useGitGraph } = await import("@/hooks/useGitGraph");

    const { result } = renderHook(() =>
      useGitGraph({ owner: "example", repo: "cool-project" }),
    );

    await waitFor(() =>
      expect(result.current.error).toBe("Failed to fetch multibranch commits"),
    );
  });

  it("clears the error on a successful reload", async () => {
    // The error is reset at the top of each effect, so switching repositories after a
    // failure must not leave the banner up.
    stub({ branchStatus: 500 });
    const { useGitGraph } = await import("@/hooks/useGitGraph");

    const { result, rerender } = renderHook(
      ({ repo }) => useGitGraph({ owner: "example", repo }),
      { initialProps: { repo: "broken" } },
    );
    await waitFor(() => expect(result.current.error).not.toBeNull());

    stub();
    rerender({ repo: "working" });

    await waitFor(() => expect(result.current.error).toBeNull());
  });
});

describe("guards", () => {
  it("makes no request without an owner and repo", async () => {
    const spy = vi.fn();
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/:owner/:repo/branches`, () => {
        spy();
        return HttpResponse.json([]);
      }),
      http.get(`${BACKEND_URL}/api/v1/github/repos/:owner/:repo/commits-multibranch`, () => {
        spy();
        return HttpResponse.json([]);
      }),
    );
    const { useGitGraph } = await import("@/hooks/useGitGraph");

    renderHook(() => useGitGraph({ owner: "", repo: "" }));

    // Give the effects a chance to fire if they were going to.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(spy).not.toHaveBeenCalled();
  });

  it("clears the previous repository's commits when the repo changes", async () => {
    // Without the explicit reset, the old history stays on screen while the new one
    // loads, which reads as though the two repositories shared a history.
    stub({ commits: COMMITS });
    const { useGitGraph } = await import("@/hooks/useGitGraph");

    const { result, rerender } = renderHook(
      ({ repo }) => useGitGraph({ owner: "example", repo }),
      { initialProps: { repo: "first" } },
    );
    await waitFor(() => expect(result.current.commits).toHaveLength(1));

    stub({ commits: [] });
    rerender({ repo: "second" });

    await waitFor(() => expect(result.current.commits).toEqual([]));
  });
});

describe("selection", () => {
  it("starts with nothing selected", async () => {
    stub();
    const { useGitGraph } = await import("@/hooks/useGitGraph");

    const { result } = renderHook(() =>
      useGitGraph({ owner: "example", repo: "cool-project" }),
    );

    expect(result.current.selectedCommit).toBeNull();
  });

  it("exposes a setter for the selected commit", async () => {
    stub();
    const { useGitGraph } = await import("@/hooks/useGitGraph");
    const { act } = await import("@testing-library/react");

    const { result } = renderHook(() =>
      useGitGraph({ owner: "example", repo: "cool-project" }),
    );
    await waitFor(() => expect(result.current.commits).toHaveLength(1));

    act(() => {
      result.current.setSelectedCommit(COMMITS[0]);
    });

    expect(result.current.selectedCommit).toEqual(COMMITS[0]);
  });

  it("drops the selection when the repository changes", async () => {
    // A commit selected in one repository has no meaning in another.
    stub();
    const { useGitGraph } = await import("@/hooks/useGitGraph");
    const { act } = await import("@testing-library/react");

    const { result, rerender } = renderHook(
      ({ repo }) => useGitGraph({ owner: "example", repo }),
      { initialProps: { repo: "first" } },
    );
    await waitFor(() => expect(result.current.commits).toHaveLength(1));
    act(() => {
      result.current.setSelectedCommit(COMMITS[0]);
    });

    rerender({ repo: "second" });

    await waitFor(() => expect(result.current.selectedCommit).toBeNull());
  });
});
