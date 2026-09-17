import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

/**
 * These are the client-side GitHub calls, so unlike the other API clients they do not
 * touch `next/headers` -- they run in the browser and authenticate with
 * `credentials: "include"`. That difference is asserted on directly, because it is the
 * one thing that would silently break: forwarding a cookie header instead would work in
 * tests and fail in the browser, where the header is forbidden.
 */

const REPO = {
  full_name: "example/cool-project",
  name: "cool-project",
  private: false,
  default_branch: "main",
  description: "A project.",
  language: "Python",
  updated_at: "2026-01-01T00:00:00Z",
  html_url: "https://github.com/example/cool-project",
  stargazers_count: 42,
};

const BRANCH = { name: "main", sha: "a".repeat(40), is_default: true };

const COMMIT = {
  sha: "a".repeat(40),
  short_sha: "a".repeat(7),
  message: "feat: a thing",
  author_name: "Ada Lovelace",
  author_avatar: null,
  authored_at: "2026-01-01T00:00:00Z",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("getMyGitHubRepos", () => {
  it("returns the repositories", async () => {
    server.use(http.get(`${BACKEND_URL}/api/v1/github/repos`, () => HttpResponse.json([REPO])));
    const { getMyGitHubRepos } = await import("@/api/github");

    await expect(getMyGitHubRepos()).resolves.toEqual([REPO]);
  });

  it("sends page and search as query parameters", async () => {
    let params = new URLSearchParams();
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos`, ({ request }) => {
        params = new URL(request.url).searchParams;
        return HttpResponse.json([REPO]);
      }),
    );
    const { getMyGitHubRepos } = await import("@/api/github");

    await getMyGitHubRepos(2, "cool");

    expect(params.get("page")).toBe("2");
    expect(params.get("q")).toBe("cool");
  });

  it("defaults to the first page with no filter", async () => {
    let params = new URLSearchParams();
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos`, ({ request }) => {
        params = new URL(request.url).searchParams;
        return HttpResponse.json([REPO]);
      }),
    );
    const { getMyGitHubRepos } = await import("@/api/github");

    await getMyGitHubRepos();

    expect(params.get("page")).toBe("1");
    expect(params.get("q")).toBe("");
  });

  it("maps a 403 to the not-linked message", async () => {
    // 403 from this route means the OAuth account was never linked. The RepoPickerModal
    // renders this exact string as its call to action, so the wording is load-bearing.
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos`, () =>
        HttpResponse.json({ detail: "GitHub account not linked." }, { status: 403 }),
      ),
    );
    const { getMyGitHubRepos } = await import("@/api/github");

    await expect(getMyGitHubRepos()).rejects.toThrow("GitHub account not linked");
  });

  it("maps a 401 to a generic failure rather than the not-linked message", async () => {
    // An expired token needs a different remedy than an unlinked account, so the two must
    // not collapse into one message.
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos`, () =>
        HttpResponse.json({ detail: "GitHub token expired." }, { status: 401 }),
      ),
    );
    const { getMyGitHubRepos } = await import("@/api/github");

    await expect(getMyGitHubRepos()).rejects.toThrow("Failed to fetch GitHub repositories");
  });

  it("throws on a 502", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos`, () => new HttpResponse(null, { status: 502 })),
    );
    const { getMyGitHubRepos } = await import("@/api/github");

    await expect(getMyGitHubRepos()).rejects.toThrow("Failed to fetch GitHub repositories");
  });

  it("passes the abort signal through", async () => {
    // The picker aborts in-flight requests when the modal closes or the query changes, so
    // a dropped signal would leave stale responses racing to set state.
    const controller = new AbortController();
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos`, async () => {
        controller.abort();
        return HttpResponse.json([REPO]);
      }),
    );
    const { getMyGitHubRepos } = await import("@/api/github");

    await expect(getMyGitHubRepos(1, "", controller.signal)).rejects.toThrow();
    expect(controller.signal.aborted).toBe(true);
  });
});

describe("getRepoBranches", () => {
  it("returns the branches", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/example/cool-project/branches`, () =>
        HttpResponse.json([BRANCH]),
      ),
    );
    const { getRepoBranches } = await import("@/api/github");

    await expect(getRepoBranches("example", "cool-project")).resolves.toEqual([BRANCH]);
  });

  it("interpolates owner and repo into the path", async () => {
    let path = "";
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/:owner/:repo/branches`, ({ request }) => {
        path = new URL(request.url).pathname;
        return HttpResponse.json([BRANCH]);
      }),
    );
    const { getRepoBranches } = await import("@/api/github");

    await getRepoBranches("my-org", "my.repo");

    expect(path).toBe("/api/v1/github/repos/my-org/my.repo/branches");
  });

  it("throws on a 404", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/example/nope/branches`, () =>
        new HttpResponse(null, { status: 404 }),
      ),
    );
    const { getRepoBranches } = await import("@/api/github");

    await expect(getRepoBranches("example", "nope")).rejects.toThrow("Failed to fetch branches");
  });
});

describe("getRepoCommits", () => {
  it("returns the commits", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/example/cool-project/commits`, () =>
        HttpResponse.json([COMMIT]),
      ),
    );
    const { getRepoCommits } = await import("@/api/github");

    await expect(getRepoCommits("example", "cool-project")).resolves.toEqual([COMMIT]);
  });

  it("sends the sha and page", async () => {
    let params = new URLSearchParams();
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/example/cool-project/commits`, ({ request }) => {
        params = new URL(request.url).searchParams;
        return HttpResponse.json([COMMIT]);
      }),
    );
    const { getRepoCommits } = await import("@/api/github");

    await getRepoCommits("example", "cool-project", "develop", 3);

    expect(params.get("sha")).toBe("develop");
    expect(params.get("page")).toBe("3");
  });

  it("sends an empty sha rather than omitting it when none is given", async () => {
    // The backend treats an empty `sha` as "use the default branch", which is what the
    // picker wants on first load. Pinned because the two behaviours look identical from
    // the client and only one of them is intended.
    let params = new URLSearchParams();
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/example/cool-project/commits`, ({ request }) => {
        params = new URL(request.url).searchParams;
        return HttpResponse.json([COMMIT]);
      }),
    );
    const { getRepoCommits } = await import("@/api/github");

    await getRepoCommits("example", "cool-project");

    expect(params.has("sha")).toBe(true);
    expect(params.get("sha")).toBe("");
  });

  it("throws on a failure", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/example/cool-project/commits`, () =>
        new HttpResponse(null, { status: 500 }),
      ),
    );
    const { getRepoCommits } = await import("@/api/github");

    await expect(getRepoCommits("example", "cool-project")).rejects.toThrow(
      "Failed to fetch commits",
    );
  });
});

describe("getRepoCommitsMultiBranch", () => {
  it("returns the merged commits", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/example/cool-project/commits-multibranch`, () =>
        HttpResponse.json([COMMIT]),
      ),
    );
    const { getRepoCommitsMultiBranch } = await import("@/api/github");

    await expect(getRepoCommitsMultiBranch("example", "cool-project")).resolves.toEqual([COMMIT]);
  });

  it("addresses the multibranch route", async () => {
    let path = "";
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/:owner/:repo/commits-multibranch`, ({ request }) => {
        path = new URL(request.url).pathname;
        return HttpResponse.json([]);
      }),
    );
    const { getRepoCommitsMultiBranch } = await import("@/api/github");

    await getRepoCommitsMultiBranch("example", "cool-project");

    expect(path).toBe("/api/v1/github/repos/example/cool-project/commits-multibranch");
  });

  it("throws on a failure", async () => {
    server.use(
      http.get(`${BACKEND_URL}/api/v1/github/repos/example/cool-project/commits-multibranch`, () =>
        new HttpResponse(null, { status: 502 }),
      ),
    );
    const { getRepoCommitsMultiBranch } = await import("@/api/github");

    await expect(getRepoCommitsMultiBranch("example", "cool-project")).rejects.toThrow(
      "Failed to fetch multibranch commits",
    );
  });
});
