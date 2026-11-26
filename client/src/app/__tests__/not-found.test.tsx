import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NotFound from "@/app/not-found";

describe("not found page", () => {
  it("says the page was not found, and why a repository link might be stale", () => {
    render(<NotFound />);

    expect(
      screen.getByRole("heading", { name: /page not found/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/link to a\s+repository/i)).toBeInTheDocument();
  });

  it("offers a route back to the dashboard", () => {
    render(<NotFound />);

    expect(screen.getByRole("link", { name: /back to dashboard/i })).toHaveAttribute(
      "href",
      "/dashboard",
    );
  });
});
