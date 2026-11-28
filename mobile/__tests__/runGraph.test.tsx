import { fireEvent, render, screen } from "@testing-library/react-native";

import { RunGraph } from "@/components/chat/RunGraph";
import { CITED_COLOR, CURRENT_COLOR, MAIN_COLOR } from "@/lib/agent/palette";
import { initialRunState, settledRunState, type Highlight, type RunState } from "@/lib/agent/reducer";
import { SKETCH_MAX_NODES, sketchGraph } from "@/lib/overview";
import { hasLitFiles, laneColorsOf, litPaths, looksFor } from "@/lib/runGraph";
import type Graph from "@/types/graph";

function node(i: number, fan = 0) {
  return {
    id: `n${i}`,
    label: `f${i}.ts`,
    path: `src/f${i}.ts`,
    group: "src",
    kind: "file",
    loc: 1,
    criticality: "safe",
    criticality_score: 0,
    language: "TypeScript",
    fan_in: fan,
    fan_out: 0,
  };
}

function graphOf(count: number): Graph {
  return {
    nodes: Array.from({ length: count }, (_, i) => node(i, count - i)),
    links: [{ source: "n0", target: "n1", type: "imports", weight: 1 }],
    metadata: { total_nodes: count, total_edges: 1, clusters: 1 },
  };
}

function highlight(over: Partial<Highlight> = {}): Highlight {
  return {
    touched: [],
    current: [],
    laneOf: {},
    edges: [],
    focusSeq: 0,
    focus: null,
    cited: [],
    ...over,
  };
}

describe("looksFor", () => {
  it("colours touched files by lane and the main agent by default", () => {
    const looks = looksFor(
      highlight({ touched: ["a", "b"], laneOf: { a: "w1", b: null } }),
      { w1: "#38bdf8" },
      true,
    );
    expect(looks.get("a")?.color).toBe("#38bdf8");
    expect(looks.get("b")?.color).toBe(MAIN_COLOR);
  });

  it("enlarges the current files while live and gilds the cited ones after", () => {
    const h = highlight({ touched: ["a"], current: ["a"], cited: ["c"] });
    const live = looksFor(h, {}, true);
    expect(live.get("a")?.color).toBe(CURRENT_COLOR);
    expect(live.has("c")).toBe(false);
    const done = looksFor(h, {}, false);
    expect(done.get("a")?.color).toBe(MAIN_COLOR);
    expect(done.get("c")?.color).toBe(CITED_COLOR);
  });

  it("collects lit paths and reports whether anything is lit", () => {
    const h = highlight({ touched: ["a"], current: ["b"], cited: ["a", "c"] });
    expect([...litPaths(h)].sort()).toEqual(["a", "b", "c"]);
    expect(hasLitFiles(h)).toBe(true);
    expect(hasLitFiles(highlight())).toBe(false);
  });

  it("reads lane colours from the run", () => {
    const run = {
      ...initialRunState,
      lanes: { w1: { id: "w1", question: "q", status: "running" as const, colorIndex: 1 } },
    };
    expect(laneColorsOf(run).w1).toMatch(/^#/);
  });
});

describe("sketchGraph keep", () => {
  it("keeps a lit file that is not among the busiest", () => {
    const graph = graphOf(SKETCH_MAX_NODES + 20);
    const lastPath = `src/f${SKETCH_MAX_NODES + 19}.ts`;
    expect(sketchGraph(graph).points.some((p) => p.path === lastPath)).toBe(false);
    const kept = sketchGraph(graph, new Set([lastPath]));
    expect(kept.points.some((p) => p.path === lastPath)).toBe(true);
    expect(kept.points).toHaveLength(SKETCH_MAX_NODES + 1);
  });
});

describe("RunGraph", () => {
  const graph = graphOf(5);

  it("renders nothing when the run lit no files", async () => {
    await render(<RunGraph graph={graph} run={initialRunState} />);
    expect(screen.queryByTestId("run-graph")).toBeNull();
  });

  it("opens from a collapsed header and counts the files", async () => {
    const run: RunState = {
      ...settledRunState("answer", [{ file_path: "src/f1.ts" }]),
      highlight: highlight({ touched: ["src/f0.ts"], cited: ["src/f1.ts"] }),
    };
    await render(<RunGraph graph={graph} run={run} />);
    expect(screen.getByText(/Graph · 2 files/)).toBeTruthy();
    await fireEvent.press(screen.getByTestId("run-graph-toggle"));
    expect(screen.getByTestId("run-graph-toggle").props.accessibilityState.expanded).toBe(true);
  });
});
