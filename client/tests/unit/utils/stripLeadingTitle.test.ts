import { describe, expect, it } from "vitest";

import { stripLeadingTitle } from "@/utils/stripLeadingTitle";

describe("stripLeadingTitle", () => {
  it("drops an opening title", () => {
    expect(stripLeadingTitle("# Architecture Summary: Illume\n\nIllume clones a repo.")).toBe(
      "Illume clones a repo.",
    );
  });

  it("drops several opening headings and blank lines", () => {
    expect(stripLeadingTitle("\n## Overview\n### Illume\nBody.")).toBe("Body.");
  });

  it("keeps headings after the first paragraph", () => {
    const text = "Body.\n\n## Flow\nMore.";
    expect(stripLeadingTitle(text)).toBe(text);
  });

  it("does not treat a hashtag as a heading", () => {
    expect(stripLeadingTitle("#tag starts here")).toBe("#tag starts here");
  });
});
