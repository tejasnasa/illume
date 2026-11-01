/**
 * Tests for the graph's layout and camera.
 *
 * The layout is a simulation, so what is worth pinning is that it produces
 * a position for every node, resolves the links to the nodes they join,
 * and frames the result. The camera is arithmetic, so its projection is
 * pinned exactly.
 */

import {
  MAX_PHI,
  MIN_PHI,
  clampPhi,
  orbitAt,
  projectPoint,
} from "@/lib/graphCamera";
import {
  boundingRadius,
  computeLayout,
  defaultTicks,
} from "@/lib/graphLayout";
import type { GraphPayload } from "@/lib/graphTypes";

/**
 * Build a small graph payload.
 *
 * @returns The payload.
 */
function makeGraph(): GraphPayload {
  return {
    nodes: [
      {
        id: "a",
        label: "a.ts",
        path: "src/a.ts",
        group: "src",
        kind: "file",
        loc: 100,
        criticality: "safe",
        criticality_score: 25,
        language: "TypeScript",
        fan_in: 1,
        fan_out: 1,
      },
      {
        id: "b",
        label: "b.ts",
        path: "src/b.ts",
        group: "src",
        kind: "file",
        loc: 200,
        criticality: "critical",
        criticality_score: 100,
        language: "TypeScript",
        fan_in: 1,
        fan_out: 1,
      },
      {
        id: "c",
        label: "c.ts",
        path: "src/c.ts",
        group: "src",
        kind: "file",
        loc: 300,
        criticality: "caution",
        criticality_score: 75,
        language: "TypeScript",
        fan_in: 1,
        fan_out: 1,
      },
    ],
    links: [
      { source: "a", target: "b", type: "imports", weight: 1 },
      { source: "b", target: "c", type: "imports", weight: 1 },
    ],
    metadata: { total_nodes: 3, total_edges: 2, clusters: 1 },
  };
}

describe("the layout", () => {
  it("settles every node somewhere", async () => {
    const result = await computeLayout(makeGraph(), { ticks: 20 });

    expect(result.positions).toHaveLength(9);
    expect(result.ticks).toBe(20);
    expect(result.simulationMs).toBeGreaterThanOrEqual(0);
  });

  it("resolves the links to the nodes they join", async () => {
    const result = await computeLayout(makeGraph(), { ticks: 20 });

    expect(result.links).toEqual([
      { source: 0, target: 1 },
      { source: 1, target: 2 },
    ]);
  });

  it("drops a link that names a node the graph does not have", async () => {
    const graph = makeGraph();
    graph.links.push({
      source: "a",
      target: "missing",
      type: "imports",
      weight: 1,
    });

    const result = await computeLayout(graph, { ticks: 10 });

    expect(result.links).toHaveLength(2);
  });

  it("reports progress as it goes", async () => {
    const seen: number[] = [];
    await computeLayout(makeGraph(), {
      ticks: 20,
      chunkSize: 10,
      onProgress: (done) => seen.push(done),
    });

    expect(seen).toEqual([10, 20]);
  });

  it("spends fewer ticks on a larger graph", () => {
    expect(defaultTicks(500)).toBe(300);
    expect(defaultTicks(5_000)).toBe(200);
    expect(defaultTicks(25_000)).toBe(100);
    expect(defaultTicks(25_000)).toBeLessThan(defaultTicks(500));
  });
});

describe("the bounding radius", () => {
  it("contains every node", () => {
    const positions = new Float32Array([3, 0, 0, 0, 4, 0]);
    expect(boundingRadius(positions)).toBeCloseTo(4);
  });

  it("is never zero", () => {
    expect(boundingRadius(new Float32Array([0, 0, 0]))).toBe(1);
  });
});

describe("the orbit camera", () => {
  it("frames the graph with a margin", () => {
    const camera = orbitAt(0, 100);
    expect(camera.radius).toBeCloseTo(240);
    expect(camera.theta).toBeCloseTo(0);
  });

  it("comes back round", () => {
    const camera = orbitAt(24_000, 100);
    expect(camera.theta).toBeCloseTo(0);
  });

  it("puts the target in the middle of the screen", () => {
    const camera = orbitAt(0, 100);
    const point = projectPoint(0, 0, 0, camera, 400, 800);

    expect(point.x).toBeCloseTo(200);
    expect(point.y).toBeCloseTo(400);
    expect(point.depth).toBeCloseTo(camera.radius);
  });

  it("puts a point to the right of the target to the right of the screen", () => {
    const camera = orbitAt(0, 100);
    const centre = projectPoint(0, 0, 0, camera, 400, 800);
    const right = projectPoint(50, 0, 0, camera, 400, 800);

    expect(right.x).toBeGreaterThan(centre.x);
    expect(right.y).toBeCloseTo(centre.y);
  });

  it("keeps the camera between the poles", () => {
    expect(clampPhi(-1)).toBe(MIN_PHI);
    expect(clampPhi(10)).toBe(MAX_PHI);
    expect(clampPhi(1)).toBe(1);
  });
});
