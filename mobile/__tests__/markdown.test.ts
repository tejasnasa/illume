/**
 * Tests for the inline markdown splitter.
 *
 * The architecture summary is the only markdown the app renders, and it
 * arrives as prose with the occasional emphasis span. The parser has to
 * leave ordinary text alone -- including words that contain an underscore
 * -- and only claim a span when the markers really wrap it.
 */

import { parseInlineMarkdown } from "@/lib/markdown";

/**
 * The text of every segment, joined back together.
 *
 * @param source - The markdown to parse.
 * @returns The plain text of the result.
 */
function plainText(source: string): string {
  return parseInlineMarkdown(source)
    .map((segment) => segment.text)
    .join("");
}

describe("parseInlineMarkdown", () => {
  it("returns a single plain segment for ordinary prose", () => {
    const segments = parseInlineMarkdown(
      "The ingest pipeline clones the repository and parses every file.",
    );

    expect(segments).toHaveLength(1);
    expect(segments[0].text).toBe(
      "The ingest pipeline clones the repository and parses every file.",
    );
    expect(segments[0].bold).toBeUndefined();
  });

  it("splits bold text out of the surrounding prose", () => {
    const segments = parseInlineMarkdown("A **bold** claim.");

    expect(segments).toHaveLength(3);
    expect(segments[0]).toEqual({ text: "A " });
    expect(segments[1]).toEqual({ text: "bold", bold: true });
    expect(segments[2]).toEqual({ text: " claim." });
  });

  it("splits italic text out of the surrounding prose", () => {
    const segments = parseInlineMarkdown("An *italic* claim.");

    expect(segments[1]).toEqual({ text: "italic", italic: true });
  });

  it("marks code spans as code", () => {
    const segments = parseInlineMarkdown("Call `run_full_analysis` first.");

    expect(segments[1]).toEqual({ text: "run_full_analysis", code: true });
  });

  it("keeps a link's label and href", () => {
    const segments = parseInlineMarkdown("See [the repo](https://example.com).");

    expect(segments[1]).toEqual({
      text: "the repo",
      href: "https://example.com",
    });
  });

  it("does not read an underscore inside a word as emphasis", () => {
    const segments = parseInlineMarkdown("The snake_case_name stays intact.");

    expect(segments).toHaveLength(1);
    expect(segments[0].text).toBe("The snake_case_name stays intact.");
  });

  it("reads a standalone underscore span as emphasis", () => {
    const segments = parseInlineMarkdown("An _emphasised_ word.");

    expect(segments[1]).toEqual({ text: "emphasised", italic: true });
  });

  it("returns an empty list for an empty string", () => {
    expect(parseInlineMarkdown("")).toEqual([]);
  });

  it("round-trips the source text minus its markers", () => {
    const source = "A **bold** claim, an *italic* one, `code` and [a link](https://x.dev).";
    expect(plainText(source)).toBe(
      "A bold claim, an italic one, code and a link.",
    );
  });
});
