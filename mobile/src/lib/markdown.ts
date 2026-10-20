/**
 * A very small inline-markdown splitter.
 *
 * @module Markdown
 *
 * The web client renders the architecture summary through ``ReactMarkdown``.
 * React Native has no DOM and no markdown renderer, and pulling a full
 * markdown library in for one prose field is not worth the bundle. What the
 * summary actually contains is inline emphasis -- a stray ``**bold**``, a
 * backticked identifier, the occasional link -- so this module splits a
 * string into styled runs and leaves the rest as plain text.
 *
 * Everything is a pure function over a string, so the parser is unit
 * tested without a renderer.
 */

/** One styled run of text inside a markdown string. */
export interface InlineSegment {
  /** The text to render, with the markdown markers removed. */
  text: string;
  /** Rendered in a heavier weight. */
  bold?: boolean;
  /** Rendered in an italic face. */
  italic?: boolean;
  /** Rendered in the monospace face. */
  code?: boolean;
  /** Set when the segment was a markdown link. */
  href?: string;
}

/**
 * The inline constructs the parser understands, in priority order.
 *
 * ``**bold**`` has to come before ``*italic*`` or the first two asterisks of
 * a bold run would be read as an empty italic span. The link alternative is
 * last because it is the only one that can contain the others.
 */
const INLINE_PATTERN =
  /(?<code>`[^`]+`)|(?<bold>\*\*[^*]+\*\*)|(?<italic>\*[^*\n]+\*)|(?<underscore>_[^_\n]+_)|\[(?<linkText>[^\]]+)\]\((?<linkHref>[^)\s]+)\)/g;

/**
 * Whether an underscore-delimited span is really emphasis.
 *
 * ``snake_case_names`` is not italics, and the regex cannot tell the
 * difference on its own -- so the characters around the span are checked
 * instead. A span only counts when it is not glued to a word character on
 * either side.
 */
function isUnderscoreEmphasis(
  source: string,
  matchIndex: number,
  matchLength: number,
): boolean {
  const before = source.charAt(matchIndex - 1);
  const after = source.charAt(matchIndex + matchLength);
  const isWordChar = (char: string) => /[A-Za-z0-9]/.test(char);
  return !isWordChar(before) && !isWordChar(after);
}

/**
 * Split a markdown string into styled runs.
 *
 * Text that matches no construct is returned verbatim in a plain segment, so
 * joining the segments' ``text`` reproduces the source minus its markers.
 *
 * @param source - The markdown string to split.
 * @returns The styled runs, in order.
 */
export function parseInlineMarkdown(source: string): InlineSegment[] {
  const segments: InlineSegment[] = [];
  if (!source) return segments;

  // Plain text is accumulated in a buffer and only flushed when a styled
  // run is emitted, so text that merely *contains* a marker -- a
  // ``snake_case_name`` -- stays in one piece with its neighbours.
  let buffer = "";
  const flush = () => {
    if (buffer) {
      segments.push({ text: buffer });
      buffer = "";
    }
  };

  let lastIndex = 0;
  INLINE_PATTERN.lastIndex = 0;

  let match = INLINE_PATTERN.exec(source);
  while (match !== null) {
    const groups = match.groups ?? {};

    buffer += source.slice(lastIndex, match.index);

    if (groups.code !== undefined) {
      flush();
      segments.push({ text: groups.code.slice(1, -1), code: true });
    } else if (groups.bold !== undefined) {
      flush();
      segments.push({ text: groups.bold.slice(2, -2), bold: true });
    } else if (groups.italic !== undefined) {
      flush();
      segments.push({ text: groups.italic.slice(1, -1), italic: true });
    } else if (groups.underscore !== undefined) {
      const emphasis = isUnderscoreEmphasis(
        source,
        match.index,
        match[0].length,
      );
      if (emphasis) {
        flush();
        segments.push({
          text: groups.underscore.slice(1, -1),
          italic: true,
        });
      } else {
        // Not emphasis after all -- keep the markers as they are.
        buffer += match[0];
      }
    } else if (groups.linkText !== undefined && groups.linkHref !== undefined) {
      flush();
      segments.push({
        text: groups.linkText,
        href: groups.linkHref,
      });
    }

    lastIndex = match.index + match[0].length;
    match = INLINE_PATTERN.exec(source);
  }

  buffer += source.slice(lastIndex);
  flush();

  return segments;
}
