/**
 * Tests for picking things out of the dependency graph.
 *
 * The rules here are what a reader relies on: that the search finds a file
 * by either half of its name, that the links of a selected file are the
 * ones that touch it, and that the reading-order tour walks the files the
 * guide names -- and only the ones the graph actually has a node for.
 */

import {
  MAX_SEARCH_MATCHES,
  guideSteps,
  incidentLinkIndices,
  isMatch,
  matchNodes,
  nodeIndexById,
} from "@/lib/graphSelection";
import type { IndexedLink } from "@/lib/graphLayout";
import type { GraphNodeMeta } from "@/lib/graphTypes";

/**
 * Build a node with sensible defaults.
 *
 * @param overrides - The fields the test cares about.
 * @returns The node.
 */
function makeNode(overrides: Partial<GraphNodeMeta> = {}): GraphNodeMeta {
  return {
    id: "node-1",
    label: "index.ts",
    path: "src/index.ts",
    group: "src",
    kind: "file",
    loc: 100,
    criticality: "safe",
    criticality_score: 25,
    language: "TypeScript",
    fan_in: 1,
    fan_out: 2,
    ...overrides,
  };
}

describe("searching the graph", () => {
  it("matches on the label", () => {
    expect(isMatch(makeNode({ label: "server.ts" }), "server")).toBe(true);
  });

  it("matches on the path", () => {
    expect(
      isMatch(makeNode({ label: "a.ts", path: "src/api/routes.ts" }), "api"),
    ).toBe(true);
  });

  it("ignores the case of the query", () => {
    expect(isMatch(makeNode({ label: "Server.ts" }), "server")).toBe(true);
  });

  it("matches nothing for an empty query", () => {
    expect(isMatch(makeNode(), "")).toBe(false);
    expect(isMatch(makeNode(), "   ")).toBe(false);
  });

  it("returns the matching nodes", () => {
    const nodes = [
      makeNode({ id: "a", label: "server.ts", path: "src/server.ts" }),
      makeNode({ id: "b", label: "client.ts", path: "src/client.ts" }),
      makeNode({ id: "c", label: "api.ts", path: "src/api.ts" }),
    ];

    const matches = matchNodes(nodes, "api");
    expect(matches.map((node) => node.id)).toEqual(["c"]);
  });

  it("caps the number of matches it returns", () => {
    const nodes = Array.from({ length: 50 }, (_, index) =>
      makeNode({ id: `n-${index}`, label: `match-${index}.ts` }),
    );

    const matches = matchNodes(nodes, "match");
    expect(matches).toHaveLength(MAX_SEARCH_MATCHES);
  });
});

describe("the links of a selected node", () => {
  it("finds the links that touch it", () => {
    const links: IndexedLink[] = [
      { source: 0, target: 1 },
      { source: 1, target: 2 },
      { source: 2, target: 3 },
    ];

    expect(incidentLinkIndices(links, 1)).toEqual([0, 1]);
    expect(incidentLinkIndices(links, 3)).toEqual([2]);
  });

  it("finds nothing for a node with no links", () => {
    expect(incidentLinkIndices([{ source: 0, target: 1 }], 9)).toEqual([]);
  });
});

describe("the reading-order tour", () => {
  const nodes = [
    makeNode({ id: "a", path: "src/first.ts" }),
    makeNode({ id: "b", path: "src/second.ts" }),
  ];

  it("joins the guide to the graph by path", () => {
    const steps = guideSteps(
      [
        { position: 2, file_path: "src/second.ts", annotation: "then this" },
        { position: 1, file_path: "src/first.ts", annotation: "start here" },
      ],
      nodes,
    );

    expect(steps.map((step) => step.node.id)).toEqual(["a", "b"]);
    expect(steps[0].annotation).toBe("start here");
  });

  it("skips a path the graph has no node for", () => {
    // A barrel file holds only re-exports, so the graph lifts its edges
    // onto the files it re-exports and leaves it with no node of its own.
    const steps = guideSteps(
      [
        { position: 1, file_path: "src/index.ts", annotation: "the barrel" },
        { position: 2, file_path: "src/second.ts", annotation: "then this" },
      ],
      nodes,
    );

    expect(steps.map((step) => step.node.id)).toEqual(["b"]);
  });

  it("is empty when the guide names nothing the graph has", () => {
    const steps = guideSteps(
      [{ position: 1, file_path: "src/nowhere.ts", annotation: "" }],
      nodes,
    );
    expect(steps).toEqual([]);
  });
});

describe("finding a node by its identifier", () => {
  it("returns the index of the node", () => {
    const nodes = [makeNode({ id: "a" }), makeNode({ id: "b" })];
    expect(nodeIndexById(nodes, "b")).toBe(1);
  });

  it("returns -1 for a node the graph does not have", () => {
    const nodes = [makeNode({ id: "a" })];
    expect(nodeIndexById(nodes, "zzz")).toBe(-1);
    expect(nodeIndexById(nodes, null)).toBe(-1);
  });
});
