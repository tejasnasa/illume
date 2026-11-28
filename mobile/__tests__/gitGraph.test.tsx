/**
 * Tests for :component:`GitGraph`, the commit timeline in the picker.
 *
 * - The box is the same height while the history loads and once it has
 *   loaded, and shows a loading label in between.
 * - Commit nodes are drawn in their lane colour, never in the background
 *   colour (which made them invisible), and the selected node is white with
 *   a lane-coloured outline.
 * - The footer names the target and offers Back.
 */

import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { GitGraph, TIMELINE_HEIGHT } from "@/components/GitGraph";
import { RAIL_COLORS } from "@/lib/gitGraphLayout";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";
import { colors } from "@/theme/tokens";

const BRANCHES = [
  { name: "main", sha: "aaa1111", is_default: true },
  { name: "feature", sha: "bbb2222", is_default: false },
];

const COMMITS = [
  {
    sha: "aaa1111aaaa",
    short_sha: "aaa1111",
    message: "Add the ingest endpoint",
    author_name: "Ada",
    author_avatar: null,
    authored_at: "2026-01-15T10:00:00Z",
    parents: ["ccc3333cccc"],
    branches: ["main"],
  },
  {
    sha: "ccc3333cccc",
    short_sha: "ccc3333",
    message: "Initial commit",
    author_name: "Ada",
    author_avatar: null,
    authored_at: "2026-01-13T10:00:00Z",
    parents: [],
    branches: ["main"],
  },
];

let originalFetch: typeof fetch;

beforeEach(() => {
  originalFetch = global.fetch;
  __setTokenStoreImplementation({
    async getItemAsync() {
      return null;
    },
    async setItemAsync() {},
    async deleteItemAsync() {},
  });
  (global as unknown as { fetch: typeof fetch }).fetch = (async (
    input: RequestInfo | URL,
  ) => {
    const url = String(input);
    const body = url.includes("/branches")
      ? BRANCHES
      : url.includes("/commits-multibranch")
        ? COMMITS
        : null;
    if (!body) return new Response("not found", { status: 404 });
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
});

afterEach(() => {
  (global as unknown as { fetch: typeof fetch }).fetch = originalFetch;
});

/** Render the timeline with the provider stack the picker uses. */
async function renderGraph(props: Partial<React.ComponentProps<typeof GitGraph>> = {}) {
  return render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 0, height: 0 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <GitGraph owner="o" repo="r" onSelect={() => {}} {...props} />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

/** A node of the rendered tree, as ``toJSON`` returns it. */
interface TreeNode {
  type: string;
  props: Record<string, unknown>;
  children: (TreeNode | string)[] | null;
}

/**
 * Turn the native colour value svg serialises into a ``#rrggbb`` string.
 *
 * @param value - A colour string, or the ``{ payload }`` ARGB form.
 * @returns The colour as lowercase hex.
 */
function hex(value: unknown): unknown {
  const payload = (value as { payload?: number } | undefined)?.payload;
  if (typeof payload !== "number") return value;
  return `#${(payload & 0xffffff).toString(16).padStart(6, "0")}`;
}

/**
 * Collect the fill and stroke of every svg rectangle in the rendered tree.
 *
 * @param tree - The rendered tree.
 * @returns One entry per rectangle, in draw order.
 */
function nodeFills(tree: unknown): { fill?: unknown; stroke?: unknown }[] {
  const found: { fill?: unknown; stroke?: unknown }[] = [];
  const walk = (node: TreeNode | string | null) => {
    if (!node || typeof node === "string") return;
    if (node.type === "RNSVGRect") {
      found.push({ fill: hex(node.props.fill), stroke: hex(node.props.stroke) });
    }
    node.children?.forEach(walk);
  };
  [tree].flat().forEach((root) => walk(root as TreeNode));
  return found;
}

describe("GitGraph", () => {
  it("keeps the box the same height while loading and once loaded", async () => {
    const screen = await renderGraph();

    const heightOf = () => {
      const style = screen.getByTestId("gitgraph-box").props.style;
      return [style].flat(Infinity).find((s: any) => s?.height)?.height;
    };

    expect(screen.getByTestId("gitgraph-loading")).toBeTruthy();
    expect(screen.getByText("Loading history")).toBeTruthy();
    expect(heightOf()).toBe(TIMELINE_HEIGHT);

    await waitFor(() => {
      expect(screen.getByTestId("gitgraph-commit-aaa1111")).toBeTruthy();
    });
    expect(screen.queryByTestId("gitgraph-loading")).toBeNull();
    expect(heightOf()).toBe(TIMELINE_HEIGHT);
  });

  it("draws nodes in their lane colour and never in the background colour", async () => {
    const screen = await renderGraph();
    await waitFor(() => {
      expect(screen.getByTestId("gitgraph-commit-aaa1111")).toBeTruthy();
    });

    const nodes = nodeFills(screen.toJSON());
    expect(nodes).toHaveLength(2);
    for (const node of nodes) {
      expect(node.fill).toBe(RAIL_COLORS[0]);
      expect(node.fill).not.toBe(colors.background);
    }
  });

  it("draws the selected node white with a lane-coloured outline", async () => {
    const screen = await renderGraph();
    await waitFor(() => {
      expect(screen.getByTestId("gitgraph-commit-aaa1111")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(screen.getByTestId("gitgraph-commit-aaa1111"));
    });

    const nodes = nodeFills(screen.toJSON());
    expect(nodes.filter((n) => n.fill === colors.foreground)).toEqual([
      { fill: colors.foreground, stroke: RAIL_COLORS[0] },
    ]);
  });

  it("names the target on the ingest button and offers Back", async () => {
    const onBack = jest.fn();
    const screen = await renderGraph({ onBack });
    await waitFor(() => {
      expect(screen.getByTestId("gitgraph-commit-aaa1111")).toBeTruthy();
    });

    expect(screen.getByText("Ingest branch main @ tip →")).toBeTruthy();

    await act(async () => {
      fireEvent.press(screen.getByTestId("gitgraph-commit-aaa1111"));
    });
    expect(screen.getByText("Ingest commit aaa1111 on main →")).toBeTruthy();

    fireEvent.press(screen.getByTestId("gitgraph-back"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
