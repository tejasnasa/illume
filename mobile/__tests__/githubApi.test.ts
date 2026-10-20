/**
 * Tests for the GitHub proxy transport.
 *
 * The picker is the only screen that talks to GitHub, and it does so
 * through three endpoints. These tests pin the URLs (a wrong path is a
 * silent 404 at runtime) and the error rewriting, which is where the
 * user-visible difference between "GitHub is not linked" and "GitHub is
 * unreachable" is decided.
 */

import {
  GITHUB_NOT_LINKED_MESSAGE,
  GITHUB_REPOS_PER_PAGE,
  getMyGitHubRepos,
  getRepoBranches,
  getRepoCommitsMultiBranch,
} from "@/api/github";
import { ApiError } from "@/lib/apiError";

import { __setTokenStoreImplementation } from "@/lib/tokenStore";

const BACKEND = "http://api.test:8000";

beforeEach(() => {
  __setTokenStoreImplementation({
    async getItemAsync() {
      return null;
    },
    async setItemAsync() {},
    async deleteItemAsync() {},
  });
});

function makeFetch(response: Response | (() => Response)): jest.Mock {
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

describe("getMyGitHubRepos", () => {
  it("hits the proxy listing path with the page and page size", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, []));
    await getMyGitHubRepos(2, {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      `${BACKEND}/api/v1/github/repos?page=2&per_page=${GITHUB_REPOS_PER_PAGE}`,
    );
  });

  it("defaults to the first page", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, []));
    await getMyGitHubRepos(undefined, {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toContain("page=1");
  });

  it("returns the parsed array on a 200 response", async () => {
    const repos = [{ full_name: "owner/name", name: "name" }];
    const fetchImpl = makeFetch(jsonResponse(200, repos));
    const result = await getMyGitHubRepos(1, {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(result).toEqual(repos);
  });

  it("rewrites a 403 into the not-linked message", async () => {
    const fetchImpl = makeFetch(jsonResponse(403, { detail: "nope" }));
    await expect(
      getMyGitHubRepos(1, {
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
      message: GITHUB_NOT_LINKED_MESSAGE,
    });
  });

  it("keeps the server's detail for other failures", async () => {
    const fetchImpl = makeFetch(
      jsonResponse(404, { detail: "Repository not found on GitHub" }),
    );
    await expect(
      getMyGitHubRepos(1, {
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({
      message: "Repository not found on GitHub",
    });
  });

  it("falls back to a generic message when the server sent no detail", async () => {
    const fetchImpl = makeFetch(jsonResponse(502, {}));
    await expect(
      getMyGitHubRepos(1, {
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({
      message: "Failed to fetch GitHub repositories",
    });
  });
});

describe("getRepoBranches", () => {
  it("hits the branches path with the owner and repo", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, []));
    await getRepoBranches("owner", "name", {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BACKEND}/api/v1/github/repos/owner/name/branches`);
  });

  it("rewrites a 403 into the not-linked message", async () => {
    const fetchImpl = makeFetch(jsonResponse(403, { detail: "nope" }));
    await expect(
      getRepoBranches("owner", "name", {
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({ message: GITHUB_NOT_LINKED_MESSAGE });
  });
});

describe("getRepoCommitsMultiBranch", () => {
  it("hits the multibranch commits path", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, []));
    await getRepoCommitsMultiBranch("owner", "name", {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      `${BACKEND}/api/v1/github/repos/owner/name/commits-multibranch`,
    );
  });

  it("surfaces a network failure as an ApiError", async () => {
    const fetchImpl = jest.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    await expect(
      getRepoCommitsMultiBranch("owner", "name", {
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
