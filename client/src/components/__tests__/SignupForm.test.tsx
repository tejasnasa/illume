import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../../tests/msw/handlers";
import { server } from "../../../tests/msw/server";
import SignupForm from "@/components/SignupForm";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), back: vi.fn() }),
}));

/** Captures the `window.location.href` assignment the OAuth button makes. */
let assigned: string[] = [];

beforeEach(() => {
  assigned = [];
  Object.defineProperty(window, "location", {
    configurable: true,
    value: new Proxy(
      {},
      {
        set: (_t, property, value) => {
          if (property === "href") assigned.push(String(value));
          return true;
        },
        get: (_t, property) => (property === "href" ? (assigned.at(-1) ?? "") : undefined),
      },
    ),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

const REGISTER_URL = `${BACKEND_URL}/api/v1/auth/register`;

/** Fills every field with values the schema accepts. */
async function fillValid(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Name"), "Ada Lovelace");
  await user.type(screen.getByLabelText("Email"), "ada@example.com");
  await user.type(screen.getByLabelText("Password"), "correct-horse-1!");
}

describe("the form", () => {
  it("labels every field", () => {
    // Labels are what make the inputs reachable by name -- for a screen reader and for
    // these tests. An `id` without a matching `htmlFor` would break both.
    render(<SignupForm />);

    expect(screen.getByLabelText("Name")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("uses the right input types", () => {
    render(<SignupForm />);

    expect(screen.getByLabelText("Email")).toHaveAttribute("type", "email");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Name")).toHaveAttribute("type", "text");
  });

  it("renders a submit button", () => {
    render(<SignupForm />);

    expect(screen.getByRole("button", { name: /SIGN UP/i })).toBeInTheDocument();
  });

  it("offers a GitHub alternative", () => {
    render(<SignupForm />);

    expect(screen.getByRole("button", { name: /GitHub/i })).toBeInTheDocument();
  });

  it("shows no error before submission", () => {
    render(<SignupForm />);

    expect(screen.queryByText(/Something went wrong/)).not.toBeInTheDocument();
    expect(screen.queryByText(/at least/)).not.toBeInTheDocument();
  });
});

describe("client-side validation", () => {
  it("rejects an empty submission", async () => {
    const spy = vi.fn();
    server.use(
      http.post(REGISTER_URL, () => {
        spy();
        return HttpResponse.json({});
      }),
    );
    const user = userEvent.setup();
    render(<SignupForm />);

    await user.click(screen.getByRole("button", { name: /SIGN UP/i }));

    await waitFor(() => expect(screen.getByText(/at least 2 characters/i)).toBeInTheDocument());
    expect(spy).not.toHaveBeenCalled();
  });

  it("does not submit a malformed email", async () => {
    // The input is `type="email"`, so the browser's own constraint validation refuses the
    // submission before React's handler runs -- the zod message never appears, because
    // zod is never reached. Asserted on the outcome that matters (no request), not on
    // which layer rejected it.
    const spy = vi.fn();
    server.use(
      http.post(REGISTER_URL, () => {
        spy();
        return HttpResponse.json({});
      }),
    );
    const user = userEvent.setup();
    render(<SignupForm />);

    await user.type(screen.getByLabelText("Name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "not-an-email");
    await user.type(screen.getByLabelText("Password"), "correct-horse-1!");
    await user.click(screen.getByRole("button", { name: /SIGN UP/i }));

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(spy).not.toHaveBeenCalled();
  });

  it("rejects a password with no number", async () => {
    const user = userEvent.setup();
    render(<SignupForm />);

    await user.type(screen.getByLabelText("Name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "onlyletters!");
    await user.click(screen.getByRole("button", { name: /SIGN UP/i }));

    await waitFor(() => expect(screen.getByText(/at least one number/i)).toBeInTheDocument());
  });

  it("shows only one message at a time", async () => {
    // `firstError` picks the first of name/email/password, so a form with three problems
    // shows one banner rather than three.
    const user = userEvent.setup();
    render(<SignupForm />);

    await user.click(screen.getByRole("button", { name: /SIGN UP/i }));

    await waitFor(() => expect(screen.getAllByText(/at least|valid email/i)).toHaveLength(1));
  });
});

describe("submission", () => {
  it("posts the credentials and lands on the dashboard", async () => {
    server.use(
      http.post(REGISTER_URL, () => HttpResponse.json({ message: "ok" }, { status: 201 })),
    );
    const user = userEvent.setup();
    render(<SignupForm />);

    await fillValid(user);
    await user.click(screen.getByRole("button", { name: /SIGN UP/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"));
  });

  it("sends what was typed", async () => {
    let body: Record<string, string> = {};
    server.use(
      http.post(REGISTER_URL, async ({ request }) => {
        body = (await request.json()) as Record<string, string>;
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    render(<SignupForm />);

    await fillValid(user);
    await user.click(screen.getByRole("button", { name: /SIGN UP/i }));

    await waitFor(() => expect(body.email).toBe("ada@example.com"));
    expect(body.name).toBe("Ada Lovelace");
    expect(body.password).toBe("correct-horse-1!");
  });

  it("shows the backend's reason on a duplicate email", async () => {
    // "Email already registered" is the message that tells the user to log in instead,
    // which is exactly why it is worth surfacing rather than collapsing into the generic
    // banner.
    server.use(
      http.post(REGISTER_URL, () =>
        HttpResponse.json({ detail: "Email already registered" }, { status: 400 }),
      ),
    );
    const user = userEvent.setup();
    render(<SignupForm />);

    await fillValid(user);
    await user.click(screen.getByRole("button", { name: /SIGN UP/i }));

    await waitFor(() =>
      expect(screen.getByText("Email already registered")).toBeInTheDocument(),
    );
  });

  it("does not navigate on a failure", async () => {
    server.use(
      http.post(REGISTER_URL, () => HttpResponse.json({ detail: "nope" }, { status: 500 })),
    );
    const user = userEvent.setup();
    render(<SignupForm />);

    await fillValid(user);
    await user.click(screen.getByRole("button", { name: /SIGN UP/i }));

    await waitFor(() => expect(screen.getByText("nope")).toBeInTheDocument());
    expect(push).not.toHaveBeenCalled();
  });

  it("falls back to the generic banner when the body is not JSON", async () => {
    // A bodyless 500 -- an nginx error page, or a proxy cutting the connection -- makes
    // `res.json()` throw. The shared helper swallows that, so the banner shows the
    // intended fallback rather than the parser's own message, which is what a raw engine
    // error reaching the user looked like.
    server.use(http.post(REGISTER_URL, () => new HttpResponse(null, { status: 500 })));
    const user = userEvent.setup();
    render(<SignupForm />);

    await fillValid(user);
    await user.click(screen.getByRole("button", { name: /SIGN UP/i }));

    await waitFor(() =>
      expect(screen.getByText("Something went wrong. Please try again.")).toBeInTheDocument(),
    );
  });
});

describe("the GitHub alternative", () => {
  it("navigates to the OAuth start URL", async () => {
    render(<SignupForm />);

    await userEvent.setup().click(screen.getByRole("button", { name: /GitHub/i }));

    expect(assigned[0]).toContain("/api/v1/auth/github");
  });

  it("does not submit the form", async () => {
    // The OAuth button sits inside the same form; without an explicit `type` it would
    // behave as a submit and fire the credential handler instead.
    const spy = vi.fn();
    server.use(
      http.post(REGISTER_URL, () => {
        spy();
        return HttpResponse.json({});
      }),
    );
    render(<SignupForm />);

    await userEvent.setup().click(screen.getByRole("button", { name: /GitHub/i }));

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(spy).not.toHaveBeenCalled();
  });
});
