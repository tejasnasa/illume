import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import FileDetailCard, {
  type FileOwnership,
} from "@/components/ui/FileDetailCard";
import type { FileDetail, FileNode } from "@/types/explorer";

const GITHUB_URL = "https://github.com/example/cool-project";

const FILE: FileNode = {
  id: "f1",
  label: "util.py",
  path: "src/core/util.py",
  language: "python",
  criticality: "safe",
  loc: 40,
  fan_in: 3,
  fan_out: 1,
  group: "core",
  kind: "file",
};

const OWNERSHIP: FileOwnership = {
  file_id: "f1",
  file_path: "src/core/util.py",
  primary_owner: "Ada Lovelace",
  contributors: [
    {
      name: "Ada Lovelace",
      email: "ada@example.com",
      percentage: 80,
      last_commit: "2026-01-01",
    },
    {
      name: "Grace Hopper",
      email: "grace@example.com",
      percentage: 20,
      last_commit: "2025-12-01",
    },
  ],
  bus_factor: 2,
  is_knowledge_silo: false,
};

/** A neighbour file at `path`. */
function neighbour(path: string, criticality = "safe"): FileNode {
  return { ...FILE, id: path, path, label: path, criticality };
}

/** Renders the card with defaults, overridable per test. */
function renderCard(
  props: Partial<React.ComponentProps<typeof FileDetailCard>> = {},
) {
  return render(
    <FileDetailCard
      file={FILE}
      ownershipData={OWNERSHIP}
      isLoading={false}
      detail={null}
      isLoadingDetail={false}
      githubUrl={GITHUB_URL}
      repoNumber={7}
      annotation={null}
      readingPosition={null}
      importers={[]}
      imports={[]}
      onSelectPath={vi.fn()}
      {...props}
    />,
  );
}

/** The card titled `title`, located by its heading. */
function card(title: RegExp): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("section")!;
}

describe("file metadata", () => {
  it("renders the filename, with its directory above it", () => {
    renderCard();

    expect(screen.getByRole("heading", { name: "util.py" })).toBeInTheDocument();
    expect(screen.getByText("src/core/")).toBeInTheDocument();
  });

  it("renders the language", () => {
    renderCard();

    expect(screen.getByText("python")).toBeInTheDocument();
  });

  it("falls back to Unknown for a falsy language", () => {
    // The graph endpoint coerces a null column to `"unknown"`, so an empty
    // string is the reachable falsy value here.
    renderCard({ file: { ...FILE, language: "" } });

    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });

  it("renders the criticality, defaulting a missing one to safe", () => {
    renderCard({ file: { ...FILE, criticality: "" } });

    expect(screen.getByText("safe")).toBeInTheDocument();
  });

  it("renders size and connection counts", () => {
    renderCard();

    expect(screen.getByText("40 LOC")).toBeInTheDocument();
    expect(screen.getByText("In 3 · Out 1")).toBeInTheDocument();
  });

  it("flags a knowledge silo", () => {
    renderCard({
      ownershipData: { ...OWNERSHIP, is_knowledge_silo: true, bus_factor: 1 },
    });

    expect(screen.getByText("Knowledge silo")).toBeInTheDocument();
  });

  it("does not flag a file that is not a silo", () => {
    renderCard();

    expect(screen.queryByText("Knowledge silo")).not.toBeInTheDocument();
  });
});

describe("actions", () => {
  it("asks the chat about this file", () => {
    renderCard();

    const href = screen
      .getByRole("link", { name: /Ask about this file/ })
      .getAttribute("href")!;
    expect(href.startsWith("/repo/7/chat?q=")).toBe(true);
    expect(decodeURIComponent(href.split("q=")[1])).toContain(
      "src/core/util.py",
    );
  });

  it("links to the graph", () => {
    renderCard();

    expect(screen.getByRole("link", { name: "Graph" })).toHaveAttribute(
      "href",
      "/repo/7/graph",
    );
  });
});

describe("github link", () => {
  const githubLink = () => screen.getByRole("link", { name: /GitHub/ });

  it("links to the file on GitHub", () => {
    renderCard();

    expect(githubLink()).toHaveAttribute(
      "href",
      `${GITHUB_URL}/blob/master/src/core/util.py`,
    );
  });

  it("pins the link to the ingested commit when one is supplied", () => {
    // The commit is the snapshot the file was indexed at, so it wins over the branch.
    renderCard({ commitSha: "a1b2c3d4", branch: "develop" });

    expect(githubLink().getAttribute("href")).toContain("/blob/a1b2c3d4/");
  });

  it("falls back to the ingested branch when the commit is missing", () => {
    renderCard({ branch: "develop" });

    expect(githubLink().getAttribute("href")).toContain("/blob/develop/");
  });

  it("opens in a new tab", () => {
    renderCard();

    expect(githubLink()).toHaveAttribute("target", "_blank");
  });
});

describe("who to ask", () => {
  it("marks the primary owner", () => {
    renderCard();

    const ada = within(card(/Who to ask/)).getByText("Ada Lovelace");
    expect(within(ada).getByText("Owner")).toBeInTheDocument();
  });

  it("formats each contributor's share to one decimal place", () => {
    renderCard({
      ownershipData: {
        ...OWNERSHIP,
        contributors: [
          { name: "Ada", email: null, percentage: 66.66666, last_commit: null },
        ],
      },
    });

    expect(screen.getByText("66.7%")).toBeInTheDocument();
  });

  it("shows a dash for a null share, and a real zero as zero", () => {
    renderCard({
      ownershipData: {
        ...OWNERSHIP,
        contributors: [
          { name: "Ada", email: null, percentage: null, last_commit: null },
          { name: "Grace", email: null, percentage: 0, last_commit: null },
        ],
      },
    });

    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("0.0%")).toBeInTheDocument();
  });

  it("states the bus factor and contributor count", () => {
    renderCard();

    expect(screen.getByText(/Bus factor 2 · 2 contributors/)).toBeInTheDocument();
  });

  it("uses the singular for one contributor", () => {
    renderCard({
      ownershipData: {
        ...OWNERSHIP,
        bus_factor: 1,
        contributors: [OWNERSHIP.contributors[0]],
      },
    });

    expect(screen.getByText(/1 contributor$/)).toBeInTheDocument();
  });
});

describe("loading and empty states", () => {
  it("shows the loading state, and no ownership, while loading", () => {
    renderCard({ isLoading: true });

    expect(screen.getByText("Loading ownership")).toBeInTheDocument();
    expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument();
  });

  it("shows the empty state when there is no ownership data", () => {
    renderCard({ ownershipData: null });

    expect(screen.getByText(/No ownership data/)).toBeInTheDocument();
  });

  it("prefers loading over the empty state", () => {
    renderCard({ ownershipData: null, isLoading: true });

    expect(screen.getByText("Loading ownership")).toBeInTheDocument();
    expect(screen.queryByText(/No ownership data/)).not.toBeInTheDocument();
  });
});

describe("annotation", () => {
  it("renders the note with its reading-order position", () => {
    renderCard({ annotation: "Start here.", readingPosition: 3 });

    expect(screen.getByText(/Start here\./)).toBeInTheDocument();
    expect(screen.getByText(/Read 3/)).toBeInTheDocument();
  });

  it("omits the note when absent", () => {
    renderCard();

    expect(screen.queryByText(/Read \d/)).not.toBeInTheDocument();
  });
});

describe("connections", () => {
  it("counts importers and imports in the card titles", () => {
    renderCard({
      importers: [neighbour("a.py"), neighbour("b.py")],
      imports: [neighbour("c.py")],
    });

    expect(card(/Imported by · 2/)).toBeInTheDocument();
    expect(card(/Imports · 1/)).toBeInTheDocument();
  });

  it("selects a neighbour when its row is clicked", async () => {
    const onSelectPath = vi.fn();
    const user = userEvent.setup();
    renderCard({ importers: [neighbour("src/app.py")], onSelectPath });

    await user.click(screen.getByRole("button", { name: /src\/app\.py/ }));

    expect(onSelectPath).toHaveBeenCalledWith("src/app.py");
  });

  it("shows ten rows and says how many more there are", () => {
    const many = Array.from({ length: 13 }, (_, i) => neighbour(`m${i}.py`));
    renderCard({ importers: many });

    const list = card(/Imported by/);
    expect(within(list).getAllByRole("button")).toHaveLength(10);
    expect(within(list).getByText("and 3 more")).toBeInTheDocument();
  });

  it("says so when nothing is connected", () => {
    renderCard();

    expect(screen.getByText("Nothing imports this file")).toBeInTheDocument();
    expect(screen.getByText("No internal imports")).toBeInTheDocument();
  });
});

const DETAIL: FileDetail = {
  symbols: [
    { kind: "class", name: "Parser", start_line: 5 },
    { kind: "function", name: "tokenize", start_line: 40 },
  ],
  commits: [
    {
      hash: "c".repeat(40),
      title: "fix: tokenize tabs",
      author: "Ada",
      at: new Date().toISOString(),
    },
  ],
};

describe("symbols and recent changes", () => {
  it("links each symbol to its line at the pinned commit", () => {
    renderCard({ detail: DETAIL, commitSha: "abc123" });
    const symbols = card(/^symbols/i);

    const link = within(symbols).getByRole("link", { name: /tokenize/ });
    expect(link).toHaveAttribute(
      "href",
      `${GITHUB_URL}/blob/abc123/src/core/util.py#L40`,
    );
    expect(within(symbols).getByText("L5")).toBeInTheDocument();
  });

  it("links each recent change to its commit, with author", () => {
    renderCard({ detail: DETAIL });
    const changes = card(/recent changes/i);

    const link = within(changes).getByRole("link", { name: /tokenize tabs/ });
    expect(link).toHaveAttribute("href", `${GITHUB_URL}/commit/${"c".repeat(40)}`);
    expect(within(changes).getByText("ccccccc")).toBeInTheDocument();
    expect(within(changes).getByText(/Commit · Ada ·/)).toBeInTheDocument();
  });

  it("says so when there is nothing to list", () => {
    renderCard({ detail: { symbols: [], commits: [] } });

    expect(screen.getByText("No functions or classes")).toBeInTheDocument();
    expect(screen.getByText("No commits in the analysed history")).toBeInTheDocument();
  });

  it("shows a loading line while the detail is on its way", () => {
    renderCard({ isLoadingDetail: true });

    expect(screen.getByText("Loading symbols")).toBeInTheDocument();
    expect(screen.getByText("Loading history")).toBeInTheDocument();
  });
});
