import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../../tests/msw/handlers";
import { server } from "../../../tests/msw/server";
import GitGraph from "@/components/GitGraph";

/**
 * The branch/commit timeline used to choose what to ingest.
 *
 * Despite the name it is not the dependency graph and not 3D -- it is a 2D SVG list. What
 * is worth pinning is the selection flow, because the chosen branch and SHA are what the
 * ingest request is built from.
 */

const BRANCHES = [
  { name: "main", sha: "a".repeat(40), is_default: true },
  { name: "develop", sha: "b".repeat(40), is_default: false },
];

const COMMITS = [
  {
    sha: "c".repeat(40),
    short_sha: "c".repeat(7),
    message: "feat: a recent thing",
    author_name: "Ada Lovelace",
    author_avatar: null,
    authored_at: "2026-01-02T00:00:00Z",
    parents: [],
    branches: ["main", "develop"],
  },
];

/** Registers both endpoints the component loads from. */
function stub({ commits = COMMITS, commitStatus = 200 } = {}) {
  server.use(
    http.get(`${BACKEND_URL}/api/v1/github/repos/:owner/:repo/branches`, () =>
      HttpResponse.json(BRANCHES),
    ),
    http.get(`${BACKEND_URL}/api/v1/github/repos/:owner/:repo/commits-multibranch`, () =>
      HttpResponse.json(commits, { status: commitStatus }),
    ),
  );
}

/** Renders with defaults. */
function renderGraph(props: Partial<React.ComponentProps<typeof GitGraph>> = {}) {
  const defaults = {
    owner: "example",
    repo: "cool-project",
    onSelect: vi.fn(),
    isSubmitting: false,
  };
  const merged = { ...defaults, ...props };
  return { ...render(<GitGraph {...merged} />), ...merged };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("loading", () => {
  it("renders the commits once loaded", async () => {
    stub();
    renderGraph();

    await waitFor(() => expect(screen.getByText("feat: a recent thing")).toBeInTheDocument());
  });

  it("renders the author", async () => {
    stub();
    renderGraph();

    await waitFor(() => expect(screen.getByText(/Ada Lovelace/)).toBeInTheDocument());
  });

  it("shows a loading state first", () => {
    stub();
    renderGraph();

    // The fetch has not resolved on the first paint.
    expect(screen.queryByText("feat: a recent thing")).not.toBeInTheDocument();
  });

  it("shows an error when the history cannot be loaded", async () => {
    stub({ commitStatus: 502 });
    renderGraph();

    await waitFor(() =>
      expect(screen.getByText(/Failed to fetch multibranch commits/)).toBeInTheDocument(),
    );
  });

  it("renders an empty history without crashing", async () => {
    stub({ commits: [] });
    renderGraph();

    await waitFor(() =>
      expect(screen.queryByText(/Failed to fetch/)).not.toBeInTheDocument(),
    );
  });
});

describe("branch selection", () => {
  it("offers the default branch", async () => {
    stub();
    renderGraph();

    await waitFor(() => expect(screen.getByText("main")).toBeInTheDocument());
  });

  it("badges a commit with every branch it appears on", async () => {
    // Branch names are not listed separately -- there is no branch selector. They appear
    // only as badges on the commits that carry them, which is why the fixture's single
    // commit is on both branches.
    stub();
    renderGraph();

    await waitFor(() => expect(screen.getByText("develop")).toBeInTheDocument());
    expect(screen.getByText("main")).toBeInTheDocument();
  });

  it("does not render the branch list the hook loads", async () => {
    // `useGitGraph` fetches branches (for the default marker) and the component never
    // renders that array -- the timeline is built from commits. Recorded so the unused
    // value is visible.
    stub();
    renderGraph();

    await waitFor(() => expect(screen.getByText("develop")).toBeInTheDocument());
    // The only "develop" is the badge on the commit, not a branch row.
    expect(screen.getAllByText("develop")).toHaveLength(1);
  });

  it("does not commit a selection on render", async () => {
    // `onSelect` drives an ingest request; firing it on mount would start an ingestion
    // the user never asked for.
    const onSelect = vi.fn();
    stub();
    renderGraph({ onSelect });

    await waitFor(() => expect(screen.getByText("main")).toBeInTheDocument());
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe("the ingest action", () => {
  /** The submit button, found by its label rather than by position. */
  function ingestButton(): HTMLElement {
    return screen.getByRole("button", { name: /^Ingest / });
  }

  it("names the default branch as the target", async () => {
    // The label is what tells the user what is about to be ingested; it is built from the
    // selection, so a stale selection would show the wrong branch here too.
    stub();
    renderGraph();

    await waitFor(() => expect(ingestButton()).toHaveTextContent("Ingest branch main"));
  });

  it("reports the default branch and no SHA by default", async () => {
    const onSelect = vi.fn();
    stub();
    renderGraph({ onSelect });
    await waitFor(() => expect(ingestButton()).toBeEnabled());

    await userEvent.setup().click(ingestButton());

    expect(onSelect).toHaveBeenCalledWith("main", null);
  });

  it("is disabled while the parent is submitting", async () => {
    // A second click would queue a duplicate ingestion of the same repository. The label
    // changes to "Ingesting..." while submitting, so the button is found by that name.
    stub();
    renderGraph({ isSubmitting: true });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Ingesting/ })).toBeDisabled(),
    );
  });

  it("shows an ingesting label while submitting", async () => {
    stub();
    renderGraph({ isSubmitting: true });

    await waitFor(() => expect(screen.getByText("Ingesting...")).toBeInTheDocument());
  });

  it("is disabled when there is no history to ingest", async () => {
    // Nothing to select means nothing to ingest; the button reflects that rather than
    // sending a request with an undefined ref.
    stub({ commits: [] });
    renderGraph();

    await waitFor(() => expect(ingestButton()).toBeDisabled());
  });
});

describe("commit selection", () => {
  /** The ingest button, found by its label rather than by position. */
  function ingestButton(): HTMLElement {
    return screen.getByRole("button", { name: /^Ingest / });
  }

  it("reports a chosen commit instead of the branch", async () => {
    const onSelect = vi.fn();
    stub();
    renderGraph({ onSelect });
    await waitFor(() => expect(screen.getByText("feat: a recent thing")).toBeInTheDocument());

    await userEvent.setup().click(screen.getByText("feat: a recent thing"));
    await userEvent.setup().click(ingestButton());

    expect(onSelect).toHaveBeenCalledWith("main", "c".repeat(40));
  });

  it("names the commit as the target", async () => {
    stub();
    renderGraph();
    await waitFor(() => expect(screen.getByText("feat: a recent thing")).toBeInTheDocument());

    await userEvent.setup().click(screen.getByText("feat: a recent thing"));

    expect(ingestButton()).toHaveTextContent(`Ingest commit ${"c".repeat(7)}`);
  });

  it("deselects a commit when it is clicked again", async () => {
    const onSelect = vi.fn();
    stub();
    renderGraph({ onSelect });
    await waitFor(() => expect(screen.getByText("feat: a recent thing")).toBeInTheDocument());
    const user = userEvent.setup();

    await user.click(screen.getByText("feat: a recent thing"));
    await user.click(screen.getByText("feat: a recent thing"));
    await user.click(ingestButton());

    // Back to the default branch, with no SHA.
    expect(onSelect).toHaveBeenCalledWith("main", null);
  });
});
