import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import CitationCard from "@/components/ui/CitationCard";
import type ChatMessage from "@/types/chat";

/** The shape `ChatMessage.sources` declares, for the builder below. */
type Source = ChatMessage["sources"][number];

/**
 * Builds a citation as `POST /chat` actually returns one.
 *
 * The server serializes all ten fields of every source and sets the ones that do not
 * apply to that source's type to `null` -- `file_path` on a commit, `commit_hash` on a
 * symbol, and so on. The client's `ChatMessage.sources` type declares all ten as
 * non-nullable, so a faithful fixture cannot satisfy it. The cast lives here, once,
 * rather than at each of the twenty-odd call sites.
 *
 * `CitationCard` already defends against the nulls (`?? ""`, ternaries throughout), which
 * is why the inaccuracy has never surfaced as a runtime bug.
 */
function source(
  fields: { source_type: string; chunk_text: string } & Partial<
    Omit<Source, "source_type" | "chunk_text">
  >,
): Source {
  return {
    file_path: null,
    symbol_name: null,
    start_line: null,
    end_line: null,
    commit_hash: null,
    author_name: null,
    pr_number: null,
    pr_title: null,
    ...fields,
  } as unknown as Source;
}

const URL = "https://github.com/example/cool-project";

const symbol = source({
  source_type: "symbol",
  chunk_text: "def slugify(text): return text.lower()",
  file_path: "src/util.py",
  symbol_name: "slugify",
  start_line: 4,
  end_line: 6,
});

const commit = source({
  source_type: "commit",
  chunk_text: "abc1234 | Ada | feat: add slugify",
  commit_hash: "abc1234def",
  author_name: "Ada Lovelace",
});

const pullRequest = source({
  source_type: "pull_request",
  chunk_text: "PR #42: Add slugify",
  pr_number: 42,
  pr_title: "Add slugify",
});

const file = source({
  source_type: "file",
  chunk_text: "File: src/util.py",
  file_path: "src/deep/util.py",
});

const document = source({
  source_type: "document",
  chunk_text: "README: ## Usage",
  file_path: "docs/README.md",
});

describe("type labels", () => {
  /**
   * `TYPE_CONFIG` carries a `label` for every source type -- "Symbol", "Commit", "Pull
   * Request", "File", "File". The card still distinguishes types visually by icon and
   * colour alone; the label is now exposed as the icon chip's *accessible name* instead
   * of as text. Rendering it as a visible label was the alternative, and is what the
   * `it.fails` below used to ask for.
   */
  it.each([
    ["a symbol", symbol],
    ["a commit", commit],
    ["a pull request", pullRequest],
    ["a file", file],
  ])("renders no visible text label for %s", (_label, src) => {
    render(<CitationCard src={src} url={URL} />);

    expect(screen.queryByText("Symbol")).not.toBeInTheDocument();
    expect(screen.queryByText("Commit")).not.toBeInTheDocument();
    expect(screen.queryByText("Pull Request")).not.toBeInTheDocument();
    expect(screen.queryByText("File")).not.toBeInTheDocument();
  });

  it("exposes the type as an accessible name rather than a visible label", () => {
    // Naming the chip closes the accessibility hole with no layout change, rather than
    // adding a third line to a card that already reads well. A visible label would be the
    // other option -- change this test if the design moves that way.
    render(<CitationCard src={symbol} url={URL} />);

    expect(screen.getByRole("img", { name: "Symbol" })).toBeInTheDocument();
    expect(screen.queryByText("Symbol")).not.toBeInTheDocument();
  });

  it("renders an unknown source type rather than crashing", () => {
    // New source types can be added server-side before the client knows about them. The
    // card must still render rather than throwing on an undefined config lookup.
    render(
      <CitationCard
        src={{ ...file, source_type: "sql_view" as never }}
        url={URL}
      />,
    );

    expect(screen.getByText("util.py")).toBeInTheDocument();
  });

  it("names the source type for assistive technology", () => {
    // The concrete consequence of the old shape: a screen reader announced the symbol name
    // and file path but never what kind of source it was, because the type lived only in
    // the icon's shape and colour.
    render(<CitationCard src={symbol} url={URL} />);

    expect(screen.getByRole("img", { name: "Symbol" })).toBeInTheDocument();
  });
});

describe("primary label", () => {
  it("uses the symbol name", () => {
    render(<CitationCard src={symbol} url={URL} />);

    expect(screen.getByText("slugify")).toBeInTheDocument();
  });

  it("uses the shortened commit hash", () => {
    render(<CitationCard src={commit} url={URL} />);

    expect(screen.getByText("abc1234")).toBeInTheDocument();
  });

  it("uses the PR number", () => {
    render(<CitationCard src={pullRequest} url={URL} />);

    expect(screen.getByText("PR #42")).toBeInTheDocument();
  });

  it("uses the basename for a file", () => {
    // The full path is the sub-label; the headline is the filename alone.
    render(<CitationCard src={file} url={URL} />);

    expect(screen.getByText("util.py")).toBeInTheDocument();
  });

  it("renders no symbol name for an anonymous symbol", () => {
    // Before the parser fix, exported TS interfaces became symbols named `<anonymous>`.
    // The guard keeps that placeholder out of the UI even if it recurs.
    render(
      <CitationCard
        src={{ ...symbol, symbol_name: "<anonymous>" }}
        url={URL}
      />,
    );

    expect(screen.queryByText("<anonymous>")).not.toBeInTheDocument();
  });
});

describe("github links", () => {
  it("links a symbol to its line range", () => {
    render(<CitationCard src={symbol} url={URL} />);

    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      `${URL}/blob/master/src/util.py#L4-L6`,
    );
  });

  it("links a commit to the commit page", () => {
    render(<CitationCard src={commit} url={URL} />);

    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      `${URL}/commit/abc1234def`,
    );
  });

  it("links a pull request to the PR page", () => {
    render(<CitationCard src={pullRequest} url={URL} />);

    expect(screen.getByRole("link")).toHaveAttribute("href", `${URL}/pull/42`);
  });

  it("renders no link for a document", () => {
    render(<CitationCard src={document} url={URL} />);

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("hardcodes the master branch", () => {
    // The card falls back to ``master`` when no ``branch`` prop is supplied, which is
    // what a call site that does not yet know the ingested branch will see.
    render(<CitationCard src={symbol} url={URL} />);

    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      expect.stringContaining("/blob/master/"),
    );
  });

  it("uses the provided branch in place of the master fallback", () => {
    // The repository's ingested branch is forwarded by callers (ChatBubble) so a repo
    // ingested from ``main`` -- GitHub's default -- produces a live link rather than a
    // dead ``master`` one.
    render(<CitationCard src={symbol} url={URL} branch="develop" />);

    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      `${URL}/blob/develop/src/util.py#L4-L6`,
    );
  });

  it("opens links in a new tab without leaking the referrer", () => {
    render(<CitationCard src={symbol} url={URL} />);

    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});

describe("expansion", () => {
  it("hides the chunk text initially", () => {
    render(<CitationCard src={symbol} url={URL} />);

    expect(screen.queryByText(/def slugify/)).not.toBeInTheDocument();
  });

  it("shows the chunk text once expanded", async () => {
    const user = userEvent.setup();
    render(<CitationCard src={symbol} url={URL} />);

    await user.click(screen.getByRole("button"));

    expect(screen.getByText(/def slugify/)).toBeInTheDocument();
  });

  it("collapses again on a second click", async () => {
    const user = userEvent.setup();
    render(<CitationCard src={symbol} url={URL} />);

    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("button"));

    expect(screen.queryByText(/def slugify/)).not.toBeInTheDocument();
  });

  it("renders the chunk text as plain text, not markup", async () => {
    // The chunk is source code, which routinely contains angle brackets. Rendered as
    // markup it would either vanish or inject.
    const user = userEvent.setup();
    render(
      <CitationCard
        src={{ ...symbol, chunk_text: "List<int> items = new List<int>();" }}
        url={URL}
      />,
    );

    await user.click(screen.getByRole("button"));

    expect(screen.getByText(/List<int>/)).toBeInTheDocument();
  });
});

describe("sub-labels", () => {
  it("shows the file path under a symbol", () => {
    render(<CitationCard src={symbol} url={URL} />);

    expect(screen.getByText("src/util.py")).toBeInTheDocument();
  });

  it("attributes a commit to its author", () => {
    render(<CitationCard src={commit} url={URL} />);

    expect(screen.getByText("by Ada Lovelace")).toBeInTheDocument();
  });

  it("shows the PR title", () => {
    render(<CitationCard src={pullRequest} url={URL} />);

    expect(screen.getByText("Add slugify")).toBeInTheDocument();
  });
});
