/**
 * A small block-level markdown parser.
 *
 * @module MarkdownBlocks
 *
 * The web client pipes chat answers through ``react-markdown`` with
 * ``remark-gfm``. Both are DOM-only: they build real elements and rely on
 * a document to do it, and React Native has neither. Pulling a markdown
 * library in for one prose field is not worth the bundle, so this module
 * does the same job in a fraction of the size.
 *
 * The subset it understands is the one an answer actually uses:
 *
 * - paragraphs,
 * - headings (``#`` through ``######``),
 * - bullet lists (``-``, ``*``, ``+``),
 * - ordered lists (``1.``, ``1)``),
 * - fenced code blocks (```` ``` ```` with an optional language).
 *
 * Inside a block, the inline constructs come from
 * :func:`parseInlineMarkdown` -- bold, italic, inline code and links -- so
 * the two modules speak one language and a run means the same thing in
 * both.
 *
 * Everything here is a pure function over a string. There is no React and
 * no React Native in this file, which is what lets the parser be unit
 * tested in the node environment.
 */

import { parseInlineMarkdown, type InlineSegment } from "@/lib/markdown";

/**
 * A run of inline markdown inside a block.
 *
 * The very same shape :func:`parseInlineMarkdown` returns, so a caller can
 * hand one to the other without translating.
 */
export type MarkdownRun = InlineSegment[];

/** A run of prose. */
export interface MarkdownParagraph {
  /** The discriminator the renderer switches on. */
  type: "paragraph";
  /** The inline runs of the paragraph. */
  runs: MarkdownRun;
}

/** A section heading. */
export interface MarkdownHeading {
  /** The discriminator the renderer switches on. */
  type: "heading";
  /** The heading level, 1 through 6. */
  level: number;
  /** The inline runs of the heading. */
  runs: MarkdownRun;
}

/** An ordered or unordered list. */
export interface MarkdownList {
  /** The discriminator the renderer switches on. */
  type: "list";
  /** True for an ordered list, false for a bullet list. */
  ordered: boolean;
  /** One entry per item; each item is a list of inline runs. */
  items: MarkdownRun[];
}

/** A fenced code block. */
export interface MarkdownCode {
  /** The discriminator the renderer switches on. */
  type: "code";
  /** The language tag on the fence, when the fence carried one. */
  language: string | null;
  /** The code itself, with the markers removed. */
  code: string;
}

/** Any block the parser produces. */
export type MarkdownBlock =
  | MarkdownParagraph
  | MarkdownHeading
  | MarkdownList
  | MarkdownCode;

/**
 * A heading: up to six hashes, then the text.
 *
 * The space after the hashes is required, so ``#hashtag`` stays prose.
 */
const HEADING_PATTERN = /^(#{1,6})\s+(.*)$/;

/**
 * A bullet item: a dash, an asterisk or a plus, then the text.
 *
 * The space is required, so ``*emphasis*`` is not mistaken for a bullet.
 */
const BULLET_PATTERN = /^[-*+]\s+(.*)$/;

/** An ordered item: a number, a dot or a closing parenthesis, then the text. */
const ORDERED_PATTERN = /^(\d+)[.)]\s+(.*)$/;

/** The opening or closing fence of a code block. */
const FENCE_PATTERN = /^```(.*)$/;

/**
 * Parse a markdown string into its blocks.
 *
 * A soft line break inside a paragraph is joined with a space, which is
 * what the web's ``remark-gfm`` does with it -- the two clients therefore
 * wrap their text at the same places. A blank line ends a paragraph.
 *
 * @param source - The markdown string to parse.
 * @returns The blocks, in the order they appear.
 */
export function parseMarkdownBlocks(source: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  if (!source) return blocks;

  const lines = source.replace(/\r\n/g, "\n").split("\n");
  let index = 0;
  let paragraphLines: string[] = [];

  /**
   * Close the paragraph that is being collected, if there is one.
   */
  const flushParagraph = () => {
    if (paragraphLines.length === 0) return;
    blocks.push({
      type: "paragraph",
      runs: parseInlineMarkdown(paragraphLines.join(" ")),
    });
    paragraphLines = [];
  };

  while (index < lines.length) {
    const line = lines[index];

    const fence = FENCE_PATTERN.exec(line);
    if (fence) {
      flushParagraph();
      const language = fence[1].trim();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !FENCE_PATTERN.test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      // Step over the closing fence when the block was closed; an unclosed
      // fence simply runs to the end of the answer.
      if (index < lines.length) index += 1;
      blocks.push({
        type: "code",
        language: language.length > 0 ? language : null,
        code: codeLines.join("\n"),
      });
      continue;
    }

    const heading = HEADING_PATTERN.exec(line);
    if (heading) {
      flushParagraph();
      blocks.push({
        type: "heading",
        level: heading[1].length,
        runs: parseInlineMarkdown(heading[2].trim()),
      });
      index += 1;
      continue;
    }

    const bullet = BULLET_PATTERN.exec(line);
    const ordered = ORDERED_PATTERN.exec(line);
    if (bullet || ordered) {
      flushParagraph();
      const isOrdered = Boolean(ordered);
      const items: MarkdownRun[] = [];
      while (index < lines.length) {
        const currentBullet = BULLET_PATTERN.exec(lines[index]);
        const currentOrdered = ORDERED_PATTERN.exec(lines[index]);
        if (isOrdered && currentOrdered) {
          items.push(parseInlineMarkdown(currentOrdered[2].trim()));
        } else if (!isOrdered && currentBullet) {
          items.push(parseInlineMarkdown(currentBullet[1].trim()));
        } else {
          break;
        }
        index += 1;
      }
      blocks.push({ type: "list", ordered: isOrdered, items });
      continue;
    }

    if (line.trim().length === 0) {
      flushParagraph();
      index += 1;
      continue;
    }

    paragraphLines.push(line.trim());
    index += 1;
  }

  flushParagraph();

  return blocks;
}
