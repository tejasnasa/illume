import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Login from "@/app/login/page";

/**
 * The login page is GitHub-OAuth only. There is no email/password form on this route,
 * despite hooks like `useLoginForm` existing in the tree unused.
 */
describe("login page", () => {
  it("mounts the OAuth entry point", () => {
    render(<Login />);

    expect(
      screen.getByRole("button", { name: /continue with github/i }),
    ).toBeInTheDocument();
  });

  it("renders the welcome heading", () => {
    render(<Login />);

    expect(
      screen.getByRole("heading", { name: /welcome to illume/i }),
    ).toBeInTheDocument();
  });

  it("states what the GitHub permission is used for", () => {
    render(<Login />);

    for (const label of ["Read-only", "Never stored", "Private repos"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});
