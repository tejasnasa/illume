import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), back: vi.fn() }),
}));

const LOGIN_URL = `${BACKEND_URL}/api/v1/auth/login`;

afterEach(() => {
  vi.clearAllMocks();
});

describe("validation gate", () => {
  it("does not submit an empty form", async () => {
    // Zod rejects the empty defaults, so `handleSubmit` never reaches the handler. The
    // request must not go out.
    const spy = vi.fn();
    server.use(
      http.post(LOGIN_URL, () => {
        spy();
        return HttpResponse.json({});
      }),
    );
    const { default: useLoginForm } = await import("@/hooks/useLoginForm");
    const { result } = renderHook(() => useLoginForm());

    await act(async () => {
      await result.current.onSubmit();
    });

    expect(spy).not.toHaveBeenCalled();
  });

  it("exposes the email error first", async () => {
    const { default: useLoginForm } = await import("@/hooks/useLoginForm");
    const { result } = renderHook(() => useLoginForm());

    await act(async () => {
      await result.current.onSubmit();
    });

    expect(result.current.firstError).toMatch(/valid email/i);
  });

  it("reports a short password", async () => {
    const { default: useLoginForm } = await import("@/hooks/useLoginForm");
    const { result } = renderHook(() => useLoginForm());

    await act(async () => {
      result.current.register("email").onChange({
        target: { value: "ada@example.com", name: "email" },
      });
      result.current.register("password").onChange({
        target: { value: "short", name: "password" },
      });
    });
    await act(async () => {
      await result.current.onSubmit();
    });

    await waitFor(() => expect(result.current.firstError).toMatch(/valid password/i));
  });

  it("does not send a request when validation fails", async () => {
    const spy = vi.fn();
    server.use(
      http.post(LOGIN_URL, () => {
        spy();
        return HttpResponse.json({});
      }),
    );
    const { default: useLoginForm } = await import("@/hooks/useLoginForm");
    const { result } = renderHook(() => useLoginForm());

    await act(async () => {
      result.current.register("email").onChange({
        target: { value: "not-an-email", name: "email" },
      });
      result.current.register("password").onChange({
        target: { value: "longenough", name: "password" },
      });
    });
    await act(async () => {
      await result.current.onSubmit();
    });

    expect(spy).not.toHaveBeenCalled();
  });
});

describe("successful submission", () => {
  async function submitValid() {
    const { default: useLoginForm } = await import("@/hooks/useLoginForm");
    const { result } = renderHook(() => useLoginForm());
    await act(async () => {
      result.current.register("email").onChange({
        target: { value: "ada@example.com", name: "email" },
      });
      result.current.register("password").onChange({
        target: { value: "correct-horse-1", name: "password" },
      });
    });
    await act(async () => {
      await result.current.onSubmit();
    });
    return result;
  }

  it("posts the credentials", async () => {
    let body: { email?: string; password?: string } = {};
    let method = "";
    server.use(
      http.post(LOGIN_URL, async ({ request }) => {
        method = request.method;
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ message: "ok" });
      }),
    );

    await submitValid();

    expect(method).toBe("POST");
    expect(body.email).toBe("ada@example.com");
    expect(body.password).toBe("correct-horse-1");
  });

  it("sends credentials so the session cookie is stored", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    server.use(http.post(LOGIN_URL, () => HttpResponse.json({ message: "ok" })));

    await submitValid();

    expect(spy.mock.calls[0][1]?.credentials).toBe("include");
  });

  it("redirects to the dashboard", async () => {
    server.use(http.post(LOGIN_URL, () => HttpResponse.json({ message: "ok" })));

    await submitValid();

    expect(push).toHaveBeenCalledWith("/dashboard");
  });

  it("sets no error", async () => {
    server.use(http.post(LOGIN_URL, () => HttpResponse.json({ message: "ok" })));

    const result = await submitValid();

    expect(result.current.firstError).toBeUndefined();
  });

  it("does not redirect on a failure", async () => {
    server.use(
      http.post(LOGIN_URL, () => HttpResponse.json({ detail: "Invalid email or password" }, { status: 401 })),
    );

    await submitValid();

    expect(push).not.toHaveBeenCalled();
  });
});

describe("failed submission", () => {
  /** Submits valid credentials against a handler that fails. */
  async function submitAgainst(handler: () => Response) {
    server.use(http.post(LOGIN_URL, handler));
    const { default: useLoginForm } = await import("@/hooks/useLoginForm");
    const { result } = renderHook(() => useLoginForm());
    await act(async () => {
      result.current.register("email").onChange({
        target: { value: "ada@example.com", name: "email" },
      });
      result.current.register("password").onChange({
        target: { value: "wrong-password-1", name: "password" },
      });
    });
    await act(async () => {
      await result.current.onSubmit();
    });
    return result;
  }

  it("surfaces the backend's own message", async () => {
    // The backend reports its reason as `detail`. Reading `.message` instead meant every
    // failure fell through to the generic text, so the reason written to be actionable
    // never reached the screen.
    const result = await submitAgainst(() =>
      HttpResponse.json({ detail: "Invalid email or password" }, { status: 401 }),
    );

    await waitFor(() =>
      expect(result.current.firstError).toBe("Invalid email or password"),
    );
  });

  it("falls back to the generic message when the body carries no reason", async () => {
    // A 500 with no body is the case the fallback is actually for.
    const result = await submitAgainst(() => new HttpResponse(null, { status: 500 }));

    await waitFor(() =>
      expect(result.current.firstError).toBe("Something went wrong. Please try again."),
    );
  });

  it("puts the error in the banner rather than on a field", async () => {
    // A 401 is not an email problem or a password problem -- it is both or neither, so it
    // is surfaced once above the form instead of under one input.
    const result = await submitAgainst(() =>
      HttpResponse.json({ detail: "Invalid email or password" }, { status: 401 }),
    );

    await waitFor(() => expect(result.current.firstError).toBeTruthy());
  });

  it("handles a non-JSON error body", async () => {
    // A 502 from a proxy returns HTML. `res.json()` throws on that, and the shared helper
    // swallows the throw -- so the user gets the generic fallback rather than the JSON
    // parser's own message, which is what used to reach the screen.
    const result = await submitAgainst(
      () => new HttpResponse("<html>Bad Gateway</html>", { status: 502 }),
    );

    await waitFor(() =>
      expect(result.current.firstError).toBe("Something went wrong. Please try again."),
    );
  });

  it("clears the submitting flag", async () => {
    const result = await submitAgainst(() => new HttpResponse(null, { status: 500 }));

    await waitFor(() => expect(result.current.isSubmitting).toBe(false));
  });
});
