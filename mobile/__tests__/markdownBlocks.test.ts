/**
 * Tests for the block-level markdown parser.
 *
 * The parser is the whole of the mobile answer renderer, so the cases
 * below pin the subset it supports: the block kinds, the boundaries
 * between them, and the inline runs inside them.
 */

import { parseMarkdownBlocks } from "@/lib/markdownBlocks";

describe("parseMarkdownBlocks", () => {
  it("returns nothing for an empty answer", () => {
    expect(parseMarkdownBlocks("")).toEqual([]);
  });

  it("parses a paragraph", () => {
    const [block] = parseMarkdownBlocks("The ingest pipeline is one task.");

    expect(block.type).toBe("paragraph");
    if (block.type !== "paragraph") throw new Error("expected a paragraph");
    expect(block.runs).toEqual([{ text: "The ingest pipeline is one task." }]);
  });

  it("joins the lines of a paragraph with a space", () => {
    const [block] = parseMarkdownBlocks("The ingest pipeline\nis one task.");

    expect(block.type).toBe("paragraph");
    if (block.type !== "paragraph") throw new Error("expected a paragraph");
    expect(block.runs).toEqual([{ text: "The ingest pipeline is one task." }]);
  });

  it("parses a heading and keeps its level", () => {
    const [block] = parseMarkdownBlocks("## The pipeline");

    expect(block.type).toBe("heading");
    if (block.type !== "heading") throw new Error("expected a heading");
    expect(block.level).toBe(2);
    expect(block.runs).toEqual([{ text: "The pipeline" }]);
  });

  it("parses a bullet list", () => {
    const [block] = parseMarkdownBlocks("- clone\n- parse\n- score");

    expect(block.type).toBe("list");
    if (block.type !== "list") throw new Error("expected a list");
    expect(block.ordered).toBe(false);
    expect(block.items).toEqual([
      [{ text: "clone" }],
      [{ text: "parse" }],
      [{ text: "score" }],
    ]);
  });

  it("parses an ordered list", () => {
    const [block] = parseMarkdownBlocks("1. clone\n2. parse");

    expect(block.type).toBe("list");
    if (block.type !== "list") throw new Error("expected a list");
    expect(block.ordered).toBe(true);
    expect(block.items).toEqual([[{ text: "clone" }], [{ text: "parse" }]]);
  });

  it("keeps a bullet list and an ordered list apart", () => {
    const blocks = parseMarkdownBlocks("- clone\n\n1. parse");

    expect(blocks).toHaveLength(2);
    expect(blocks[0].type).toBe("list");
    expect(blocks[1].type).toBe("list");
    if (blocks[0].type !== "list" || blocks[1].type !== "list") {
      throw new Error("expected two lists");
    }
    expect(blocks[0].ordered).toBe(false);
    expect(blocks[1].ordered).toBe(true);
  });

  it("parses a fenced code block with its language", () => {
    const [block] = parseMarkdownBlocks(
      "```python\nprint('hello')\n```",
    );

    expect(block.type).toBe("code");
    if (block.type !== "code") throw new Error("expected a code block");
    expect(block.language).toBe("python");
    expect(block.code).toBe("print('hello')");
  });

  it("parses a fenced code block without a language", () => {
    const [block] = parseMarkdownBlocks("```\nplain\n```");

    expect(block.type).toBe("code");
    if (block.type !== "code") throw new Error("expected a code block");
    expect(block.language).toBeNull();
    expect(block.code).toBe("plain");
  });

  it("keeps the markdown inside a code block verbatim", () => {
    const [block] = parseMarkdownBlocks("```\n**not bold**\n```");

    expect(block.type).toBe("code");
    if (block.type !== "code") throw new Error("expected a code block");
    expect(block.code).toBe("**not bold**");
  });

  it("parses the inline runs of a paragraph", () => {
    const [block] = parseMarkdownBlocks("A **bold** word and `code`.");

    expect(block.type).toBe("paragraph");
    if (block.type !== "paragraph") throw new Error("expected a paragraph");
    expect(block.runs).toEqual([
      { text: "A " },
      { text: "bold", bold: true },
      { text: " word and " },
      { text: "code", code: true },
      { text: "." },
    ]);
  });

  it("parses a link inside a paragraph", () => {
    const [block] = parseMarkdownBlocks("See [the docs](https://example.com).");

    expect(block.type).toBe("paragraph");
    if (block.type !== "paragraph") throw new Error("expected a paragraph");
    expect(block.runs).toEqual([
      { text: "See " },
      { text: "the docs", href: "https://example.com" },
      { text: "." },
    ]);
  });

  it("parses the inline runs of a heading", () => {
    const [block] = parseMarkdownBlocks("## The `ingest` task");

    expect(block.type).toBe("heading");
    if (block.type !== "heading") throw new Error("expected a heading");
    expect(block.runs).toEqual([
      { text: "The " },
      { text: "ingest", code: true },
      { text: " task" },
    ]);
  });

  it("parses the inline runs of a list item", () => {
    const [block] = parseMarkdownBlocks("- **clone** the repo");

    expect(block.type).toBe("list");
    if (block.type !== "list") throw new Error("expected a list");
    expect(block.items).toEqual([
      [{ text: "clone", bold: true }, { text: " the repo" }],
    ]);
  });

  it("separates the blocks of a mixed answer", () => {
    const blocks = parseMarkdownBlocks(
      "## Overview\n\nThe pipeline runs.\n\n- clone\n- parse\n\n```sh\nls\n```",
    );

    expect(blocks.map((block) => block.type)).toEqual([
      "heading",
      "paragraph",
      "list",
      "code",
    ]);
  });

  it("does not read a hashtag as a heading", () => {
    const [block] = parseMarkdownBlocks("#hashtag is not a heading");

    expect(block.type).toBe("paragraph");
    if (block.type !== "paragraph") throw new Error("expected a paragraph");
    expect(block.runs).toEqual([{ text: "#hashtag is not a heading" }]);
  });

  it("does not read an emphasised word as a bullet", () => {
    const [block] = parseMarkdownBlocks("*emphasis* is prose");

    expect(block.type).toBe("paragraph");
    if (block.type !== "paragraph") throw new Error("expected a paragraph");
    expect(block.runs).toEqual([
      { text: "emphasis", italic: true },
      { text: " is prose" },
    ]);
  });
});
