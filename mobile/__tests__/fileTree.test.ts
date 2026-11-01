/**
 * Tests for the file tree logic.
 *
 * The tree is the part of the explorer that can be wrong without looking
 * wrong: a row that sits at the wrong depth, a collapsed directory that
 * still shows its children, an expansion set that is mutated in place --
 * all of those render perfectly happily and quietly show the wrong thing.
 * So the rules are pinned down here, away from any rendering.
 */

import {
  ancestorPaths,
  buildFileTree,
  defaultExpandedPaths,
  expandAncestors,
  flattenTree,
  toggleExpandedPath,
} from "@/lib/fileTree";
import type { FileNode } from "@/types/explorer";

/**
 * Build a file entry for the tree builder.
 *
 * @param path - The file's repository-relative path.
 * @param overrides - The fields the test cares about.
 * @returns The file entry.
 */
function makeFile(path: string, overrides: Partial<FileNode> = {}): FileNode {
  const parts = path.split("/");
  return {
    id: `id-${path}`,
    label: parts[parts.length - 1],
    path,
    group: parts.slice(0, -1).join("/"),
    kind: "file",
    loc: 10,
    criticality: "safe",
    language: "TypeScript",
    fan_in: 0,
    fan_out: 0,
    ...overrides,
  };
}

/** The files every test builds its tree from. */
const FILES: FileNode[] = [
  makeFile("src/app.ts", { loc: 120, criticality: "critical" }),
  makeFile("src/lib/util.ts"),
  makeFile("README.md"),
];

describe("buildFileTree", () => {
  it("nests the flat list under its directories", () => {
    const tree = buildFileTree(FILES);

    expect(tree.name).toBe("root");
    expect(Object.keys(tree.children).sort()).toEqual(["README.md", "src"]);

    const src = tree.children.src;
    expect(src.type).toBe("directory");
    expect(src.path).toBe("src");
    expect(Object.keys(src.children).sort()).toEqual(["app.ts", "lib"]);

    const lib = src.children.lib;
    expect(lib.type).toBe("directory");
    expect(lib.path).toBe("src/lib");
    expect(lib.children["util.ts"].type).toBe("file");
  });

  it("keeps the file payload on the leaf", () => {
    const tree = buildFileTree(FILES);
    const leaf = tree.children.src.children["app.ts"];

    expect(leaf.file?.path).toBe("src/app.ts");
    expect(leaf.file?.loc).toBe(120);
    expect(leaf.file?.criticality).toBe("critical");
  });

  it("ignores a file with an empty path", () => {
    const tree = buildFileTree([makeFile("")]);

    expect(Object.keys(tree.children)).toEqual([]);
  });

  it("drops the file payload when a path is also a directory prefix", () => {
    // Pathological but not impossible in the graph payload. The subtree
    // wins: the node has to be expandable, so keeping a file record on it
    // would leave a row that can be seen but never selected.
    const tree = buildFileTree([
      makeFile("a/b"),
      makeFile("a/b/c.ts"),
      makeFile("a/d.ts"),
    ]);

    const b = tree.children.a.children.b;
    expect(b.type).toBe("directory");
    expect(b.file).toBeUndefined();
    expect(b.children["c.ts"].type).toBe("file");

    // The same result regardless of which entry the payload lists first.
    const reversed = buildFileTree([
      makeFile("a/b/c.ts"),
      makeFile("a/b"),
    ]);
    expect(reversed.children.a.children.b.file).toBeUndefined();
  });
});

describe("flattenTree", () => {
  it("draws the directories and files of the top level", () => {
    const rows = flattenTree(buildFileTree(FILES), new Set());

    // Directories come before files, so "src" leads.
    expect(rows.map((row) => row.node.path)).toEqual(["src", "README.md"]);
    expect(rows[0].depth).toBe(0);
    expect(rows[0].hasChildren).toBe(true);
    expect(rows[0].expanded).toBe(false);
    expect(rows[1].hasChildren).toBe(false);
  });

  it("hides the children of a collapsed directory", () => {
    const rows = flattenTree(buildFileTree(FILES), new Set());

    expect(
      rows.some((row) => row.node.path === "src/app.ts"),
    ).toBe(false);
  });

  it("draws the children of an expanded directory one level deeper", () => {
    const rows = flattenTree(buildFileTree(FILES), new Set(["src"]));

    expect(rows.map((row) => row.node.path)).toEqual([
      "src",
      "src/lib",
      "src/app.ts",
      "README.md",
    ]);
    expect(rows.map((row) => row.depth)).toEqual([0, 1, 1, 0]);
    expect(rows[0].expanded).toBe(true);
    // "src/lib" is open to the reader only once it is expanded itself.
    expect(rows[1].expanded).toBe(false);
  });

  it("opens a directory that is expanded", () => {
    const rows = flattenTree(buildFileTree(FILES), new Set(["src", "src/lib"]));

    expect(rows.map((row) => row.node.path)).toEqual([
      "src",
      "src/lib",
      "src/lib/util.ts",
      "src/app.ts",
      "README.md",
    ]);
    expect(rows[2].depth).toBe(2);
  });
});

describe("defaultExpandedPaths", () => {
  it("opens the top level and nothing deeper", () => {
    const paths = defaultExpandedPaths(buildFileTree(FILES));

    expect(Array.from(paths)).toEqual(["src"]);
  });
});

describe("toggleExpandedPath", () => {
  it("adds a path that was closed", () => {
    const next = toggleExpandedPath(new Set(), "src");

    expect(next.has("src")).toBe(true);
  });

  it("removes a path that was open", () => {
    const next = toggleExpandedPath(new Set(["src"]), "src");

    expect(next.has("src")).toBe(false);
  });

  it("leaves the set it was given alone", () => {
    const original = new Set(["src"]);

    toggleExpandedPath(original, "src/lib");

    expect(Array.from(original)).toEqual(["src"]);
  });
});

describe("ancestorPaths", () => {
  it("lists the directories that contain a file, outermost first", () => {
    expect(ancestorPaths("src/lib/util.ts")).toEqual(["src", "src/lib"]);
  });

  it("lists nothing for a file at the top level", () => {
    expect(ancestorPaths("README.md")).toEqual([]);
  });
});

describe("expandAncestors", () => {
  it("opens every directory that contains the file", () => {
    const next = expandAncestors(new Set(), "src/lib/util.ts");

    expect(Array.from(next).sort()).toEqual(["src", "src/lib"]);
  });
});
