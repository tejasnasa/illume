import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../msw/handlers";
import { server } from "../../msw/server";

const CONTACT_URL = `${BACKEND_URL}/api/v1/contact`;

/**
 * Registers values for the named fields at once.
 *
 * Typed against the hook's own shape with `register` narrowed to its return value,
 * because `UseFormRegister` is generic over the field-name union and the helper passes
 * names as plain strings.
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
    result.current
      .register(name as never)
      .onChange({ target: { value, name } });
  }
}

const VALID = {
  category: "bug",
  name: "Ada Lovelace",
  email: "ada@example.com",
  message: "The graph view does not render on a large repository.",
  illume_hp: "",
};

/** Mounts the hook with a valid payload already in the form. */
async function submitValid(
  overrides: Record<string, string> = {},
  defaults?: { name?: string; email?: string },
) {
  const { default: useContactForm } = await import("@/hooks/useContactForm");
  const { result } = renderHook(() => useContactForm(defaults));
  await act(async () => {
    fill(result, { ...VALID, ...overrides });
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
      http.post(CONTACT_URL, () => {
        spy();
        return HttpResponse.json({});
      }),
    );
    const { default: useContactForm } = await import("@/hooks/useContactForm");
    const { result } = renderHook(() => useContactForm());

    await act(async () => {
      await result.current.onSubmit();
    });

    expect(spy).not.toHaveBeenCalled();
  });

  it("asks for a category before anything else", async () => {
    // Category is the first field in the layout and the only one an untouched form gets
    // wrong, so it is the message the banner should show.
    const { default: useContactForm } = await import("@/hooks/useContactForm");
    const { result } = renderHook(() => useContactForm());

    await act(async () => {
      await result.current.onSubmit();
    });

    expect(result.current.firstError).toMatch(/pick a category/i);
  });

  it("rejects a message that is too short", async () => {
    const spy = vi.fn();
    server.use(
      http.post(CONTACT_URL, () => {
        spy();
        return HttpResponse.json({});
      }),
    );

    const result = await submitValid({ message: "nope" });

    await waitFor(() =>
      expect(result.current.firstError).toMatch(/at least 10 characters/i),
    );
    expect(spy).not.toHaveBeenCalled();
  });

  it("rejects a malformed email", async () => {
    const result = await submitValid({ email: "not-an-email" });

    await waitFor(() =>
      expect(result.current.firstError).toMatch(/valid email/i),
    );
  });
});

describe("successful submission", () => {
  it("posts every field including the honeypot", async () => {
    // The honeypot is only a control if it reaches the server. Dropping it here would
    // leave a decoy in the markup that the endpoint never sees.
    let body: Record<string, string> = {};
    let method = "";
    server.use(
      http.post(CONTACT_URL, async ({ request }) => {
        method = request.method;
        body = (await request.json()) as Record<string, string>;
        return HttpResponse.json({ message: "ok" });
      }),
    );

    await submitValid();

    expect(method).toBe("POST");
    expect(body).toEqual(VALID);
  });

  it("sends a filled honeypot through rather than stripping it", async () => {
    // The client must stay indifferent to the decoy. Discarding it locally would leave
    // the submission looking legitimate to a bot that reads the response.
    let body: Record<string, string> = {};
    server.use(
      http.post(CONTACT_URL, async ({ request }) => {
        body = (await request.json()) as Record<string, string>;
        return HttpResponse.json({ message: "ok" });
      }),
    );

    await submitValid({ illume_hp: "https://spam.example" });

    expect(body.illume_hp).toBe("https://spam.example");
  });

  it("sends credentials so a signed-in visitor is attributed", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    server.use(
      http.post(CONTACT_URL, () => HttpResponse.json({ message: "ok" })),
    );

    await submitValid();

    expect(spy.mock.calls[0][1]?.credentials).toBe("include");
  });

  it("confirms delivery with an inline success banner", async () => {
    server.use(
      http.post(CONTACT_URL, () => HttpResponse.json({ message: "ok" })),
    );

    const result = await submitValid();

    // The hook surfaces a success message the form renders; the test reads it back
    // from the hook rather than the DOM because the test file pairs with a form-level
    // test that covers the rendered banner.
    await waitFor(() =>
      expect(result.current.successMessage).toMatch(/we'll reply by email/i),
    );
  });

  it("sets no error", async () => {
    server.use(
      http.post(CONTACT_URL, () => HttpResponse.json({ message: "ok" })),
    );

    const result = await submitValid();

    expect(result.current.firstError).toBeUndefined();
  });
});

describe("identity prefill", () => {
  it("prefills the name and email it is given", async () => {
    let body: Record<string, string> = {};
    server.use(
      http.post(CONTACT_URL, async ({ request }) => {
        body = (await request.json()) as Record<string, string>;
        return HttpResponse.json({ message: "ok" });
      }),
    );

    const { default: useContactForm } = await import("@/hooks/useContactForm");
    const { result } = renderHook(() =>
      useContactForm({ name: "Grace Hopper", email: "grace@example.com" }),
    );
    await act(async () => {
      fill(result, {
        category: "other",
        message: "A question about reading order.",
      });
    });
    await act(async () => {
      await result.current.onSubmit();
    });

    expect(body.name).toBe("Grace Hopper");
    expect(body.email).toBe("grace@example.com");
  });
});

describe("failed submission", () => {
  it("surfaces the backend's own message", async () => {
    // "The contact form is not accepting messages right now" tells the visitor to email
    // instead. Reading `.message` from a body that carries `detail` dropped it.
    server.use(
      http.post(CONTACT_URL, () =>
        HttpResponse.json(
          { detail: "The contact form is not accepting messages right now." },
          { status: 503 },
        ),
      ),
    );

    const result = await submitValid();

    await waitFor(() =>
      expect(result.current.firstError).toBe(
        "The contact form is not accepting messages right now.",
      ),
    );
  });

  it("surfaces a delivery failure distinctly from a rejection", async () => {
    server.use(
      http.post(CONTACT_URL, () =>
        HttpResponse.json(
          {
            detail: "Could not deliver your message. Please try again shortly.",
          },
          { status: 502 },
        ),
      ),
    );

    const result = await submitValid();

    await waitFor(() =>
      expect(result.current.firstError).toMatch(/could not deliver/i),
    );
  });

  it("does not report success when delivery failed", async () => {
    // The whole point of failing loudly: a swallowed error would tell the visitor their
    // message was sent while it existed nowhere.
    server.use(
      http.post(CONTACT_URL, () => new HttpResponse(null, { status: 502 })),
    );

    const result = await submitValid();

    expect(result.current.successMessage).toBeNull();
  });

  it("falls back to the generic message when the body carries no reason", async () => {
    server.use(
      http.post(CONTACT_URL, () => new HttpResponse(null, { status: 500 })),
    );

    const result = await submitValid();

    await waitFor(() =>
      expect(result.current.firstError).toBe(
        "Something went wrong. Please try again.",
      ),
    );
  });

  it("clears the submitting flag after a failure", async () => {
    server.use(
      http.post(CONTACT_URL, () => new HttpResponse(null, { status: 500 })),
    );

    const result = await submitValid();

    await waitFor(() => expect(result.current.isSubmitting).toBe(false));
  });
});
