import { act, renderHook } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

/**
 * `useRouter` only works inside the Next.js app router, so it is stubbed with a spy.
 *
 * Asserting on the spy rather than on real navigation is the point: the redirect target
 * is the contract, and it is a string.
 */
const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), back: vi.fn() }),
}));

afterEach(() => {
  vi.clearAllMocks();
});

describe("useLogout", () => {
  it("returns a function", async () => {
    const { useLogout } = await import("@/hooks/useLogout");
    const { result } = renderHook(() => useLogout());

    expect(typeof result.current).toBe("function");
  });

  it("posts to the logout endpoint", async () => {
    let method = "";
    let path = "";
    server.use(
      http.post(`${BACKEND_URL}/api/v1/auth/logout`, ({ request }) => {
        method = request.method;
        path = new URL(request.url).pathname;
        return HttpResponse.json({ message: "Logged out" });
      }),
    );
    const { useLogout } = await import("@/hooks/useLogout");
    const { result } = renderHook(() => useLogout());

    await act(async () => {
      await result.current();
    });

    expect(method).toBe("POST");
    expect(path).toBe("/api/v1/auth/logout");
  });

  it("sends credentials so the session cookie is cleared", async () => {
    // The backend clears the cookie by setting an expired one on the response. Without
    // `credentials: "include"` the browser would neither send the old cookie nor accept
    // the replacement, and logout would silently do nothing.
    //
    // Asserted on the fetch init rather than on the request headers: MSW's request object
    // does not expose `credentials`, and happy-dom has no cookie jar to observe.
    const spy = vi.spyOn(globalThis, "fetch");
    server.use(
      http.post(`${BACKEND_URL}/api/v1/auth/logout`, () => HttpResponse.json({ message: "ok" })),
    );
    const { useLogout } = await import("@/hooks/useLogout");
    const { result } = renderHook(() => useLogout());

    await act(async () => {
      await result.current();
    });

    expect(spy.mock.calls[0][1]?.credentials).toBe("include");
  });

  it("redirects to the login page", async () => {
    server.use(
      http.post(`${BACKEND_URL}/api/v1/auth/logout`, () => HttpResponse.json({ message: "ok" })),
    );
    const { useLogout } = await import("@/hooks/useLogout");
    const { result } = renderHook(() => useLogout());

    await act(async () => {
      await result.current();
    });

    expect(push).toHaveBeenCalledWith("/login");
  });

  it("does not redirect when the request fails", async () => {
    // `await fetch(...)` sits before `router.push`, so a rejection skips the navigation
    // and propagates to the caller -- which, for a bare `onClick={logout}` handler, means
    // an unhandled rejection and a button that appears to do nothing.
    //
    // Defensible as written: if the session cookie was not cleared, redirecting to /login
    // would only bounce the user back through the proxy. What is missing is any feedback
    // that the attempt failed, not the navigation itself.
    server.use(http.post(`${BACKEND_URL}/api/v1/auth/logout`, () => HttpResponse.error()));
    const { useLogout } = await import("@/hooks/useLogout");
    const { result } = renderHook(() => useLogout());

    await act(async () => {
      await result.current().catch(() => {});
    });

    expect(push).not.toHaveBeenCalled();
  });

  it("propagates the rejection rather than swallowing it", async () => {
    // Pinned separately because the two are independent: the hook could stop redirecting
    // and start catching, or the reverse, and only one of those is a behaviour change.
    server.use(http.post(`${BACKEND_URL}/api/v1/auth/logout`, () => HttpResponse.error()));
    const { useLogout } = await import("@/hooks/useLogout");
    const { result } = renderHook(() => useLogout());

    await expect(
      act(async () => {
        await result.current();
      }),
    ).rejects.toThrow();
  });

  it("does not redirect before the request settles", async () => {
    let resolveRequest: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      resolveRequest = resolve;
    });
    server.use(
      http.post(`${BACKEND_URL}/api/v1/auth/logout`, async () => {
        await gate;
        return HttpResponse.json({ message: "ok" });
      }),
    );
    const { useLogout } = await import("@/hooks/useLogout");
    const { result } = renderHook(() => useLogout());

    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current();
    });

    expect(push).not.toHaveBeenCalled();

    await act(async () => {
      resolveRequest();
      await pending;
    });

    expect(push).toHaveBeenCalledWith("/login");
  });
});
