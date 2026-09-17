import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import FileDetailCard from "@/components/ui/FileDetailCard";

const GITHUB_URL = "https://github.com/example/cool-project";

const FILE = {
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

const OWNERSHIP = {
  file_id: "f1",
  file_path: "src/core/util.py",
  primary_owner: "Ada Lovelace",
  contributors: [
    { name: "Ada Lovelace", email: "ada@example.com", percentage: 80, last_commit: "2026-01-01" },
    { name: "Grace Hopper", email: "grace@example.com", percentage: 20, last_commit: "2025-12-01" },
  ],
  bus_factor: 2,
  is_knowledge_silo: false,
};

/** Renders the card with defaults, overridable per test. */
function renderCard(props: Partial<React.ComponentProps<typeof FileDetailCard>> = {}) {
  return render(
    <FileDetailCard
      file={FILE}
      ownershipData={OWNERSHIP}
      isLoading={false}
      githubUrl={GITHUB_URL}
      annotation={null}
      onClose={vi.fn()}
      {...props}
    />,
  );
}

describe("file metadata", () => {
  it("renders the filename and full path", () => {
    renderCard();

    expect(screen.getByRole("heading", { name: "util.py" })).toBeInTheDocument();
    expect(screen.getByText("src/core/util.py")).toBeInTheDocument();
  });

  it("renders the language", () => {
    renderCard();

    expect(screen.getByText("python")).toBeInTheDocument();
  });

  it("falls back to Unknown for a falsy language", () => {
    // The fallback is `file.language || "Unknown"`, so it is the falsy case rather than
    // the null one. The graph endpoint coerces a null column to `"unknown"`
    // (`graph_builder.py`), so an empty string is the reachable falsy value here.
    renderCard({ file: { ...FILE, language: "" } });

    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });

  it("renders the criticality badge", () => {
    renderCard();

    expect(screen.getByText("safe")).toBeInTheDocument();
  });

  it("flags a knowledge silo", () => {
    renderCard({ ownershipData: { ...OWNERSHIP, is_knowledge_silo: true, bus_factor: 1 } });

    expect(screen.getByText("Knowledge Silo")).toBeInTheDocument();
  });

  it("does not flag a file that is not a silo", () => {
    renderCard();

    expect(screen.queryByText("Knowledge Silo")).not.toBeInTheDocument();
  });
});

describe("github link", () => {
  it("links to the file on GitHub", () => {
    const { container } = renderCard();

    const link = container.querySelector("a");
    expect(link).toHaveAttribute("href", `${GITHUB_URL}/blob/master/src/core/util.py`);
  });

  it("hardcodes the master branch", () => {
    // The repository's ingested branch is available to the client but unused, so a repo
    // ingested from `main` -- GitHub's default now -- produces a dead link. Four other
    // components share this; see CLAUDE.md's note on the five deep links.
    const { container } = renderCard();

    expect(container.querySelector("a")?.getAttribute("href")).toContain("/blob/master/");
  });

  it("opens in a new tab", () => {
    const { container } = renderCard();

    expect(container.querySelector("a")).toHaveAttribute("target", "_blank");
  });
});

describe("ownership", () => {
  it("renders the primary owner", () => {
    // Scoped rather than queried globally: the same name also appears in the contributor
    // list below, so an unscoped lookup matches twice and proves nothing about the owner
    // card specifically.
    renderCard();

    const ownerCard = screen.getByText("Highest contribution share").parentElement!;
    expect(within(ownerCard).getByText("Ada Lovelace")).toBeInTheDocument();
  });

  it("falls back to Unknown for a missing owner", () => {
    renderCard({ ownershipData: { ...OWNERSHIP, primary_owner: null } });

    const ownerCard = screen.getByText("Highest contribution share").parentElement!;
    expect(within(ownerCard).getByText("Unknown")).toBeInTheDocument();
  });

  it("renders the bus factor", () => {
    // Scoped for the same reason: "2" is also the contributor count, and both are in the
    // card at once.
    renderCard();

    const busFactorCard = screen.getByText("Bus Factor").parentElement!;
    expect(within(busFactorCard).getByText("2")).toBeInTheDocument();
  });

  it("renders the contributor count as its own figure", () => {
    renderCard();

    const contributorCard = screen.getByText("Contributors").parentElement!;
    expect(within(contributorCard).getByText("2")).toBeInTheDocument();
  });

  it("uses the singular unit for a bus factor of one", () => {
    // The unit is derived from the number, so it reads "1 engineer" rather than the
    // "1 engineers" a naive interpolation would produce.
    renderCard({ ownershipData: { ...OWNERSHIP, bus_factor: 1 } });

    expect(screen.getByText("engineer")).toBeInTheDocument();
  });

  it("uses the plural unit above one", () => {
    renderCard();

    expect(screen.getByText("engineers")).toBeInTheDocument();
  });

  it("counts the contributors", () => {
    renderCard();

    expect(screen.getByText("Contributors")).toBeInTheDocument();
    expect(screen.getByText(/2 authors/)).toBeInTheDocument();
  });

  it("formats each contributor's share to one decimal place", () => {
    renderCard({
      ownershipData: {
        ...OWNERSHIP,
        contributors: [{ name: "Ada", email: null, percentage: 66.66666, last_commit: null }],
      },
    });

    expect(screen.getByText("66.7%")).toBeInTheDocument();
  });

  it("renders N/A for a null percentage", () => {
    // `percentage` is nullable on the JSONB payload; `null.toFixed` would throw.
    renderCard({
      ownershipData: {
        ...OWNERSHIP,
        contributors: [{ name: "Ada", email: null, percentage: null, last_commit: null }],
      },
    });

    expect(screen.getByText("N/A")).toBeInTheDocument();
  });

  it("omits the distribution section when there are no contributors", () => {
    renderCard({ ownershipData: { ...OWNERSHIP, contributors: [] } });

    expect(screen.queryByText(/authors/)).not.toBeInTheDocument();
  });
});

describe("loading and empty states", () => {
  it("shows the loading state", () => {
    renderCard({ isLoading: true });

    expect(screen.getByText("Loading ownership data...")).toBeInTheDocument();
  });

  it("does not show ownership while loading", () => {
    renderCard({ isLoading: true });

    expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument();
  });

  it("shows the empty state when there is no ownership data", () => {
    renderCard({ ownershipData: null });

    expect(screen.getByText("No ownership data")).toBeInTheDocument();
  });

  it("prefers loading over the empty state", () => {
    // Both are falsy-ish at once on first open: the request is in flight and the payload
    // is still null. Loading is the honest thing to show.
    renderCard({ isLoading: true, ownershipData: null });

    expect(screen.getByText("Loading ownership data...")).toBeInTheDocument();
    expect(screen.queryByText("No ownership data")).not.toBeInTheDocument();
  });
});

describe("annotation", () => {
  it("renders the note when present", () => {
    renderCard({ annotation: "Read this first." });

    expect(screen.getByText(/Read this first\./)).toBeInTheDocument();
  });

  it("omits the note when absent", () => {
    renderCard({ annotation: null });

    expect(screen.queryByText(/^Note:/)).not.toBeInTheDocument();
  });
});

describe("closing", () => {
  it("calls onClose when the close button is clicked", async () => {
    const onClose = vi.fn();
    renderCard({ onClose });

    // The close button is the only button without a title, and it is the first one.
    await userEvent.setup().click(screen.getAllByRole("button")[0]);

    expect(onClose).toHaveBeenCalled();
  });

  it("does not call onClose on render", () => {
    const onClose = vi.fn();
    renderCard({ onClose });

    expect(onClose).not.toHaveBeenCalled();
  });
});
