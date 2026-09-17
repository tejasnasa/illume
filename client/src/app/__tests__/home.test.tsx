import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "@/app/page";

/**
 * The landing page is a client component that pulls in PNG assets, phosphor icons, and
 * motion. It is the most import-heavy route in the app, so mounting it is a cheap
 * smoke test that the whole client stack still resolves.
 */
describe("landing page", () => {
  it("renders the headline", () => {
    render(<Home />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      /onboard engineers/i,
    );
  });

  it("links to login from the navigation", () => {
    render(<Home />);

    const loginLinks = screen.getAllByRole("link", { name: /login/i });

    expect(loginLinks.length).toBeGreaterThan(0);
    for (const link of loginLinks) {
      expect(link).toHaveAttribute("href", "/login");
    }
  });

  it("renders every feature card", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { name: /architecture brief/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /codebase glossary/i }),
    ).toBeInTheDocument();
  });
});
