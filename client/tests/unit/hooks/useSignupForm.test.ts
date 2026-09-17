import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), back: vi.fn() }),
}));

const REGISTER_URL = `${BACKEND_URL}/api/v1/auth/register`;

/**
 * Registers values for all three fields at once.
 *
 * The ref is typed against the hook's own shape with `register` narrowed to its return
 * value, because `UseFormRegister` is generic over the field-name union and the helper
 * passes names as plain strings.
 */
function fill(
  result: {
    current: {
      register: (name: never) => {
        onChange: (event: { target: { value: string; name: string } }) => void;
      };
    };
  },
  values: Record<string, string>,
) {
  for (const [name, value] of Object.entries(values)) {
    result.current.register(name as never).onChange({ target: { value, name } });
  }
}

/** Mounts the hook with a valid payload already in the form. */
async function submitValid(overrides: Record<string, string> = {}) {
  const { default: useSignupForm } = await import("@/hooks/useSignupForm");
  const { result } = renderHook(() => useSignupForm());
  await act(async () => {
    fill(result, {
      name: "Ada Lovelace",
      email: "ada@example.com",
      password: "correct-horse-1!",
      ...overrides,
    });
  });
  await act(async () => {
    await result.current.onSubmit();
  });
  return result;
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("validation gate", () => {
  it("does not submit an empty form", async () => {
    const spy = vi.fn();
    server.use(
      http.post(REGISTER_URL, () => {
        spy();
        return HttpResponse.json({});
      }),
    );
    const { default: useSignupForm } = await import("@/hooks/useSignupForm");
    const { result } = renderHook(() => useSignupForm());

    await act(async () => {
      await result.current.onSubmit();
    });

    expect(spy).not.toHaveBeenCalled();
  });

  it("reports the name error first", async () => {
    // The error order in the hook is name, email, password -- so a form with everything
    // wrong shows the name problem, which is the first field in the layout.
    const { default: useSignupForm } = await import("@/hooks/useSignupForm");
    const { result } = renderHook(() => useSignupForm());

    await act(async () => {
      await result.current.onSubmit();
    });

    expect(result.current.firstError).toMatch(/at least 2 characters/i);
  });

  it("rejects a weak password", async () => {
    const spy = vi.fn();
    server.use(
      http.post(REGISTER_URL, () => {
        spy();
        return HttpResponse.json({});
      }),
    );

    const result = await submitValid({ password: "onlyletters" });

    await waitFor(() => expect(result.current.firstError).toMatch(/at least one number/i));
    expect(spy).not.toHaveBeenCalled();
  });

  it("rejects a malformed email", async () => {
    const result = await submitValid({ email: "not-an-email" });

    await waitFor(() => expect(result.current.firstError).toMatch(/valid email/i));
  });

  it("does not require a password confirmation field", async () => {
    // There is no password-confirmation check, because the schema and the form have no
    // `confirmPassword` -- so there is nothing to mismatch. Noted so the gap is visible
    // rather than assumed covered.
    const { signupSchema } = await import("@/types/validators");

    expect(Object.keys(signupSchema.shape)).toEqual(["name", "email", "password"]);
  });
});

describe("successful submission", () => {
  it("posts all three fields", async () => {
    let body: Record<string, string> = {};
    let method = "";
    server.use(
      http.post(REGISTER_URL, async ({ request }) => {
        method = request.method;
        body = (await request.json()) as Record<string, string>;
        return HttpResponse.json({ message: "ok" }, { status: 201 });
      }),
    );

    await submitValid();

    expect(method).toBe("POST");
    expect(body).toEqual({
      name: "Ada Lovelace",
      email: "ada@example.com",
      password: "correct-horse-1!",
    });
  });

  it("redirects to the dashboard", async () => {
    server.use(http.post(REGISTER_URL, () => HttpResponse.json({}, { status: 201 })));

    await submitValid();

    expect(push).toHaveBeenCalledWith("/dashboard");
  });

  it("sends credentials so the session cookie from registration is kept", async () => {
    // Registration logs the new account in, so the response sets the cookie and the
    // request must be willing to accept it.
    const spy = vi.spyOn(globalThis, "fetch");
    server.use(http.post(REGISTER_URL, () => HttpResponse.json({}, { status: 201 })));

    await submitValid();

    expect(spy.mock.calls[0][1]?.credentials).toBe("include");
  });

  it("sets no error", async () => {
    server.use(http.post(REGISTER_URL, () => HttpResponse.json({}, { status: 201 })));

    const result = await submitValid();

    expect(result.current.firstError).toBeUndefined();
  });

  it("does not redirect on a duplicate email", async () => {
    server.use(
      http.post(REGISTER_URL, () =>
        HttpResponse.json({ detail: "Email already registered" }, { status: 400 }),
      ),
    );

    await submitValid();

    expect(push).not.toHaveBeenCalled();
  });
});

describe("failed submission", () => {
  it("surfaces the backend's own message", async () => {
    // "Email already registered" is precisely the message that tells the user to log in
    // instead. Reading `.message` from a body that carries `detail` dropped it.
    server.use(
      http.post(REGISTER_URL, () =>
        HttpResponse.json({ detail: "Email already registered" }, { status: 400 }),
      ),
    );

    const result = await submitValid();

    await waitFor(() => expect(result.current.firstError).toBe("Email already registered"));
  });

  it("falls back to the generic message when the body carries no reason", async () => {
    server.use(http.post(REGISTER_URL, () => new HttpResponse(null, { status: 500 })));

    const result = await submitValid();

    await waitFor(() =>
      expect(result.current.firstError).toBe("Something went wrong. Please try again."),
    );
  });

  it("clears the submitting flag after a failure", async () => {
    server.use(http.post(REGISTER_URL, () => new HttpResponse(null, { status: 500 })));

    const result = await submitValid();

    await waitFor(() => expect(result.current.isSubmitting).toBe(false));
  });
});
