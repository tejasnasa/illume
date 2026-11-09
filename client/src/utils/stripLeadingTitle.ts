/**
 * Removes markdown headings that open a generated summary.
 * @module StripLeadingTitle
 */

const LEADING_HEADINGS = /^(?:[ \t]*(?:#{1,6}[ \t].*|#{1,6})[ \t]*(?:\r?\n|$)|[ \t]*\r?\n)+/;

/**
 * Drops headings (and blank lines) at the very start of the text.
 *
 * Generated summaries often begin with a title such as
 * `# Architecture Summary: Foo`, which only repeats the panel's own heading.
 * Headings later in the text are left alone.
 *
 * @param text - Markdown text.
 * @returns The text without its opening headings.
 */
export function stripLeadingTitle(text: string): string {
  return text.replace(LEADING_HEADINGS, "").trim();
}
