/**
 * Tests for the repository creation transport.
 *
 * The create endpoint has a naming asymmetry the rest of the app has to
 * respect: the response calls the user-scoped integer ``repo_num`` while
 * the repository record itself calls it ``repo_number``. Pinning the
 * request body shape here keeps the two from being conflated.
 */

import { createRepository, getRepositories } from "@/api/repository";

import { __setTokenStoreImplementation } from "@/lib/tokenStore";

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

describe("createRepository", () => {
  it("posts to the collection path", async () => {
    const fetchImpl = makeFetch(jsonResponse(202, { repo_num: 7 }));
    await createRepository(
      { github_url: "https://github.com/owner/name" },
      {
        backendUrl: "http://api.test:8000",
        fetchImpl: fetchImpl as unknown as typeof fetch,
      },
    );

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://api.test:8000/api/v1/repository");
    expect(init.method).toBe("POST");
  });

  it("sends the branch and commit when they are set", async () => {
    const fetchImpl = makeFetch(jsonResponse(202, { repo_num: 7 }));
    await createRepository(
      {
        github_url: "https://github.com/owner/name",
        branch: "main",
        commit_sha: "abc1234",
      },
      {
        backendUrl: "http://api.test:8000",
        fetchImpl: fetchImpl as unknown as typeof fetch,
      },
    );

    const [, init] = fetchImpl.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({
      github_url: "https://github.com/owner/name",
      branch: "main",
      commit_sha: "abc1234",
    });
  });

  it("returns the created repository's identifiers", async () => {
    const fetchImpl = makeFetch(
      jsonResponse(202, { repo_id: "uuid-1", repo_num: 42 }),
    );
    const result = await createRepository(
      { github_url: "https://github.com/owner/name" },
      {
        backendUrl: "http://api.test:8000",
        fetchImpl: fetchImpl as unknown as typeof fetch,
      },
    );
    expect(result).toEqual({ repo_id: "uuid-1", repo_num: 42 });
  });

  it("propagates a 402 as a quota error", async () => {
    const fetchImpl = makeFetch(
      jsonResponse(402, { detail: "Add your own API key to ingest another repository." }),
    );
    await expect(
      createRepository(
        { github_url: "https://github.com/owner/name" },
        {
          backendUrl: "http://api.test:8000",
          fetchImpl: fetchImpl as unknown as typeof fetch,
        },
      ),
    ).rejects.toMatchObject({ kind: "quota", status: 402 });
  });
});

describe("getRepositories", () => {
  it("still hits the listing path", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, []));
    await getRepositories({
      backendUrl: "http://api.test:8000",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe("http://api.test:8000/api/v1/repository");
  });
});
