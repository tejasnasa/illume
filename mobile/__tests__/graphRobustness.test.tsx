/**
 * Edge cases that must never take the graph screen down: empty and
 * malformed payloads, non-finite positions, oversized graphs, the bracket
 * sizing, and the boundary that contains a render failure.
 */

import { render, screen } from "@testing-library/react-native";
import { Text } from "react-native";

import { RenderBoundary } from "@/components/RenderBoundary";
import {
  BRACKET_MIN_PX,
  bracketHalfSize,
  bracketVertices,
  worldPerPixel,
} from "@/lib/graphBrackets";
import {
  MAX_LAYOUT_NODES,
  boundingRadius,
  computeLayout,
  finiteOrZero,
} from "@/lib/graphLayout";
import type { GraphPayload } from "@/lib/graphTypes";

jest.mock("expo-router", () => ({
  __esModule: true,
  useGlobalSearchParams: () => ({}),
  useIsFocused: () => true,
}));

function node(id: string, loc = 10) {
  return {
    id,
    label: id,
    path: `src/${id}.ts`,
    group: "src",
    kind: "file",
    loc,
    criticality: "safe",
    criticality_score: 0,
    language: "TypeScript",
    fan_in: 0,
    fan_out: 0,
  };
}

function payload(
  nodes: ReturnType<typeof node>[],
  links: GraphPayload["links"] = [],
): GraphPayload {
  return {
    nodes,
    links,
    metadata: { total_nodes: nodes.length, total_edges: links.length, clusters: 1 },
  } as GraphPayload;
}

describe("computeLayout edge cases", () => {
  it("lays out an empty graph without simulating", async () => {
    const result = await computeLayout(payload([]));
    expect(result.positions.length).toBe(0);
    expect(result.links).toEqual([]);
    expect(result.boundingRadius).toBe(1);
    expect(result.nodeCount).toBe(0);
    expect(result.truncated).toBe(false);
  });

  it("treats a payload with missing lists as empty", async () => {
    const broken = {} as unknown as GraphPayload;
    const result = await computeLayout(broken);
    expect(result.nodeCount).toBe(0);
    const nullish = { nodes: null, links: null } as unknown as GraphPayload;
    expect((await computeLayout(nullish)).nodeCount).toBe(0);
  });

  it("copes with a null payload", async () => {
    const result = await computeLayout(null as unknown as GraphPayload);
    expect(result.nodeCount).toBe(0);
  });

  it("lays out a single node with every position finite", async () => {
    const result = await computeLayout(payload([node("a")]), { ticks: 5 });
    expect(result.positions.length).toBe(3);
    for (const v of result.positions) expect(Number.isFinite(v)).toBe(true);
    expect(Number.isFinite(result.boundingRadius)).toBe(true);
  });

  it("drops links to unknown nodes and self links", async () => {
    const result = await computeLayout(
      payload(
        [node("a"), node("b")],
        [
          { source: "a", target: "b", type: "imports", weight: 1 },
          { source: "a", target: "ghost", type: "imports", weight: 1 },
          { source: "b", target: "b", type: "imports", weight: 1 },
        ] as GraphPayload["links"],
      ),
      { ticks: 5 },
    );
    expect(result.links).toEqual([{ source: 0, target: 1 }]);
  });

  it("caps an oversized payload and says so", async () => {
    const nodes = Array.from({ length: MAX_LAYOUT_NODES + 5 }, (_, i) =>
      node(`n${i}`),
    );
    const result = await computeLayout(payload(nodes), { ticks: 1 });
    expect(result.truncated).toBe(true);
    expect(result.nodeCount).toBe(MAX_LAYOUT_NODES);
    expect(result.positions.length).toBe(MAX_LAYOUT_NODES * 3);
  }, 60_000);

  it("stops between chunks when aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const result = await computeLayout(payload([node("a"), node("b")]), {
      ticks: 100,
      signal: controller.signal,
    });
    expect(result.ticks).toBe(0);
    expect(result.positions.length).toBe(6);
  });

  it("replaces non-finite coordinates with zero", () => {
    expect(finiteOrZero(NaN)).toBe(0);
    expect(finiteOrZero(Infinity)).toBe(0);
    expect(finiteOrZero(undefined)).toBe(0);
    expect(finiteOrZero(4)).toBe(4);
  });

  it("ignores NaN and infinite positions when framing the camera", () => {
    expect(boundingRadius(new Float32Array([NaN, 0, 0]))).toBe(1);
    expect(boundingRadius(new Float32Array([Infinity, 0, 0]))).toBe(1);
    expect(boundingRadius(new Float32Array([3, 4, 0, NaN, 1, 1]))).toBe(5);
    expect(boundingRadius(new Float32Array(0))).toBe(1);
  });
});

describe("bracket sizing", () => {
  it("covers more world units per pixel the further the camera is", () => {
    expect(worldPerPixel(200, 800)).toBeGreaterThan(worldPerPixel(100, 800));
  });

  it("returns zero for inputs that cannot give a size", () => {
    expect(worldPerPixel(0, 800)).toBe(0);
    expect(worldPerPixel(100, 0)).toBe(0);
    expect(worldPerPixel(NaN, 800)).toBe(0);
  });

  it("never draws smaller than the on-screen minimum", () => {
    const far = bracketHalfSize(0.5, 1000, 800);
    const onScreenSide = (2 * far) / worldPerPixel(1000, 800);
    expect(onScreenSide).toBeGreaterThanOrEqual(BRACKET_MIN_PX - 1e-6);
  });

  it("lets a large node frame itself when zoomed in", () => {
    expect(bracketHalfSize(50, 10, 800)).toBe(50);
  });

  it("is finite and non-negative for bad input", () => {
    expect(bracketHalfSize(NaN, 100, 800)).toBeGreaterThanOrEqual(0);
    expect(bracketHalfSize(-3, NaN, 0)).toBe(0);
    expect(Number.isFinite(bracketHalfSize(1, Infinity, 800))).toBe(true);
  });

  it("builds four corners of two arms each", () => {
    const v = bracketVertices();
    expect(v.length).toBe(8 * 2 * 3);
    for (const x of v) expect(Math.abs(x)).toBeLessThanOrEqual(1);
  });
});

describe("RenderBoundary", () => {
  it("renders its children when nothing throws", async () => {
    await render(
      <RenderBoundary>
        <Text>fine</Text>
      </RenderBoundary>,
    );
    expect(screen.getByText("fine")).toBeTruthy();
  });

  it("shows a message when a child throws", async () => {
    const spy = jest.spyOn(console, "error").mockImplementation(() => {});
    const onError = jest.fn();
    function Boom(): never {
      throw new Error("gl exploded");
    }
    await render(
      <RenderBoundary title="Could not draw" onError={onError}>
        <Boom />
      </RenderBoundary>,
    );
    expect(screen.getByText("Could not draw")).toBeTruthy();
    expect(screen.getByText("gl exploded")).toBeTruthy();
    expect(onError).toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe("graphErrorMessage", () => {
  it("explains a 409 as not ready", () => {
    const { graphErrorMessage } = require("@/app/(app)/repo/[id]/graph");
    const { ApiError } = require("@/lib/apiError");
    const err = new ApiError({ kind: "clientError", status: 409, message: "x" });
    expect(graphErrorMessage(err)).toMatch(/still being analysed/);
    expect(graphErrorMessage(new Error("boom"))).toMatch(/could not be loaded/);
  });
});
