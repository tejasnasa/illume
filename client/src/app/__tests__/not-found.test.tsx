import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NotFound from "@/app/not-found";

describe("not found page", () => {
  it("explains that the repository was not found", () => {
    render(<NotFound />);

    expect(
      screen.getByRole("heading", { name: /repository not found/i }),
    ).toBeInTheDocument();
  });

  it("offers a route back to the dashboard", () => {
    render(<NotFound />);

    expect(screen.getByRole("link", { name: /back to dashboard/i })).toHaveAttribute(
      "href",
      "/dashboard",
    );
  });
});
