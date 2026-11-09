/**
 * Turns a model answer into markdown the renderer can decorate.
 *
 * The server writes citation keys in square brackets (`[F:app/main.py:3-9]`,
 * `[C:a1b2c3d4]`, `[PR:142]`, `[D:README#install]`, possibly several in one
 * bracket). They should not reach the reader as raw text, so they are
 * rewritten here into links with a private fragment that the markdown renderer
 * turns into chips, leaving code blocks and the rest of the markdown as they
 * are. Verification marks (`[[verify:<verdict>]]`) that older answers carry
 * are removed.
 * @module AgentAnswer
 */
import type { Citation } from "./types";

export const CITE_PREFIX = "#illume-cite=";
const MARK = /\[\[verify:([a-z_]+)\]\]/g;
const KEY_START = /^(?:PR:|F:|C:|D:)/;
const KEY_SPLIT = /\s*[;,]\s*(?=(?:PR|F|C|D):)/;

/**
 * Finds the `]` closing the bracket opened at `open`.
 *
 * Paths may contain brackets themselves (`app/repo/[id]/page.tsx`), so the
 * scan counts depth instead of stopping at the first `]`.
 */
function closingBracket(text: string, open: number): number {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    const ch = text[i];
    if (ch === "\n") return -1;
    if (ch === "[") depth += 1;
    else if (ch === "]") {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/** Splits text into code (fenced or inline) and prose spans. */
function splitCode(text: string): { code: boolean; text: string }[] {
  const parts: { code: boolean; text: string }[] = [];
  const pattern = /(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > last)
      parts.push({ code: false, text: text.slice(last, index) });
    parts.push({ code: true, text: match[0] });
    last = index + match[0].length;
  }
  if (last < text.length) parts.push({ code: false, text: text.slice(last) });
  return parts;
}

function rewriteProse(text: string): string {
  let out = "";
  let i = 0;
  // Keys already shown in the current paragraph: a source cited again before
  // the paragraph ends adds nothing a reader would click.
  let shown = new Set<string>();
  while (i < text.length) {
    if (text.startsWith("\n\n", i)) shown = new Set();
    if (text[i] === "[") {
      const close = closingBracket(text, i);
      if (close !== -1) {
        const inner = text.slice(i + 1, close);
        const isLink = text[close + 1] === "(";
        if (KEY_START.test(inner) && !isLink) {
          const keys = inner
            .split(KEY_SPLIT)
            .filter(Boolean)
            .filter((key) => !shown.has(key));
          for (const key of keys) shown.add(key);
          if (keys.length > 0) {
            const label = keys.map(shortKeyLabel).join(", ");
            out += `[${escapeLabel(label)}](${CITE_PREFIX}${encodeHref(keys.join("\n"))})`;
          } else {
            // Drop the space left before a citation that was removed.
            out = out.replace(/[ \t]+$/, "");
          }
          i = close + 1;
          continue;
        }
      }
    }
    out += text[i];
    i += 1;
  }
  return out;
}

/** Percent-encodes a value, including the parentheses that would end a link. */
function encodeHref(value: string): string {
  return encodeURIComponent(value).replace(/[()]/g, (c) =>
    c === "(" ? "%28" : "%29",
  );
}

function escapeLabel(label: string): string {
  return label.replace(/[[\]\\]/g, "\\$&");
}

/**
 * The text shown on a chip for a key.
 *
 * @param key - A citation key such as `F:server/app/main.py:3-9`.
 * @returns `main.py:3-9`, `C:a1b2c3d4`, `PR #142` or the document slug.
 */
export function shortKeyLabel(key: string): string {
  if (key.startsWith("F:")) {
    const body = key.slice(2);
    const range = /^(.*?):(\d+(?:-\d+)?)$/.exec(body);
    const path = range ? range[1] : body;
    const name = path.split("/").pop() || path;
    return range ? `${name}:${range[2]}` : name;
  }
  if (key.startsWith("PR:")) return `PR #${key.slice(3)}`;
  if (key.startsWith("C:")) return `commit ${key.slice(2, 9)}`;
  if (key.startsWith("D:")) return key.slice(2).split("#").pop() || key;
  return key;
}

/**
 * Rewrites the citation keys in an answer into chip links.
 *
 * Verification marks, which older stored answers may carry, are removed: the
 * answer is shown as it was written.
 *
 * @param answer - Raw answer text from the model.
 * @returns Markdown with `#illume-cite=` links.
 */
export function decorateAnswer(answer: string): string {
  return splitCode(answer)
    .map((part) =>
      part.code ? part.text : rewriteProse(part.text.replace(MARK, "")),
    )
    .join("");
}

/**
 * Cuts a citation key or verification mark that is still being written.
 *
 * While an answer streams, its last characters can be the start of a key
 * (`[F:app/ma`) or a mark (`[[veri`). Shown as they are, they flash as raw
 * text and then vanish once the bracket closes, so the unfinished tail is held
 * back until it does.
 *
 * @param answer - The text received so far.
 * @returns The text without an unfinished trailing key or mark.
 */
export function trimPartialMarkup(answer: string): string {
  const open = answer.lastIndexOf("[");
  if (open === -1) return answer;
  const tail = answer.slice(open);
  if (tail.includes("]") || tail.includes("\n")) return answer;
  const start = answer[open - 1] === "[" ? open - 1 : open;
  const body = answer.slice(start).replace(/^\[+/, "");
  const partial = /^(?:P(?:R(?::.*)?)?|[FCD](?::.*)?|v(?:e(?:r(?:i(?:f(?:y(?::.*)?)?)?)?)?)?)?$/;
  return partial.test(body) ? answer.slice(0, start) : answer;
}

/** The answer with every verification mark removed, for history sent back. */
export function stripMarks(answer: string): string {
  return answer.replace(MARK, "").replace(/[ \t]+\n/g, "\n");
}

/** Decodes the keys carried by a chip link, or `null` for other links. */
export function keysFromHref(href: string | undefined): string[] | null {
  if (!href || !href.startsWith(CITE_PREFIX)) return null;
  try {
    return decodeURIComponent(href.slice(CITE_PREFIX.length))
      .split("\n")
      .filter(Boolean);
  } catch {
    return null;
  }
}

/** The canonical key a stored source would have been written with. */
export function keyOfCitation(citation: Partial<Citation>): string | null {
  if (citation.key) return citation.key;
  if (citation.source_type === "commit" && citation.commit_hash)
    return `C:${citation.commit_hash.slice(0, 8)}`;
  if (citation.source_type === "pull_request" && citation.pr_number != null)
    return `PR:${citation.pr_number}`;
  if (citation.file_path) {
    return citation.start_line != null && citation.end_line != null
      ? `F:${citation.file_path}:${citation.start_line}-${citation.end_line}`
      : `F:${citation.file_path}`;
  }
  return null;
}

/**
 * Finds the citation a key in the answer refers to.
 *
 * Tries the exact key first, then the same file or the same commit, so a key
 * written with a slightly different line range still resolves.
 *
 * @param key - Key from the answer text.
 * @param citations - Evidence the run returned.
 * @returns The matching citation, if any.
 */
export function findCitation(
  key: string,
  citations: Partial<Citation>[],
): Partial<Citation> | null {
  const exact = citations.find((c) => keyOfCitation(c) === key);
  if (exact) return exact;
  if (key.startsWith("F:")) {
    const path = key.slice(2).replace(/:\d+(?:-\d+)?$/, "");
    return citations.find((c) => c.file_path === path) ?? null;
  }
  if (key.startsWith("C:")) {
    const hash = key.slice(2);
    return (
      citations.find(
        (c) => c.commit_hash && c.commit_hash.startsWith(hash.slice(0, 7)),
      ) ?? null
    );
  }
  return null;
}

/** The file a key points at, for pulsing its node; `null` for non-file keys. */
export function pathOfKey(key: string): string | null {
  if (!key.startsWith("F:")) return null;
  return key.slice(2).replace(/:\d+(?:-\d+)?$/, "");
}

/** Every distinct citation key written in an answer, in order of appearance. */
export function answerKeys(answer: string): string[] {
  const keys = new Set<string>();
  for (const match of decorateAnswer(answer).matchAll(
    /#illume-cite=([^)\s]+)/g,
  )) {
    for (const key of keysFromHref(`${CITE_PREFIX}${match[1]}`) ?? [])
      keys.add(key);
  }
  return [...keys];
}

/** Sources split by whether the answer's own text cites them. */
export interface SourcePartition {
  cited: Partial<Citation>[];
  /** Retrieved evidence the answer does not cite. */
  retrieved: Partial<Citation>[];
  /** Keys the run gathered that no returned source carries. */
  retrievedKeys: string[];
}

/**
 * Separates what an answer cites from what the run merely retrieved.
 *
 * An answer with no keys at all (an older stored turn) treats every source as
 * cited, since there is nothing to tell them apart.
 *
 * @param answer - The answer text.
 * @param citations - Sources returned with the answer.
 * @param evidenceKeys - Every key the run gathered.
 * @returns The partition.
 */
export function partitionSources(
  answer: string,
  citations: Partial<Citation>[],
  evidenceKeys: string[],
): SourcePartition {
  const written = answerKeys(answer);
  if (written.length === 0) {
    return { cited: citations, retrieved: [], retrievedKeys: [] };
  }
  const cited = new Set<Partial<Citation>>();
  for (const key of written) {
    const found = findCitation(key, citations);
    if (found) cited.add(found);
  }
  const retrieved = citations.filter((c) => !cited.has(c));
  const known = new Set(citations.map((c) => keyOfCitation(c)));
  const retrievedKeys = evidenceKeys.filter(
    (key) => !written.includes(key) && !known.has(key),
  );
  return { cited: [...cited], retrieved, retrievedKeys };
}

/** A citation in the non-null shape the citation card takes. */
export function toSource(citation: Partial<Citation>): Citation {
  return {
    key: citation.key ?? null,
    source_type: citation.source_type ?? "document",
    chunk_text: citation.chunk_text ?? "",
    file_path: citation.file_path ?? null,
    symbol_name: citation.symbol_name ?? null,
    start_line: citation.start_line ?? null,
    end_line: citation.end_line ?? null,
    commit_hash: citation.commit_hash ?? null,
    author_name: citation.author_name ?? null,
    pr_number: citation.pr_number ?? null,
    pr_title: citation.pr_title ?? null,
  };
}
