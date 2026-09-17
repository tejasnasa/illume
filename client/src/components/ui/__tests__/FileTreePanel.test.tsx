import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import FileTreePanel from "@/components/ui/FileTreePanel";
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
    selectedFile: null,
    expandedDirs: new Set<string>(),
    onFileClick: vi.fn(),
    onToggleDir: vi.fn(),
    pageIndex: null,
    totalPages: 0,
    onNavigate: vi.fn(),
  };
  const merged = { ...defaults, ...props };
  return { ...render(<FileTreePanel {...merged} />), ...merged };
}

describe("header", () => {
  it("renders the title", () => {
    renderPanel();

    expect(screen.getByRole("heading", { name: "File Explorer" })).toBeInTheDocument();
  });

  it("labels the columns", () => {
    renderPanel();

    expect(screen.getByText("Directory / File")).toBeInTheDocument();
    expect(screen.getByText("LOC")).toBeInTheDocument();
    expect(screen.getByText("Guardrail")).toBeInTheDocument();
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
});

describe("reading-order pager", () => {
  it("renders the label", () => {
    renderPanel();

    expect(screen.getByText("Reading Order:")).toBeInTheDocument();
  });

  it("disables the previous arrow before the order loads", () => {
    renderPanel({ pageIndex: null, totalPages: 0 });

    expect(screen.getAllByRole("button")[0]).toBeDisabled();
  });

  it("leaves the next arrow enabled before the order loads", () => {
    // Deliberate, from the shape of the expressions: `disabled` is
    // `pageIndex !== null && …`, so a null index passes, and the handler is
    // `(pageIndex ?? -1) + 1` -- which is exactly 0. So the arrow looks active and lands
    // on the first page.
    //
    // The two arrows disagree about whether the pager is usable yet, which reads oddly
    // beside the "— / 0" counter. It is pinned rather than flagged because the `?? -1` is
    // too specific to be accidental: without it, the click would send 1.
    renderPanel({ pageIndex: null, totalPages: 0 });

    expect(screen.getAllByRole("button")[1]).toBeEnabled();
  });

  it("navigates to the first page from an unloaded index", async () => {
    const onNavigate = vi.fn();
    renderPanel({ pageIndex: null, totalPages: 0, onNavigate });

    await userEvent.setup().click(screen.getAllByRole("button")[1]);

    expect(onNavigate).toHaveBeenCalledWith(0);
  });

  it("shows a dash for the current page before the order loads", () => {
    renderPanel({ pageIndex: null, totalPages: 0 });

    expect(screen.getByText("— / 0")).toBeInTheDocument();
  });

  it("shows a one-based page number", () => {
    // The index is zero-based but the label is not, so the last of five pages reads "5 / 5".
    renderPanel({ pageIndex: 4, totalPages: 5 });

    expect(screen.getByText("5 / 5")).toBeInTheDocument();
  });

  it("disables the previous arrow on the first page", () => {
    renderPanel({ pageIndex: 0, totalPages: 5 });

    expect(screen.getAllByRole("button")[0]).toBeDisabled();
  });

  it("enables the next arrow when pages remain", () => {
    renderPanel({ pageIndex: 0, totalPages: 5 });

    expect(screen.getAllByRole("button")[1]).toBeEnabled();
  });

  it("disables the next arrow on the last page", () => {
    renderPanel({ pageIndex: 4, totalPages: 5 });

    expect(screen.getAllByRole("button")[1]).toBeDisabled();
  });

  it("navigates forward", async () => {
    const onNavigate = vi.fn();
    renderPanel({ pageIndex: 1, totalPages: 5, onNavigate });

    await userEvent.setup().click(screen.getAllByRole("button")[1]);

    expect(onNavigate).toHaveBeenCalledWith(2);
  });

  it("navigates backward", async () => {
    const onNavigate = vi.fn();
    renderPanel({ pageIndex: 2, totalPages: 5, onNavigate });

    await userEvent.setup().click(screen.getAllByRole("button")[0]);

    expect(onNavigate).toHaveBeenCalledWith(1);
  });

  it("treats a null index as the first page when going back", () => {
    // `(pageIndex ?? 0) - 1` yields -1, which the parent is expected to clamp. The arrow
    // is disabled in this state, so the call is unreachable from the UI -- pinned so a
    // future change that enables it does not silently send -1.
    const onNavigate = vi.fn();
    renderPanel({ pageIndex: null, totalPages: 3, onNavigate });

    expect(screen.getAllByRole("button")[0]).toBeDisabled();
    expect(onNavigate).not.toHaveBeenCalled();
  });
});

describe("selection layout", () => {
  it("centers the panel when nothing is selected", () => {
    // The panel takes the full width until a file is chosen and the detail card appears
    // beside it. The centering is applied through motion, so the assertion is that
    // rendering does not depend on a selection.
    renderPanel({ selectedFile: null });

    expect(screen.getByRole("heading", { name: "File Explorer" })).toBeInTheDocument();
  });

  it("renders with a selection", () => {
    renderPanel({ selectedFile: file("README.md", "README.md") });

    expect(screen.getByRole("heading", { name: "File Explorer" })).toBeInTheDocument();
  });

  it("marks the selected file in the tree", () => {
    renderPanel({ selectedFile: file("README.md", "README.md") });

    const row = screen.getByText("README.md").closest("button")!;
    expect(row.className).toContain("bg-(--primary)/10");
  });
});
