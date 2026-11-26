import { describe, expect, it } from "vitest";

import { heroScene, sampleScene, sceneFromGraph, yawToward } from "@/lib/pixelGraph";
import type Graph from "@/types/graph";

/** A file node at `path`, with the fields the builder reads. */
function file(id: string, path: string, extra: Partial<Graph["nodes"][number]> = {}) {
  return {
    id,
    path,
    label: path.split("/").pop()!,
    group: "",
    kind: "file",
    loc: 100,
    criticality: "safe",
    criticality_score: 25,
    language: "python",
    fan_in: 0,
    fan_out: 0,
    ...extra,
  };
}

/** A graph of `nodes`, linked by `[sourceId, targetId]` pairs. */
function graphOf(nodes: Graph["nodes"], links: [string, string][] = []): Graph {
  return {
    nodes,
    links: links.map(([source, target]) => ({ source, target, type: "imports", weight: 1 })),
    metadata: { total_nodes: nodes.length, total_edges: links.length, clusters: 0 },
  };
}

const hubs = (scene: ReturnType<typeof sceneFromGraph>) =>
  scene.nodes.filter((n) => n.kind === 1).map((n) => n.short);

describe("built-in scenes", () => {
  it("draws the same hero every time", () => {
    const a = heroScene();
    const b = heroScene();
    expect(a.nodes.map((n) => [n.x, n.y, n.z])).toEqual(b.nodes.map((n) => [n.x, n.y, n.z]));
  });

  it("letters the hero's directories by their last segment", () => {
    expect(hubs(heroScene())).toContain("hooks/");
    expect(hubs(heroScene())).toContain("components/");
  });

  it("keeps the sample anonymous: seven directories of seven files", () => {
    const scene = sampleScene();
    expect(scene.nodes.filter((n) => n.kind === 1)).toHaveLength(7);
    expect(scene.byPath.size).toBe(49);
  });
});

describe("scenes from a repository graph", () => {
  it("gives every file a node, reachable by its path", () => {
    const scene = sceneFromGraph(graphOf([file("1", "app/a.py"), file("2", "app/b.py")]));
    expect(scene.byPath.get("app/a.py")?.kind).toBe(0);
    expect(scene.byPath.get("app/b.py")?.kind).toBe(0);
  });

  it("splits a single top-level folder one level deeper", () => {
    const scene = sceneFromGraph(
      graphOf([
        file("1", "src/api/a.ts"),
        file("2", "src/hooks/b.ts"),
        file("3", "src/components/c.tsx"),
      ]),
    );
    expect(hubs(scene).sort()).toEqual(["api/", "components/", "hooks/"]);
  });

  it("files root-level files under a hub of their own", () => {
    const scene = sceneFromGraph(graphOf([file("1", "README.md"), file("2", "app/a.py")]));
    expect(hubs(scene)).toContain("./");
  });

  it("folds the smallest directories together past nine", () => {
    const nodes = Array.from({ length: 12 }, (_, i) =>
      file(String(i), `d${i}/f.py`),
    );
    const scene = sceneFromGraph(graphOf(nodes));
    expect(hubs(scene)).toHaveLength(9);
    expect(hubs(scene)).toContain("other/");
    expect(scene.byPath.size).toBe(12);
  });

  it("draws the real import edges between files", () => {
    const scene = sceneFromGraph(
      graphOf([file("1", "app/a.py"), file("2", "lib/b.py")], [["1", "2"]]),
    );
    const a = scene.byPath.get("app/a.py");
    const b = scene.byPath.get("lib/b.py");
    expect(scene.edges.some(([x, y]) => x === a && y === b)).toBe(true);
  });

  it("reads link ends another renderer already swapped for node objects", () => {
    const graph = graphOf([file("1", "app/a.py"), file("2", "lib/b.py")]);
    graph.links = [
      { source: { id: "1" } as never, target: { id: "2" } as never, type: "imports", weight: 1 },
    ];
    const scene = sceneFromGraph(graph);
    expect(scene.edges.filter(([x, y]) => x.kind === 0 && y.kind === 0)).toHaveLength(1);
  });

  it("drops edges to files it does not know", () => {
    const scene = sceneFromGraph(graphOf([file("1", "app/a.py")], [["1", "missing"]]));
    expect(scene.edges.filter(([x, y]) => x.kind === 0 && y.kind === 0)).toHaveLength(0);
  });
});

describe("yawToward", () => {
  it("turns a node on the far side round to the front", () => {
    const yaw = yawToward({ x: 0, z: -1 });
    // After the turn the node's rotated depth is the largest it can be.
    const depth = 0 * Math.sin(yaw) + -1 * Math.cos(yaw);
    expect(depth).toBeCloseTo(1);
  });
});
