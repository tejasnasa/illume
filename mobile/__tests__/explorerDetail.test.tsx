/**
 * Tests for the explorer's file details: the `file` route parameter, the
 * symbols and recent commits, the neighbourhood and the neighbour lists.
 */

import React from "react";
import { act, fireEvent, render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";

import ExplorerScreen from "@/app/(app)/repo/[id]/explorer";
import {
  NeighbourhoodCard,
  NeighbourListCard,
} from "@/components/explorer/FileExtras";
import {
  NEIGHBOUR_SIDE_MAX,
  layoutNeighbourhood,
  neighboursByPath,
} from "@/lib/neighbourhood";
import { __setTokenStoreImplementation } from "@/lib/tokenStore";
import type { FileNode } from "@/types/explorer";

const mockParams: Record<string, string> = { id: "42", file: "src/app.ts" };

jest.mock("expo-router", () => {
  function noop() {
    /* router stub */
  }
  const routerObj = { push: noop, replace: noop, back: noop, navigate: noop };
  return {
    __esModule: true,
    default: routerObj,
    router: routerObj,
    useRouter: () => routerObj,
    useGlobalSearchParams: () => mockParams,
    Stack: ((p: { children?: unknown }) => p.children) as unknown as object,
    Redirect: (() => null) as unknown as object,
  };
});

function file(id: string, path: string, criticality = "safe"): FileNode {
  return {
    id,
    label: path.split("/").pop() as string,
    path,
    group: "src",
    kind: "file",
    loc: 10,
    criticality,
    language: "TypeScript",
    fan_in: 0,
    fan_out: 0,
  };
}

const NODES = [file("1", "src/app.ts", "critical"), file("2", "src/util.ts"), file("3", "src/main.ts")];
const LINKS = [
  { source: "3", target: "1", type: "imports", weight: 1 },
  { source: "1", target: "2", type: "imports", weight: 1 },
  { source: "1", target: "2", type: "imports", weight: 1 },
];

describe("neighboursByPath", () => {
  it("splits importers from imports and skips duplicates", () => {
    const { importers, imports } = neighboursByPath(NODES, LINKS, "src/app.ts");
    expect(importers.map((f) => f.path)).toEqual(["src/main.ts"]);
    expect(imports.map((f) => f.path)).toEqual(["src/util.ts"]);
  });

  it("is empty for an unknown path or a link to a missing node", () => {
    expect(neighboursByPath(NODES, LINKS, "nope.ts")).toEqual({ importers: [], imports: [] });
    expect(
      neighboursByPath(NODES, [{ source: "9", target: "1" }], "src/app.ts").importers,
    ).toEqual([]);
  });
});

describe("layoutNeighbourhood", () => {
  it("puts the file in the middle, importers left and imports right", () => {
    const scene = layoutNeighbourhood(NODES[0], [NODES[2]], [NODES[1]], 320, 200);
    const [self, left, right] = scene.pixels;
    expect(self.selected).toBe(true);
    expect(self.x).toBe(160);
    expect(left.x).toBeLessThan(160);
    expect(right.x).toBeGreaterThan(160);
    expect(scene.lines).toHaveLength(2);
    expect(scene.hidden).toEqual({ importers: 0, imports: 0 });
  });

  it("caps each side and keeps every pixel on the canvas", () => {
    const many = Array.from({ length: 40 }, (_, i) => file(`m${i}`, `src/m${i}.ts`));
    const scene = layoutNeighbourhood(NODES[0], many, [], 320, 200);
    expect(scene.pixels).toHaveLength(1 + NEIGHBOUR_SIDE_MAX);
    expect(scene.hidden.importers).toBe(40 - NEIGHBOUR_SIDE_MAX);
    for (const p of scene.pixels) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(320);
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeLessThanOrEqual(200);
    }
  });
});

describe("neighbour cards", () => {
  it("draws the picture and selects a neighbour by path", async () => {
    const onSelectPath = jest.fn();
    const screen = await render(
      <>
        <NeighbourhoodCard file={NODES[0]} importers={[NODES[2]]} imports={[NODES[1]]} />
        <NeighbourListCard
          title="Imports"
          testID="file-imports"
          files={[NODES[1]]}
          empty="none"
          onSelectPath={onSelectPath}
        />
      </>,
    );
    expect(screen.getByTestId("file-neighbourhood")).toBeTruthy();
    await fireEvent.press(screen.getByTestId("neighbour-src/util.ts"));
    expect(onSelectPath).toHaveBeenCalledWith("src/util.ts");
  });

  it("says when a file has no neighbours", async () => {
    const screen = await render(
      <NeighbourListCard
        title="Imported by"
        testID="file-importers"
        files={[]}
        empty="Nothing imports this file"
        onSelectPath={() => {}}
      />,
    );
    expect(screen.getByText("Nothing imports this file")).toBeTruthy();
  });
});

describe("ExplorerScreen file details", () => {
  let original: typeof fetch;

  beforeEach(() => {
    __setTokenStoreImplementation({
      async getItemAsync() {
        return "valid-jwt";
      },
      async setItemAsync() {},
      async deleteItemAsync() {},
    });
    original = global.fetch;
  });

  afterEach(() => {
    (global as unknown as { fetch: typeof fetch }).fetch = original;
  });

  it("opens the file named in the route and lists its symbols and commits", async () => {
    const calls: string[] = [];
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    const fetchImpl = jest.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      if (url.includes("/repo-1/graph")) {
        return json({
          nodes: NODES.map((n) => ({ ...n, criticality_score: 1 })),
          links: LINKS,
          metadata: { total_nodes: 3, total_edges: 2, clusters: 1 },
        });
      }
      if (url.includes("/repo-1/file?")) {
        return json({
          symbols: [{ kind: "function", name: "boot", start_line: 12 }],
          commits: [
            { hash: "abcdef1234", title: "Wire the boot", author: "Ada", at: "2026-01-01T00:00:00Z" },
          ],
        });
      }
      if (url.includes("/repo-1/guide")) {
        return json({
          repository_id: "repo-1",
          reading_order: [{ position: 2, file_path: "src/app.ts", annotation: "Start here", fan_in: 1 }],
          critical_files: [],
          architecture_brief: null,
        });
      }
      if (url.includes("/repo-1/ownership")) return json({ files: [], total: 0 });
      if (url.endsWith("/api/v1/repository/42")) {
        return json({
          id: "repo-1",
          github_url: "https://github.com/example/foo",
          name: "foo",
          status: "ready",
          architecture_summary: null,
          repo_number: 42,
          primary_language: null,
          detected_stack: null,
          entry_points: null,
          ingested_branch: "main",
          ingested_commit_sha: "abcdef1234567890",
          analysis_commit_sha: null,
          created_at: "2026-01-15T12:00:00Z",
          updated_at: "2026-01-15T12:00:00Z",
        });
      }
      return new Response("not found", { status: 404 });
    });
    (global as unknown as { fetch: typeof fetch }).fetch = fetchImpl as unknown as typeof fetch;

    const screen = await render(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 0, height: 0 },
          insets: { top: 0, left: 0, right: 0, bottom: 0 },
        }}
      >
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <ExplorerScreen />
        </QueryClientProvider>
      </SafeAreaProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("explorer-details")).toBeTruthy();
    });
    await waitFor(() => {
      expect(screen.getByText("boot")).toBeTruthy();
      expect(screen.getByText("Wire the boot")).toBeTruthy();
    });
    expect(screen.getByText(/Read 2/)).toBeTruthy();
    expect(screen.getByText(/Start here/)).toBeTruthy();
    expect(screen.getByTestId("neighbour-src/main.ts")).toBeTruthy();
    expect(screen.getByTestId("neighbour-src/util.ts")).toBeTruthy();
    expect(
      calls.some((u) => u.includes("/repo-1/file?path=src%2Fapp.ts&commits=3")),
    ).toBe(true);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  });
});
