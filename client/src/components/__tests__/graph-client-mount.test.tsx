import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import GraphClient from "@/components/GraphClient";
import type Graph from "@/types/graph";
import type Guide from "@/types/guide";

/**
 * The 3D dependency graph.
 *
 * This is a **mount smoke**, not a behavioural test. The component's output is a WebGL
 * canvas, which happy-dom cannot render, and its interesting behaviour -- node selection,
 * the reading-order tour, search halos -- is driven by frame callbacks inside the graph
 * library. What is asserted here is that it mounts, hands the right data to the library,
 * and does not crash on the shapes the API actually returns. The rendering itself is
 * covered by the E2E canvas pixel smoke.
 *
 * The mock is a class because the component drives it through a ref, exactly as in
 * `background-graph-mount.test.tsx`.
 */
const mockReceived: Record<string, unknown>[] = [];

vi.mock("react-force-graph-3d", async () => {
  const React = await import("react");
  class MockForceGraph3D extends React.Component<Record<string, unknown>> {
    cameraPosition() {
      return { x: 0, y: 0, z: 100 };
    }
    d3Force() {
      return { strength: () => {}, distance: () => {} };
    }
    d3ReheatSimulation() {}
    zoomToFit() {}
    render() {
      mockReceived.push(this.props);
      return React.createElement("div", { "data-testid": "force-graph" });
    }
  }
  return { default: MockForceGraph3D };
});

/** Bypasses `dynamic`'s wrapper so the ref reaches the mock; see the other mount test. */
vi.mock("next/dynamic", async () => {
  const { default: MockForceGraph3D } = await import("react-force-graph-3d");
  return { default: () => MockForceGraph3D };
});

const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh, back: vi.fn() }),
}));

const GRAPH: Graph = {
  nodes: [
    {
      id: "1",
      label: "a.py",
      path: "src/a.py",
      group: "src",
      kind: "file",
      loc: 40,
      language: "python",
      fan_in: 0,
      fan_out: 1,
      criticality: "safe",
      criticality_score: 25,
    },
    {
      id: "2",
      label: "b.py",
      path: "src/b.py",
      group: "src",
      kind: "file",
      loc: 90,
      language: "python",
      fan_in: 1,
      fan_out: 0,
      criticality: "critical",
      criticality_score: 100,
    },
  ],
  links: [{ source: "1", target: "2", type: "imports", weight: 1 }],
  metadata: { total_nodes: 2, total_edges: 1, clusters: 1 },
};

const GUIDE: Guide = {
  repository_id: "r1",
  reading_order: [
    { position: 1, file_path: "src/a.py", annotation: "Start here.", fan_in: 0 },
    { position: 2, file_path: "src/b.py", annotation: "Then this.", fan_in: 1 },
  ],
  critical_files: [],
  architecture_brief: null,
  pdf_ready: false,
} as unknown as Guide;

/** Renders with defaults. */
function renderClient(props: Partial<React.ComponentProps<typeof GraphClient>> = {}) {
  const defaults = {
    graphData: GRAPH,
    guide: GUIDE,
    currentLevel: "file",
    repoId: "r1",
    github_url: "https://github.com/example/cool-project",
  };
  return render(<GraphClient {...{ ...defaults, ...props }} />);
}

/** Lets the dynamic import and the first frame settle. */
async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
  mockReceived.length = 0;
  vi.clearAllMocks();
});

describe("mounting", () => {
  it("renders the graph host", async () => {
    renderClient();

    await settle();

    expect(screen.getByTestId("force-graph")).toBeInTheDocument();
  });

  it("hands the nodes and links to the library", async () => {
    renderClient();

    await settle();

    // The whole payload, metadata included -- and the component ignores `metadata`
    // entirely, which is why it is passed through untouched.
    expect(mockReceived.at(-1)?.graphData).toEqual(GRAPH);
  });

  it("renders an empty graph without crashing", async () => {
    // A ready repository with no parsed files yields empty arrays; the component has to
    // survive that rather than dividing by a node count.
    renderClient({
      graphData: {
        nodes: [],
        links: [],
        metadata: { total_nodes: 0, total_edges: 0, clusters: 0 },
      },
    });

    await settle();

    expect(screen.getByTestId("force-graph")).toBeInTheDocument();
  });

  it("renders a graph with no reading order", async () => {
    // The guide is generated after the graph, so a repository can briefly have one and
    // not the other.
    renderClient({ guide: { ...GUIDE, reading_order: [] } as unknown as Guide });

    await settle();

    expect(screen.getByTestId("force-graph")).toBeInTheDocument();
  });
});

describe("node sizing", () => {
  it("derives node size from lines of code", async () => {
    // `sqrt(loc) * 0.5` with a floor of 10 LOC, so a 40-line file and a 90-line file are
    // visibly different -- the size is the only encoding of file weight on screen.
    renderClient();

    await settle();

    const nodeVal = mockReceived.at(-1)?.nodeVal as ((node: unknown) => number) | undefined;
    expect(typeof nodeVal).toBe("function");
    expect(nodeVal!({ loc: 40 })).toBeCloseTo(Math.sqrt(40) * 0.5);
    expect(nodeVal!({ loc: 90 })).toBeCloseTo(Math.sqrt(90) * 0.5);
  });

  it("floors the size for a file with no recorded lines", async () => {
    renderClient();

    await settle();

    const nodeVal = mockReceived.at(-1)?.nodeVal as ((node: unknown) => number) | undefined;
    expect(nodeVal!({ loc: 0 })).toBeCloseTo(Math.sqrt(10) * 0.5);
  });
});

describe("selecting a node", () => {
  /** The node-click handler the component handed to the graph library. */
  async function nodeClickHandler() {
    renderClient();
    await settle();
    return mockReceived.at(-1)?.onNodeClick as ((node: unknown) => void) | undefined;
  }

  it("opens the inspector for a file in the reading order", async () => {
    const onClick = await nodeClickHandler();

    act(() => onClick!({ id: "1", label: "a.py", path: "src/a.py" }));

    expect(screen.getByText(/src\/a\.py/)).toBeInTheDocument();
  });

  it("survives a node the reading order does not mention", async () => {
    // The defect this covers, confirmed rather than theorised:
    //
    //   TypeError: Cannot read properties of undefined (reading 'annotation')
    //
    // `readingOrderMap` is built only from `guide.reading_order`, and the inspector was
    // rendered as `annotation={readingOrderMap[selectedNode?.path].annotation ?? null}`.
    // The `?? null` guarded the *property*, not the lookup -- so the fallback was
    // unreachable and any node outside the tour threw during render.
    //
    // Reachable in practice: the reading order is capped at
    // `onboarding.MAX_ANNOTATED_FILES = 100`, so every node in a file past the cap is
    // outside it -- as are all symbols whose file is not in the tour.
    const onClick = await nodeClickHandler();

    expect(() =>
      act(() => onClick!({ id: "3", label: "c.py", path: "src/c.py" })),
    ).not.toThrow();
    expect(screen.getByText(/src\/c\.py/)).toBeInTheDocument();
  });
});

describe("the guide", () => {
  it("renders without a guide rather than crashing", async () => {
    // `graph/page.tsx` fetches the guide with `.catch(() => null)`, because `GetGuide`
    // throws a 404 for a repository that has none. Reading `guide.reading_order` during
    // render with no optional chaining made an absent guide a crash instead of a degraded
    // view, so a repository with a graph but no guide rendered no graph page at all --
    // which, while guides were not being generated, was every repository.
    renderClient({ guide: null });

    await settle();

    expect(screen.getByText(/Dependency Graph/)).toBeInTheDocument();
  });

  it("hides the reading-order tour when there is nothing to walk", async () => {
    // The tour is the only part of the page that needs a guide, so with none it is hidden
    // rather than rendered as "Reading Order: — / 0", which is not actionable.
    renderClient({ guide: null });

    await settle();

    expect(screen.queryByText(/Reading Order/)).not.toBeInTheDocument();
  });
});
