/**
 * Tests for the repository transport helpers.
 *
 * The dashboard's HTTP surface lives in :mod:`src.api.repository` --
 * thin wrappers around :func:`apiGet` that hit the listing and detail
 * endpoints. These tests pin the URLs so a typo in a path (e.g.
 * ``/api/v1/repositories`` plural) is caught before it ships.
 */

import { getRepositories, getRepository } from "@/api/repository";

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

function makeFetchReturning(body: unknown): jest.Mock {
  return jest.fn(async () =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
}

describe("getRepositories", () => {
  it("hits the listing path", async () => {
    const fetchImpl = makeFetchReturning([]) as unknown as typeof fetch;
    await getRepositories({ backendUrl: "http://api.test:8000", fetchImpl });
    const [url] = (fetchImpl as unknown as jest.Mock).mock.calls[0];
    expect(url).toBe("http://api.test:8000/api/v1/repository");
  });

  it("returns the parsed array on a 200 response", async () => {
    const fetchImpl = makeFetchReturning([{ id: "r1", name: "r1" }]) as unknown as typeof fetch;
    const result = await getRepositories({
      backendUrl: "http://api.test:8000",
      fetchImpl,
    });
    expect(result).toEqual([{ id: "r1", name: "r1" }]);
  });
});

describe("getRepository", () => {
  it("hits the detail path with the supplied id", async () => {
    const fetchImpl = makeFetchReturning({ id: "r1" }) as unknown as typeof fetch;
    await getRepository(42, {
      backendUrl: "http://api.test:8000",
      fetchImpl,
    });
    const [url] = (fetchImpl as unknown as jest.Mock).mock.calls[0];
    expect(url).toBe("http://api.test:8000/api/v1/repository/42");
  });

  it("accepts a string id and forwards it on the path", async () => {
    const fetchImpl = makeFetchReturning({ id: "r1" }) as unknown as typeof fetch;
    await getRepository("abc", {
      backendUrl: "http://api.test:8000",
      fetchImpl,
    });
    const [url] = (fetchImpl as unknown as jest.Mock).mock.calls[0];
    expect(url).toBe("http://api.test:8000/api/v1/repository/abc");
  });
});
