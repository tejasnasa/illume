import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import GlossaryLetters, { parseInitial } from "@/components/ui/GlossaryLetters";

const hrefFor = (letter: string | null) => (letter ? `/g?letter=${letter}` : "/g");

describe("parseInitial", () => {
  it.each([
    ["c", "C"],
    ["Z", "Z"],
    ["#", "#"],
  ])("accepts %s as %s", (raw, parsed) => {
    expect(parseInitial(raw)).toBe(parsed);
  });

  it.each([undefined, "", "ab", "1", "é"])("rejects %s", (raw) => {
    expect(parseInitial(raw)).toBeNull();
  });
});

describe("GlossaryLetters", () => {
  it("links the initials that have terms and leaves the rest inert", () => {
    render(<GlossaryLetters active={null} present={["C", "#"]} hrefFor={hrefFor} />);

    expect(screen.getByRole("link", { name: "C" })).toHaveAttribute("href", "/g?letter=C");
    expect(screen.getByRole("link", { name: "Other" })).toHaveAttribute("href", "/g?letter=#");
    expect(screen.queryByRole("link", { name: "D" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("D, no terms")).toHaveAttribute("aria-disabled", "true");
  });

  it("marks the active initial, and All when there is none", () => {
    const { rerender } = render(
      <GlossaryLetters active={null} present={["C"]} hrefFor={hrefFor} />,
    );
    expect(screen.getByRole("link", { name: "All" })).toHaveAttribute("aria-current", "page");

    rerender(<GlossaryLetters active="C" present={["C"]} hrefFor={hrefFor} />);
    expect(screen.getByRole("link", { name: "C" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "All" })).not.toHaveAttribute("aria-current");
  });
});
