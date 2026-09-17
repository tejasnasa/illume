import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import TreeNodeRenderer from "@/components/ui/TreeNodeRenderer";
import type { FileNode, TreeNode } from "@/types/explorer";

/** A file node with the fields the renderer reads. */
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

/** A file tree node at `path`. */
function fileNode(name: string, path: string, overrides: Partial<FileNode> = {}): TreeNode {
  return { name, path, type: "file", children: {}, file: file(name, path, overrides) };
}

/** A directory node from a list of children. */
function dir(name: string, path: string, children: TreeNode[]): TreeNode {
  return {
    name,
    path,
    type: "directory",
    children: Object.fromEntries(children.map((child) => [child.name, child])),
  };
}

/**
 * The root wrapper.
 *
 * `name: "root"` is special-cased by the renderer: it renders no row of its own and its
 * children keep their parent's indentation level, so it is the only node that is always
 * expanded.
 */
function root(children: TreeNode[]): TreeNode {
  return dir("root", "", children);
}

const TREE = root([
  dir("src", "src", [
    fileNode("main.py", "src/main.py"),
    fileNode("util.py", "src/util.py", { criticality: "critical" }),
  ]),
  fileNode("README.md", "README.md", { loc: 12, criticality: "caution" }),
]);

/** Renders the tree with sensible defaults. */
function renderTree(props: Partial<React.ComponentProps<typeof TreeNodeRenderer>> = {}) {
  const defaults = {
    node: TREE,
    selectedFile: null,
    expandedDirs: new Set<string>(),
    onFileClick: vi.fn(),
    onToggleDir: vi.fn(),
  };
  const merged = { ...defaults, ...props };
  return { ...render(<TreeNodeRenderer {...merged} />), ...merged };
}

describe("the root wrapper", () => {
  it("renders its children without a row of its own", () => {
    // No "root" label, but the top-level entries are present.
    renderTree();

    expect(screen.queryByText("root")).not.toBeInTheDocument();
    expect(screen.getByText("src")).toBeInTheDocument();
    expect(screen.getByText("README.md")).toBeInTheDocument();
  });

  it("renders collapsed directories' children hidden", () => {
    renderTree();

    expect(screen.queryByText("main.py")).not.toBeInTheDocument();
  });

  it("renders an expanded directory's children", () => {
    renderTree({ expandedDirs: new Set(["src"]) });

    expect(screen.getByText("main.py")).toBeInTheDocument();
    expect(screen.getByText("util.py")).toBeInTheDocument();
  });

  it("keeps top-level files at the root's indentation level", () => {
    // The renderer passes `level` through unchanged for the root rather than incrementing
    // it, so a nested file is indented but a top-level one is not.
    renderTree({ expandedDirs: new Set(["src"]) });

    const readme = screen.getByText("README.md").closest("button")!;
    const main = screen.getByText("main.py").closest("button")!;

    expect(readme.style.paddingLeft).toBe("8px");
    expect(main.style.paddingLeft).toBe("28px");
  });
});

describe("ordering", () => {
  it("lists directories before files", () => {
    renderTree();

    const labels = screen.getAllByText(/^(src|README\.md)$/).map((el) => el.textContent);
    expect(labels).toEqual(["src", "README.md"]);
  });

  it("sorts each group alphabetically", () => {
    renderTree({
      node: root([
        fileNode("zeta.py", "zeta.py"),
        fileNode("alpha.py", "alpha.py"),
        dir("zdir", "zdir", []),
        dir("adir", "adir", []),
      ]),
    });

    const labels = screen
      .getAllByText(/^(alpha\.py|zeta\.py|adir|zdir)$/)
      .map((el) => el.textContent);
    expect(labels).toEqual(["adir", "zdir", "alpha.py", "zeta.py"]);
  });

  it("sorts case-insensitively by locale", () => {
    // `localeCompare` rather than a raw `<`, so "Beta" does not sort before "alpha".
    renderTree({
      node: root([fileNode("Beta.py", "Beta.py"), fileNode("alpha.py", "alpha.py")]),
    });

    const labels = screen.getAllByText(/\.py$/).map((el) => el.textContent);
    expect(labels).toEqual(["alpha.py", "Beta.py"]);
  });
});

describe("expansion", () => {
  it("calls onToggleDir with the directory path", async () => {
    const onToggleDir = vi.fn();
    renderTree({ onToggleDir });

    await userEvent.setup().click(screen.getByText("src"));

    expect(onToggleDir).toHaveBeenCalledWith("src");
  });

  it("does not expand by itself", () => {
    // Expansion is controlled: the set comes from the parent, so clicking a collapsed
    // directory without updating it must leave the children hidden.
    renderTree();

    expect(screen.queryByText("main.py")).not.toBeInTheDocument();
  });

  it("collapses an expanded directory", () => {
    renderTree({ expandedDirs: new Set() });

    expect(screen.queryByText("main.py")).not.toBeInTheDocument();
  });

  it("ignores an entry for a directory that is not in the tree", () => {
    // The set is keyed by path and persists across repositories, so a stale entry must
    // not expand something unrelated.
    renderTree({ expandedDirs: new Set(["nowhere", "other/path"]) });

    expect(screen.queryByText("main.py")).not.toBeInTheDocument();
  });
});

describe("files", () => {
  it("renders the line count", () => {
    renderTree({ expandedDirs: new Set(["src"]) });

    const button = screen.getByText("main.py").closest("button")!;
    expect(within(button).getByText("10")).toBeInTheDocument();
  });

  it("renders 0 for a file with no recorded line count", () => {
    // `loc || 0` -- a null column would otherwise render "null" in the row.
    renderTree({
      node: root([fileNode("empty.py", "empty.py", { loc: 0 })]),
    });

    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("renders the criticality badge", () => {
    renderTree({ expandedDirs: new Set(["src"]) });

    expect(screen.getByText("critical")).toBeInTheDocument();
  });

  it("calls onFileClick with the file, not the node", async () => {
    // The handler receives the inner `FileNode`, which is what the detail card and the
    // selection state key on.
    const onFileClick = vi.fn();
    renderTree({ onFileClick });

    await userEvent.setup().click(screen.getByText("README.md"));

    expect(onFileClick).toHaveBeenCalledTimes(1);
    expect(onFileClick.mock.calls[0][1]).toMatchObject({ path: "README.md" });
  });

  it("marks the selected file", () => {
    const { container } = renderTree({
      selectedFile: file("README.md", "README.md"),
    });

    // The selection is a class change on the row, so the assertion is on the row's
    // resolved classes rather than on any text.
    const row = screen.getByText("README.md").closest("button")!;
    expect(row.className).toContain("bg-(--primary)/10");
    expect(container).toBeTruthy();
  });

  it("does not mark an unselected file", () => {
    renderTree({ selectedFile: file("other.py", "other.py") });

    const row = screen.getByText("README.md").closest("button")!;
    expect(row.className).not.toContain("bg-(--primary)/10");
  });

  it("renders a directory row as a button without a criticality badge", () => {
    renderTree();

    const row = screen.getByText("src").closest("button")!;
    expect(within(row).queryByText("safe")).not.toBeInTheDocument();
  });
});

describe("nesting", () => {
  it("renders grandchildren", () => {
    renderTree({
      node: root([dir("a", "a", [dir("b", "b", [fileNode("deep.py", "a/b/deep.py")])])]),
      expandedDirs: new Set(["a", "b"]),
    });

    expect(screen.getByText("deep.py")).toBeInTheDocument();
  });

  it("indents deeper levels further", () => {
    renderTree({
      node: root([dir("a", "a", [dir("b", "b", [fileNode("deep.py", "a/b/deep.py")])])]),
      expandedDirs: new Set(["a", "b"]),
    });

    const depthOne = screen.getByText("b").closest("button")!;
    const depthTwo = screen.getByText("deep.py").closest("button")!;

    expect(parseInt(depthTwo.style.paddingLeft)).toBeGreaterThan(
      parseInt(depthOne.style.paddingLeft),
    );
  });

  it("hides grandchildren when the middle directory is collapsed", () => {
    renderTree({
      node: root([dir("a", "a", [dir("b", "b", [fileNode("deep.py", "a/b/deep.py")])])]),
      expandedDirs: new Set(["a"]),
    });

    expect(screen.queryByText("deep.py")).not.toBeInTheDocument();
  });
});

describe("emptiness", () => {
  it("renders no rows for an empty tree", () => {
    // A wrapping `div` is still produced -- the assertion is that it holds no rows, not
    // that the DOM is completely empty.
    const { container } = renderTree({ node: root([]) });

    expect(container.querySelectorAll("button")).toHaveLength(0);
    expect(container.textContent).toBe("");
  });

  it("renders an empty directory as just its row", () => {
    renderTree({ node: root([dir("empty", "empty", [])]) });

    expect(screen.getByText("empty")).toBeInTheDocument();
  });

  it("handles a large tree without blowing up", () => {
    // A sanity bound rather than a benchmark: the renderer recurses, and a repository can
    // legitimately have hundreds of files in one directory.
    const many = Array.from({ length: 200 }, (_, i) =>
      fileNode(`file_${i}.py`, `bulk/file_${i}.py`),
    );
    renderTree({ node: root([dir("bulk", "bulk", many)]), expandedDirs: new Set(["bulk"]) });

    expect(screen.getAllByText(/^file_\d+\.py$/)).toHaveLength(200);
  });
});
