import { fireEvent, render, screen } from "@testing-library/react-native";

import {
  GraphInspector,
  IMPORTERS_PREVIEW,
  buildGraphSourceUrl,
  splitPath,
} from "@/components/GraphInspector";
import { neighboursOf } from "@/lib/graphSelection";
import { TOUR_STEP_MS, nextTourIndex } from "@/lib/graphTour";

function node(id: string, path = `src/${id}.ts`) {
  return {
    id,
    label: `${id}.ts`,
    path,
    group: "src",
    kind: "file",
    loc: 40,
    criticality: "caution",
    criticality_score: 50,
    language: "TypeScript",
    fan_in: 0,
    fan_out: 0,
  };
}

const nodes = [node("a"), node("b"), node("c"), node("d")];

describe("neighboursOf", () => {
  it("splits links into importers and imports by direction", () => {
    const links = [
      { source: 1, target: 0 },
      { source: 2, target: 0 },
      { source: 0, target: 3 },
    ];
    const { importers, imports } = neighboursOf(nodes, links, 0);
    expect(importers.map((n) => n.id)).toEqual(["b", "c"]);
    expect(imports.map((n) => n.id)).toEqual(["d"]);
    expect(importers[0].text).toBe("b.ts · src/b.ts");
  });

  it("skips duplicates, self links and out-of-range indices", () => {
    const links = [
      { source: 1, target: 0 },
      { source: 1, target: 0 },
      { source: 0, target: 0 },
      { source: 9, target: 0 },
    ];
    expect(neighboursOf(nodes, links, 0).importers).toHaveLength(1);
    expect(neighboursOf(nodes, links, 0).imports).toHaveLength(0);
    expect(neighboursOf(nodes, links, -1)).toEqual({ importers: [], imports: [] });
    expect(neighboursOf(nodes, links, 40)).toEqual({ importers: [], imports: [] });
  });
});

describe("tour stepping", () => {
  it("starts at the first step, advances, and ends with null", () => {
    expect(nextTourIndex(null, 3)).toBe(0);
    expect(nextTourIndex(0, 3)).toBe(1);
    expect(nextTourIndex(2, 3)).toBeNull();
    expect(nextTourIndex(null, 0)).toBeNull();
    expect(TOUR_STEP_MS).toBeGreaterThan(0);
  });
});

describe("path helpers", () => {
  it("splits a path and pins the GitHub link to the commit", () => {
    expect(splitPath("a/b/c.ts")).toEqual({ dir: "a/b/", base: "c.ts" });
    expect(splitPath("c.ts")).toEqual({ dir: "", base: "c.ts" });
    expect(buildGraphSourceUrl("https://github.com/o/r/", "a b/c.ts", "main", "abc123")).toBe(
      "https://github.com/o/r/blob/abc123/a%20b/c.ts",
    );
    expect(buildGraphSourceUrl("https://github.com/o/r", "c.ts", "main")).toContain("/blob/main/");
    expect(buildGraphSourceUrl("https://github.com/o/r", "c.ts", null)).toContain("/blob/master/");
  });
});

describe("GraphInspector", () => {
  const importers = [
    { id: "b", text: "b" },
    { id: "c", text: "c" },
    { id: "d", text: "d" },
  ];

  it("shows counts, folds extra importers and selects a neighbour", async () => {
    const onSelectNode = jest.fn();
    await render(
      <GraphInspector
        node={nodes[0]}
        level="file"
        githubUrl="https://github.com/o/r"
        branch="main"
        importers={importers}
        imports={[{ id: "z", text: "z" }]}
        tourPosition={2}
        onSelectNode={onSelectNode}
        onClose={() => {}}
      />,
    );
    expect(screen.getByTestId("graph-inspector-importers")).toHaveTextContent("3");
    expect(screen.getByTestId("graph-inspector-imports")).toHaveTextContent("1");
    expect(screen.getByText("Read #2")).toBeTruthy();
    expect(screen.queryByTestId("graph-neighbour-d")).toBeNull();
    expect(IMPORTERS_PREVIEW).toBe(2);
    await fireEvent.press(screen.getByTestId("graph-importers-toggle"));
    expect(screen.getByTestId("graph-neighbour-d")).toBeTruthy();
    await fireEvent.press(screen.getByTestId("graph-neighbour-b"));
    expect(onSelectNode).toHaveBeenCalledWith("b");
  });

  it("offers the file actions at file level only", async () => {
    const onAsk = jest.fn();
    const { rerender } = await render(
      <GraphInspector
        node={nodes[0]}
        level="file"
        githubUrl="https://github.com/o/r"
        branch="main"
        onAsk={onAsk}
        onOpenExplorer={() => {}}
        onClose={() => {}}
      />,
    );
    await fireEvent.press(screen.getByTestId("graph-inspector-ask"));
    expect(onAsk).toHaveBeenCalled();
    expect(screen.getByTestId("graph-inspector-explorer")).toBeTruthy();
    await rerender(
      <GraphInspector
        node={nodes[0]}
        level="symbol"
        githubUrl="https://github.com/o/r"
        branch="main"
        onAsk={onAsk}
        onOpenExplorer={() => {}}
        onClose={() => {}}
      />,
    );
    expect(screen.queryByTestId("graph-inspector-ask")).toBeNull();
    expect(screen.queryByTestId("graph-inspector-explorer")).toBeNull();
  });

  it("renders nothing without a node", async () => {
    await render(
      <GraphInspector node={null} level="file" githubUrl="" branch={null} onClose={() => {}} />,
    );
    expect(screen.queryByTestId("graph-inspector")).toBeNull();
  });
});
