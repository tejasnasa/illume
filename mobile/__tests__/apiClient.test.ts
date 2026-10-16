/**
 * Tests for the token-injecting :mod:`src.api.client` wrapper.
 *
 * Three contracts matter:
 *
 * - The bearer token is read from the secure store on every request.
 * - Non-2xx responses become :class:`ApiError` instances with the right
 *   ``kind`` (a 401 is distinguishable from a 500; a network failure is
 *   distinguishable from both).
 * - The :func:`fetch` global is what the client uses by default -- it
 *   is the runtime surface React Query query functions will hit.
 *
 * Tests inject a mock ``fetch`` rather than going through the global, so
 * the suite runs in jest-expo without binding to a real network.
 */

import {
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  apiRequest,
  resolveBackendUrl,
} from "@/api/client";
import { ApiError } from "@/lib/apiError";
import {
  __setTokenStoreImplementation,
} from "@/lib/tokenStore";

const BACKEND = "http://api.test:8000";

function makeFetch(response: Response | (() => Response)): jest.Mock {
  const fn = jest.fn(async () =>
    typeof response === "function" ? response() : response,
  );
  return fn as unknown as jest.Mock;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("apiRequest", () => {
  beforeEach(() => {
    __setTokenStoreImplementation({
      async getItemAsync() {
        return null;
      },
      async setItemAsync() {},
      async deleteItemAsync() {},
    });
  });

  it("resolves with the parsed JSON body on a 200 response", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, { ok: true }));
    const result = await apiRequest<{ ok: boolean }>("/ping", {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(result.status).toBe(200);
    expect(result.body).toEqual({ ok: true });
  });

  it("injects Authorization: Bearer when a token is stored", async () => {
    __setTokenStoreImplementation({
      async getItemAsync() {
        return "jwt-abc";
      },
      async setItemAsync() {},
      async deleteItemAsync() {},
    });
    const fetchImpl = makeFetch(jsonResponse(200, {}));
    await apiRequest("/auth/me", {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [, init] = fetchImpl.mock.calls[0];
    const headers = (init as { headers: Record<string, string> }).headers;
    expect(headers.Authorization).toBe("Bearer jwt-abc");
  });

  it("omits Authorization when no token is stored", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, {}));
    await apiRequest("/auth/me", {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [, init] = fetchImpl.mock.calls[0];
    const headers = (init as { headers: Record<string, string> }).headers;
    expect(headers.Authorization).toBeUndefined();
  });

  it("serialises a JSON body and sets Content-Type", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, {}));
    await apiRequest("/repos", {
      method: "POST",
      body: { github_url: "https://github.com/foo/bar" },
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [, init] = fetchImpl.mock.calls[0];
    const { headers, body } = init as {
      headers: Record<string, string>;
      body: string;
    };
    expect(headers["Content-Type"]).toBe("application/json");
    expect(body).toBe(JSON.stringify({ github_url: "https://github.com/foo/bar" }));
  });

  it("hits the backend URL with the supplied path joined by a single slash", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, {}));
    await apiRequest("/api/v1/auth/me", {
      backendUrl: "http://api.test:8000/",
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [calledUrl] = fetchImpl.mock.calls[0];
    expect(calledUrl).toBe("http://api.test:8000/api/v1/auth/me");
  });

  it("accepts a path without a leading slash", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, {}));
    await apiRequest("api/v1/auth/me", {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [calledUrl] = fetchImpl.mock.calls[0];
    expect(calledUrl).toBe("http://api.test:8000/api/v1/auth/me");
  });

  it("throws an ApiError with kind=unauthorized on a 401", async () => {
    const fetchImpl = makeFetch(
      jsonResponse(401, { detail: "Invalid or expired token" }),
    );
    await expect(
      apiRequest("/auth/me", {
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({
      name: "ApiError",
      kind: "unauthorized",
      status: 401,
    });
  });

  it("throws an ApiError with kind=notFound on a 404", async () => {
    const fetchImpl = makeFetch(jsonResponse(404, { detail: "No such repo" }));
    await expect(
      apiRequest("/repos/123", {
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({
      name: "ApiError",
      kind: "notFound",
      status: 404,
    });
  });

  it("throws an ApiError with kind=server on a 500", async () => {
    const fetchImpl = makeFetch(
      jsonResponse(500, { detail: "Database is on fire" }),
    );
    await expect(
      apiRequest("/chat", {
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({
      name: "ApiError",
      kind: "server",
      status: 500,
    });
  });

  it("throws an ApiError with kind=network when fetch rejects", async () => {
    const cause = new Error("ECONNREFUSED");
    const fetchImpl = jest.fn(async () => {
      throw cause;
    });
    await expect(
      apiRequest("/auth/me", {
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      }),
    ).rejects.toMatchObject({
      name: "ApiError",
      kind: "network",
      cause,
    });
  });

  it("returns undefined body for a 204 No Content response", async () => {
    const fetchImpl = makeFetch(new Response(null, { status: 204 }));
    const result = await apiRequest("/repos/abc", {
      method: "DELETE",
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(result.status).toBe(204);
    expect(result.body).toBeUndefined();
  });

  it("uses the backend detail string as the error message when present", async () => {
    const fetchImpl = makeFetch(
      jsonResponse(409, { detail: "Already ingesting this repo" }),
    );
    let caught: ApiError | null = null;
    try {
      await apiRequest("/repos", {
        method: "POST",
        body: { github_url: "x" },
        backendUrl: BACKEND,
        fetchImpl: fetchImpl as unknown as typeof fetch,
      });
    } catch (e) {
      caught = e as ApiError;
    }
    expect(caught).not.toBeNull();
    expect(caught!.kind).toBe("clientError");
    expect(caught!.message).toContain("Already ingesting");
  });
});

describe("verb helpers", () => {
  beforeEach(() => {
    __setTokenStoreImplementation({
      async getItemAsync() {
        return null;
      },
      async setItemAsync() {},
      async deleteItemAsync() {},
    });
  });

  it("apiGet issues a GET and unwraps the body", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, { id: "r1" }));
    const body = await apiGet<{ id: string }>("/repos/r1", {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(body).toEqual({ id: "r1" });
    const [, init] = fetchImpl.mock.calls[0];
    expect((init as { method: string }).method).toBe("GET");
  });

  it("apiPost issues a POST with a JSON body", async () => {
    const fetchImpl = makeFetch(jsonResponse(202, { ok: true }));
    await apiPost("/repos", { github_url: "x" }, {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [, init] = fetchImpl.mock.calls[0];
    expect((init as { method: string }).method).toBe("POST");
    expect((init as { body: string }).body).toBe(
      JSON.stringify({ github_url: "x" }),
    );
  });

  it("apiPut issues a PUT", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, {}));
    await apiPut("/x", { a: 1 }, {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect((fetchImpl.mock.calls[0][1] as { method: string }).method).toBe("PUT");
  });

  it("apiPatch issues a PATCH", async () => {
    const fetchImpl = makeFetch(jsonResponse(200, {}));
    await apiPatch("/x", { a: 1 }, {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect((fetchImpl.mock.calls[0][1] as { method: string }).method).toBe("PATCH");
  });

  it("apiDelete issues a DELETE", async () => {
    const fetchImpl = makeFetch(new Response(null, { status: 204 }));
    await apiDelete("/x", {
      backendUrl: BACKEND,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect((fetchImpl.mock.calls[0][1] as { method: string }).method).toBe("DELETE");
  });
});

describe("resolveBackendUrl", () => {
  it("strips a trailing slash from an override", () => {
    expect(resolveBackendUrl("http://api.test:8000/")).toBe(
      "http://api.test:8000",
    );
  });

  it("returns the override when given one without trailing slash", () => {
    expect(resolveBackendUrl("https://api.illume.example.com")).toBe(
      "https://api.illume.example.com",
    );
  });

  it("falls back to the Android emulator host when no override is given and the env var is unset", () => {
    const previous = process.env.EXPO_PUBLIC_BACKEND_URL;
    delete process.env.EXPO_PUBLIC_BACKEND_URL;
    try {
      expect(resolveBackendUrl()).toBe("http://10.0.2.2:8000");
    } finally {
      if (previous !== undefined) process.env.EXPO_PUBLIC_BACKEND_URL = previous;
    }
  });
});
