/**
 * Tests for the typed error surface used by :mod:`src.api.client`.
 *
 * The error class is what every React Query ``queryFn`` rejects with, so
 * the kind discriminator is the contract the rest of the app branches on.
 */

import { ApiError, kindFromStatus } from "@/lib/apiError";

describe("kindFromStatus", () => {
  it("classifies 401 and 403 as unauthorized", () => {
    expect(kindFromStatus(401)).toBe("unauthorized");
    expect(kindFromStatus(403)).toBe("unauthorized");
  });

  it("classifies 404 as notFound", () => {
    expect(kindFromStatus(404)).toBe("notFound");
  });

  it("classifies other 4xx as clientError", () => {
    expect(kindFromStatus(400)).toBe("clientError");
    expect(kindFromStatus(409)).toBe("clientError");
    expect(kindFromStatus(422)).toBe("clientError");
  });

  it("classifies 5xx as server", () => {
    expect(kindFromStatus(500)).toBe("server");
    expect(kindFromStatus(502)).toBe("server");
    expect(kindFromStatus(503)).toBe("server");
  });

  it("returns unknown for 2xx / 3xx", () => {
    expect(kindFromStatus(200)).toBe("unknown");
    expect(kindFromStatus(302)).toBe("unknown");
  });
});

describe("ApiError", () => {
  it("is an Error subclass with the given kind", () => {
    const error = new ApiError({
      kind: "unauthorized",
      message: "Sign in again",
      status: 401,
    });
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("ApiError");
    expect(error.kind).toBe("unauthorized");
    expect(error.status).toBe(401);
    expect(error.message).toBe("Sign in again");
  });

  it("preserves body and cause when provided", () => {
    const cause = new Error("ECONNREFUSED");
    const error = new ApiError({
      kind: "network",
      message: "Network request failed",
      cause,
      body: { hint: "check the backend" },
    });
    expect(error.cause).toBe(cause);
    expect(error.body).toEqual({ hint: "check the backend" });
  });
});
