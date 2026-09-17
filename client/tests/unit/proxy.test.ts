import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { proxy } from "@/proxy";

/**
 * Builds a request carrying an optional session cookie.
 *
 * The cookie name must match the one the backend sets; a rename there without a rename
 * here would let every protected route through, so the assertions below are the guard.
 */
function request(path: string, token?: string): NextRequest {
  const req = new NextRequest(new URL(path, "http://localhost:3000"));
  if (token) {
    req.cookies.set("access_token", token);
  }
  return req;
}

/** True when the proxy decided to redirect rather than pass the request through. */
function redirects(response: Response): boolean {
  return response.status >= 300 && response.status < 400;
}

function locationOf(response: Response): string {
  return new URL(response.headers.get("location")!).pathname;
}

describe("unauthenticated requests", () => {
  it.each(["/dashboard", "/repo/abc123", "/repo/abc123/explorer"])(
    "redirects %s to the login page",
    (path) => {
      const response = proxy(request(path));

      expect(redirects(response)).toBe(true);
      expect(locationOf(response)).toBe("/login");
    },
  );

  it.each(["/", "/login"])("passes %s through", (path) => {
    const response = proxy(request(path));

    expect(redirects(response)).toBe(false);
  });

  it("treats an empty cookie value as no session", () => {
    const response = proxy(request("/dashboard", ""));

    expect(locationOf(response)).toBe("/login");
  });
});

describe("authenticated requests", () => {
  it("passes protected routes through", () => {
    const response = proxy(request("/dashboard", "a-token"));

    expect(redirects(response)).toBe(false);
  });

  it("redirects the login page to the dashboard", () => {
    const response = proxy(request("/login", "a-token"));

    expect(redirects(response)).toBe(true);
    expect(locationOf(response)).toBe("/dashboard");
  });

  it("redirects the landing page to the dashboard", () => {
    const response = proxy(request("/", "a-token"));

    expect(locationOf(response)).toBe("/dashboard");
  });
});

describe("route matching boundaries", () => {
  it("protects paths nested under /repo", () => {
    const response = proxy(request("/repo/1/graph/deeply/nested"));

    expect(locationOf(response)).toBe("/login");
  });

  /**
   * Documents a real over-match rather than endorsing it.
   *
   * Protected routes are matched with `startsWith`, so any path sharing a prefix is
   * gated too: `/dashboards-public` is treated as `/dashboard`. The failure is
   * fail-closed (an unauthenticated visitor is sent to login, and an authenticated one
   * gets through), so it is a nuisance rather than a hole. Tightening to a segment-exact
   * match would fix it, but this test pins today's behaviour so the change is deliberate.
   */
  it("over-matches paths that share a prefix with a protected route", () => {
    const response = proxy(request("/dashboards-public"));

    expect(locationOf(response)).toBe("/login");
  });

  it("does not gate an unrelated path", () => {
    const response = proxy(request("/pricing"));

    expect(redirects(response)).toBe(false);
  });
});
