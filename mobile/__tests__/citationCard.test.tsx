/**
 * Tests for the citation card's GitHub link.
 *
 * The link should point at the snapshot the answer was grounded in, so the
 * ingested commit wins over the branch. The branch is what a repository
 * ingested before the commit watermark was recorded still has, and
 * ``master`` is the last resort for a row that records neither.
 */

import { DEFAULT_SOURCE_BRANCH, resolveGithubHref } from "@/components/CitationCard";
import type { ChatSource } from "@/types/chat";

/**
 * Build a citation source.
 *
 * @param overrides - The fields the test cares about.
 * @returns The citation.
 */
function makeSource(overrides: Partial<ChatSource> = {}): ChatSource {
  return {
    source_type: "symbol",
    chunk_text: "def handler(): ...",
    file_path: "app/routes.py",
    symbol_name: "handler",
    start_line: 10,
    end_line: 12,
    commit_hash: null,
    author_name: null,
    pr_number: null,
    pr_title: null,
    ...overrides,
  };
}

const URL = "https://github.com/example/foo";

describe("resolveGithubHref", () => {
  it("pins a symbol link to the ingested commit", () => {
    expect(
      resolveGithubHref(makeSource(), URL, "main", "a1b2c3d4"),
    ).toBe(`${URL}/blob/a1b2c3d4/app/routes.py#L10-L12`);
  });

  it("prefers the commit over the branch", () => {
    expect(
      resolveGithubHref(makeSource(), URL, "develop", "a1b2c3d4"),
    ).toContain("/blob/a1b2c3d4/");
  });

  it("falls back to the branch when the commit is missing", () => {
    expect(resolveGithubHref(makeSource(), URL, "main", null)).toBe(
      `${URL}/blob/main/app/routes.py#L10-L12`,
    );
  });

  it("falls back to master only when neither ref is recorded", () => {
    expect(resolveGithubHref(makeSource(), URL, null, null)).toBe(
      `${URL}/blob/${DEFAULT_SOURCE_BRANCH}/app/routes.py#L10-L12`,
    );
  });

  it("omits the line anchor when the symbol range is unknown", () => {
    expect(
      resolveGithubHref(
        makeSource({ start_line: null, end_line: null }),
        URL,
        null,
        "a1b2c3d4",
      ),
    ).toBe(`${URL}/blob/a1b2c3d4/app/routes.py`);
  });

  it("links a commit source to the commit page, not a blob", () => {
    expect(
      resolveGithubHref(
        makeSource({ source_type: "commit", commit_hash: "deadbeef" }),
        URL,
        "main",
        "a1b2c3d4",
      ),
    ).toBe(`${URL}/commit/deadbeef`);
  });

  it("returns null for a kind with no link target", () => {
    expect(
      resolveGithubHref(
        makeSource({ source_type: "document" }),
        URL,
        "main",
        "a1b2c3d4",
      ),
    ).toBeNull();
  });
});
