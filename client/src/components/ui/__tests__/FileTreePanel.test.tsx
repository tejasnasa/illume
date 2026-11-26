import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import FileTreePanel, { ReadingOrderBar } from "@/components/ui/FileTreePanel";
import type { FileNode, TreeNode } from "@/types/explorer";

/** A file node with the fields the tree reads. */
function file(name: string, path: string, overrides: Partial<FileNode> = {}): FileNode {
  return {
    id: path,
    label: name,
    path,
    group: path.split("/")[0],
    kind: "file",
    loc: 10,
    criticality: "safe",
    language: "python",
    fan_in: 0,
    fan_out: 0,
    ...overrides,
  };
}

function fileNode(name: string, path: string): TreeNode {
  return { name, path, type: "file", children: {}, file: file(name, path) };
}

function dir(name: string, path: string, children: TreeNode[]): TreeNode {
  return {
    name,
    path,
    type: "directory",
    children: Object.fromEntries(children.map((c) => [c.name, c])),
  };
}

const TREE = dir("root", "", [
  dir("src", "src", [fileNode("main.py", "src/main.py")]),
  fileNode("README.md", "README.md"),
]);

/** Renders the panel with defaults. */
function renderPanel(props: Partial<React.ComponentProps<typeof FileTreePanel>> = {}) {
  const defaults = {
    fileTree: TREE,
    fileCount: 2,
    selectedFile: null,
    expandedDirs: new Set<string>(),
    onFileClick: vi.fn(),
    onToggleDir: vi.fn(),
  };
  const merged = { ...defaults, ...props };
  return { ...render(<FileTreePanel {...merged} />), ...merged };
}

/** Renders the reading-order bar with defaults. */
function renderBar(props: Partial<React.ComponentProps<typeof ReadingOrderBar>> = {}) {
  const merged = { pageIndex: null, totalPages: 5, onNavigate: vi.fn(), ...props };
  return { ...render(<ReadingOrderBar {...merged} />), ...merged };
}

const previous = () => screen.getByRole("button", { name: /Previous file/ });
const next = () => screen.getByRole("button", { name: /Next file/ });

describe("the panel", () => {
  it("is a navigation landmark named for the files", () => {
    renderPanel();

    expect(screen.getByRole("navigation", { name: "Files" })).toBeInTheDocument();
  });

  it("shows how many files there are", () => {
    renderPanel({ fileCount: 1234 });

    expect(screen.getByText("1,234")).toBeInTheDocument();
  });
});

describe("the tree", () => {
  it("renders the top level", () => {
    renderPanel();

    expect(screen.getByText("src")).toBeInTheDocument();
    expect(screen.getByText("README.md")).toBeInTheDocument();
  });

  it("renders expanded directories", () => {
    renderPanel({ expandedDirs: new Set(["src"]) });

    expect(screen.getByText("main.py")).toBeInTheDocument();
  });

  it("passes the click handler through", async () => {
    const onFileClick = vi.fn();
    renderPanel({ onFileClick });

    await userEvent.setup().click(screen.getByText("README.md"));

    expect(onFileClick).toHaveBeenCalled();
  });

  it("passes the toggle handler through", async () => {
    const onToggleDir = vi.fn();
    renderPanel({ onToggleDir });

    await userEvent.setup().click(screen.getByText("src"));

    expect(onToggleDir).toHaveBeenCalledWith("src");
  });

  it("marks the selected file", () => {
    renderPanel({ selectedFile: file("README.md", "README.md") });

    const row = screen.getByText("README.md").closest("button")!;
    expect(row).toHaveAttribute("aria-current", "true");
  });
});

describe("the reading-order bar", () => {
  it("renders nothing when the guide has no order", () => {
    const { container } = renderBar({ totalPages: 0 });

    expect(container).toBeEmptyDOMElement();
  });

  it("renders the label", () => {
    renderBar();

    expect(screen.getByText("Reading order")).toBeInTheDocument();
  });

  it("shows a dash while the selected file is not on the order", () => {
    renderBar({ pageIndex: null });

    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows a one-based position", () => {
    // The index is zero-based but the label is not, so the last of five reads "5".
    renderBar({ pageIndex: 4 });

    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("/ 5")).toBeInTheDocument();
  });

  it("disables previous while off the order", () => {
    renderBar({ pageIndex: null });
    expect(previous()).toBeDisabled();
  });

  it("disables previous on the first file", () => {
    renderBar({ pageIndex: 0 });
    expect(previous()).toBeDisabled();
  });

  it("starts the order from the first file when off it", async () => {
    // `(pageIndex ?? -1) + 1` is exactly 0, so the arrow lands on the first file.
    const onNavigate = vi.fn();
    renderBar({ pageIndex: null, onNavigate });

    await userEvent.setup().click(next());

    expect(onNavigate).toHaveBeenCalledWith(0);
  });

  it("disables next on the last file", () => {
    renderBar({ pageIndex: 4 });
    expect(next()).toBeDisabled();
  });

  it("navigates forward", async () => {
    const onNavigate = vi.fn();
    renderBar({ pageIndex: 1, onNavigate });

    await userEvent.setup().click(next());

    expect(onNavigate).toHaveBeenCalledWith(2);
  });

  it("navigates backward", async () => {
    const onNavigate = vi.fn();
    renderBar({ pageIndex: 2, onNavigate });

    await userEvent.setup().click(previous());

    expect(onNavigate).toHaveBeenCalledWith(1);
  });

  it("caps a long order at forty segments", () => {
    const { container } = renderBar({ totalPages: 120 });

    // The segments are mouse shortcuts, hidden from assistive technology.
    expect(container.querySelectorAll('button[aria-hidden="true"]')).toHaveLength(40);
  });
});
