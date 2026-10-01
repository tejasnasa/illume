import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AppFooter from "@/components/AppFooter";

describe("AppFooter", () => {
  it("links to the contact page", () => {
    render(<AppFooter />);

    expect(screen.getByRole("link", { name: /contact/i })).toHaveAttribute(
      "href",
      "/contact",
    );
  });

  it("links every social profile", () => {
    render(<AppFooter />);

    for (const [label, href] of [
      ["GitHub", "https://github.com/tejasnasa"],
      ["LinkedIn", "https://www.linkedin.com/in/tejasnasa/"],
      ["X", "https://x.com/tejasnasa/"],
    ]) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
  });

  it("carries its own brand mark", () => {
    render(<AppFooter />);

    expect(screen.getByText(/Illume/)).toBeInTheDocument();
  });

  it("pins itself to the bottom of a short page", () => {
    // `mt-auto` is the whole mechanism: the signed-in layouts are full-height flex
    // columns, so this margin absorbs the leftover space on an empty dashboard and the
    // footer stays on screen instead of floating mid-page.
    const { container } = render(<AppFooter />);

    expect(container.querySelector("footer")?.className).toContain("mt-auto");
  });
});
