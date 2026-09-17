import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BACKEND_URL } from "../../../tests/msw/handlers";
import { server } from "../../../tests/msw/server";
import BackgroundGraph from "@/components/BackgroundGraph";

/**
 * `react-force-graph-3d` renders WebGL, which happy-dom has no context for. The module is
 * replaced with a component that records the props it was handed, so the test can assert
 * on what the app passed down rather than on pixels -- the real canvas is E2E's job,
 * which a pixel smoke covers.
 *
 * The mock is a **class** component, mirroring the real one. That matters because the
 * component drives it through a ref: it calls `fg.cameraPosition()` on every animation
 * frame, and a function component leaves the ref null (React warns) or, with
 * `forwardRef`, hands back an object that Next's `dynamic` wrapper does not pass through.
 * A class instance is what the real library provides and what the call site expects.
 *
 * Prefixed `mock` because `vi.mock` is hoisted above this declaration.
 */
const mockReceived: Record<string, unknown>[] = [];

vi.mock("react-force-graph-3d", async () => {
  const React = await import("react");

  class MockForceGraph3D extends React.Component<Record<string, unknown>> {
    /** Returns a position, as the orbit effect destructures `{ x, y, z }` from it. */
    cameraPosition() {
      return { x: 1, y: 1, z: 1 };
    }

    /** Returns a chainable force, matching the `d3Force(...).strength(...)` call. */
    d3Force() {
      return { strength: () => {}, distance: () => {} };
    }

    d3ReheatSimulation() {}

    render() {
      mockReceived.push(this.props);
      return React.createElement("div", { "data-testid": "force-graph" });
    }
  }

  return { default: MockForceGraph3D };
});

/**
 * `next/dynamic` is replaced with a direct passthrough to the mock above.
 *
 * Not an optimisation -- it is required for the ref to work. The real `dynamic()` returns
 * a wrapper component, and the ref React attaches goes to the wrapper rather than to the
 * library class underneath it, so the component's `fgRef.current` ends up holding
 * something that is truthy and has no `cameraPosition`. The orbit effect calls that method
 * every frame, so a plain mock produced a stream of unhandled `TypeError`s that did not
 * fail any assertion and would have masked a real one.
 *
 * The import is resolved by the module graph, so it picks up the mocked library.
 */
vi.mock("next/dynamic", async () => {
  const { default: MockForceGraph3D } = await import("react-force-graph-3d");
  return { default: () => MockForceGraph3D };
});

/** Resolves the next tick, so `next/dynamic`'s import has a chance to land. */
async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

const GRAPH = {
  nodes: [
    {
      id: "1",
      label: "a.py",
      path: "src/a.py",
      group: "src",
      kind: "file",
      loc: 10,
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
      loc: 20,
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

afterEach(() => {
  mockReceived.length = 0;
  vi.restoreAllMocks();
});

describe("mounting", () => {
  it("renders nothing without graph data", () => {
    // The layout renders this behind every repository route, including ones where the
    // graph has not loaded. Returning null there is the documented behaviour.
    const { container } = render(<BackgroundGraph graph={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders a canvas host once data arrives", async () => {
    render(<BackgroundGraph graph={GRAPH} />);

    await settle();

    expect(screen.getByTestId("force-graph")).toBeInTheDocument();
  });

  it("passes the nodes and links through", async () => {
    render(<BackgroundGraph graph={GRAPH} />);

    await settle();

    // `graphData` is the whole payload, metadata included -- not a reshaped subset.
    expect(mockReceived.at(-1)?.graphData).toEqual(GRAPH);
  });

  it("accepts an empty graph", async () => {
    // A ready repository with no files yields empty arrays; the component must not treat
    // that as "not loaded" and crash on undefined.
    render(
      <BackgroundGraph
        graph={{ nodes: [], links: [], metadata: { total_nodes: 0, total_edges: 0, clusters: 0 } }}
      />,
    );

    await settle();

    expect(screen.getByTestId("force-graph")).toBeInTheDocument();
  });
});

describe("interaction", () => {
  it("disables pointer interaction", async () => {
    // It is decorative and sits behind the page content, so it must not swallow clicks
    // meant for the UI on top of it.
    render(<BackgroundGraph graph={GRAPH} />);

    await settle();

    expect(mockReceived.at(-1)?.enablePointerInteraction).toBe(false);
  });

  it("labels nodes from the `label` field", async () => {
    // A string rather than a function: the accessor names the node property to show. The
    // difference matters because a function here would be called per node per frame.
    render(<BackgroundGraph graph={GRAPH} />);

    await settle();

    expect(mockReceived.at(-1)?.nodeLabel).toBe("label");
  });
});

describe("isolation", () => {
  it("makes no request of its own", async () => {
    // The graph is fetched by the layout and passed in. A second fetch here would double
    // the payload on every repository page.
    const spy = vi.fn();
    server.use(
      http.get(`${BACKEND_URL}/api/v1/repository/:id/graph`, () => {
        spy();
        return HttpResponse.json(GRAPH);
      }),
    );

    render(<BackgroundGraph graph={GRAPH} />);
    await settle();

    expect(spy).not.toHaveBeenCalled();
  });
});
