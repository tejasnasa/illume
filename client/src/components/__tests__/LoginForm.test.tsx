import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LoginForm from "@/components/LoginForm";

/**
 * The component navigates by assigning `window.location.href`, which happy-dom treats as a
 * real navigation. Replacing `location` with a plain object makes the assignment
 * observable; a spy on the property setter is not enough because the value is written, not
 * called.
 */
let assigned: string[] = [];

beforeEach(() => {
  assigned = [];
  Object.defineProperty(window, "location", {
    configurable: true,
    value: new Proxy(
      {},
      {
        set: (_target, property, value) => {
          if (property === "href") assigned.push(String(value));
          return true;
        },
        get: (_target, property) =>
          property === "href" ? (assigned.at(-1) ?? "") : undefined,
      },
    ),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("content", () => {
  it("renders the heading", () => {
    render(<LoginForm />);

    expect(screen.getByRole("heading", { name: "Welcome to Illume" })).toBeInTheDocument();
  });

  it("offers a single GitHub action", () => {
    render(<LoginForm />);

    expect(screen.getByRole("button", { name: /Continue with GitHub/i })).toBeInTheDocument();
  });

  it("offers no email or password field", () => {
    // The live login page is OAuth-only. `useLoginForm` implements a credential flow that
    // no route mounts, so this pins the fact that adding inputs here would be a deliberate
    // change rather than an accident.
    render(<LoginForm />);

    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("states the three guarantees", () => {
    render(<LoginForm />);

    expect(screen.getByText("Read-only")).toBeInTheDocument();
    expect(screen.getByText("Never stored")).toBeInTheDocument();
    expect(screen.getByText("Private repos")).toBeInTheDocument();
  });

  it("links the logo back to the home page", () => {
    render(<LoginForm />);

    expect(screen.getByRole("link")).toHaveAttribute("href", "/");
  });
});

describe("the GitHub action", () => {
  it("navigates to the backend OAuth start URL", async () => {
    // The flow is a full-page redirect, not a fetch: the backend sets a cookie and
    // redirects to github.com, which a same-origin request could not do.
    render(<LoginForm />);

    await userEvent.setup().click(screen.getByRole("button", { name: /Continue with GitHub/i }));

    expect(assigned).toHaveLength(1);
    expect(assigned[0]).toContain("/api/v1/auth/github");
  });

  it("does not navigate on render", () => {
    render(<LoginForm />);

    expect(assigned).toHaveLength(0);
  });

  it("shows a loading state once clicked", async () => {
    // The redirect is not instant, and a second click would start the OAuth flow twice.
    render(<LoginForm />);

    await userEvent.setup().click(screen.getByRole("button", { name: /Continue with GitHub/i }));

    expect(screen.getByRole("button", { name: /Continue with GitHub/i })).toBeDisabled();
  });

  it("is enabled before the click", () => {
    render(<LoginForm />);

    expect(screen.getByRole("button", { name: /Continue with GitHub/i })).toBeEnabled();
  });
});
