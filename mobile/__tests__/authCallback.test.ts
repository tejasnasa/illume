/**
 * Parser tests for the deep-link callback URL.
 *
 * Pure functions over a string, so no native modules are needed. Exercises
 * the happy path, error path, near-misses, and ``buildAuthorizeUrl``'s
 * assembly of the inverse URL.
 */

import { buildAuthorizeUrl, parseAuthCallback } from "@/lib/authCallback";

describe("parseAuthCallback", () => {
  it("extracts the token from a successful callback", () => {
    const payload = parseAuthCallback(
      "illume://auth/callback?access_token=jwt-test&token_type=Bearer&expires_in=1296000",
    );
    expect(payload.token).toBe("jwt-test");
    expect(payload.tokenType).toBe("Bearer");
    expect(payload.expiresIn).toBe(1296000);
    expect(payload.error).toBeNull();
  });

  it("returns null fields when given a URL with no token", () => {
    const payload = parseAuthCallback("illume://auth/callback?code=foo");
    expect(payload.token).toBeNull();
    expect(payload.tokenType).toBeNull();
    expect(payload.expiresIn).toBeNull();
    expect(payload.error).toBeNull();
  });

  it("reports an error string from the backend", () => {
    const payload = parseAuthCallback(
      "illume://auth/callback?error=access_denied&error_description=user+denied",
    );
    expect(payload.error).toBe("access_denied");
    expect(payload.token).toBeNull();
  });

  it("falls back to error_description when error is absent", () => {
    const payload = parseAuthCallback(
      "illume://auth/callback?error_description=something+broke",
    );
    expect(payload.error).toBe("something broke");
  });

  it("treats an empty access_token as missing", () => {
    const payload = parseAuthCallback("illume://auth/callback?access_token=");
    expect(payload.token).toBeNull();
  });

  it("ignores a non-numeric expires_in", () => {
    const payload = parseAuthCallback(
      "illume://auth/callback?access_token=jwt&expires_in=soon",
    );
    expect(payload.token).toBe("jwt");
    expect(payload.expiresIn).toBeNull();
  });

  it("does not crash on a malformed URL", () => {
    // We never throw -- the callback screen treats a parse failure as
    // "missing token, send the user back to /login".
    expect(() => parseAuthCallback("not even a url")).not.toThrow();
    expect(() => parseAuthCallback("")).not.toThrow();
  });

  it("accepts just the query string", () => {
    const payload = parseAuthCallback("?access_token=qs-token");
    expect(payload.token).toBe("qs-token");
  });

  it("accepts a URL object", () => {
    const url = new URL("illume://auth/callback?access_token=u-token");
    expect(parseAuthCallback(url).token).toBe("u-token");
  });

  it("preserves percent-decoded values", () => {
    const payload = parseAuthCallback(
      "illume://auth/callback?error_description=cookie%20expired",
    );
    expect(payload.error).toBe("cookie expired");
  });
});

describe("buildAuthorizeUrl", () => {
  it("builds the backend's /github URL with state=deep-link", () => {
    expect(buildAuthorizeUrl("http://localhost:8000", "illume://auth/callback")).toBe(
      "http://localhost:8000/api/v1/auth/github?state=illume%3A%2F%2Fauth%2Fcallback",
    );
  });

  it("strips a trailing slash on the backend URL", () => {
    expect(buildAuthorizeUrl("http://localhost:8000/", "illume://auth/callback")).toBe(
      "http://localhost:8000/api/v1/auth/github?state=illume%3A%2F%2Fauth%2Fcallback",
    );
  });

  it("preserves path components on the backend URL", () => {
    expect(buildAuthorizeUrl("https://api.illume.example.com", "illume://auth/callback")).toBe(
      "https://api.illume.example.com/api/v1/auth/github?state=illume%3A%2F%2Fauth%2Fcallback",
    );
  });
});
