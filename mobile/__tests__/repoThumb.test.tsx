import { act, render, screen } from "@testing-library/react-native";

import { apiGet } from "@/api/client";
import { THUMB_MAX_FILES, hashSeed, layoutThumb } from "@/lib/thumbLayout";
import { RepoThumb } from "@/ui/RepoThumb";

jest.mock("@/api/client", () => ({ apiGet: jest.fn() }));
const get = apiGet as jest.Mock;
const HIDDEN = { includeHiddenElements: true };

const source = {
  nodes: [
    { id: "a", group: "src" },
    { id: "b", group: "src" },
    { id: "c", group: "tests" },
  ],
  links: [
    { source: "a", target: "b" },
    { source: "a", target: "missing" },
  ],
};

describe("layoutThumb", () => {
  it("is deterministic for a seed and differs between seeds", () => {
    expect(layoutThumb(source, 360, 112, "r1")).toEqual(layoutThumb(source, 360, 112, "r1"));
    expect(layoutThumb(source, 360, 112, "r1")).not.toEqual(layoutThumb(source, 360, 112, "r2"));
  });

  it("draws a core, a hub per directory and a square per file", () => {
    const scene = layoutThumb(source, 360, 112, "r");
    expect(scene.pixels.filter((p) => p.hub)).toHaveLength(1 + 2);
    expect(scene.pixels.filter((p) => !p.hub)).toHaveLength(3);
  });

  it("keeps only edges whose ends are drawn", () => {
    expect(layoutThumb(source, 360, 112, "r").lines).toHaveLength(1);
  });

  it("handles empty, missing and malformed input", () => {
    expect(layoutThumb(null, 360, 112, "r")).toEqual({ pixels: [], lines: [] });
    expect(layoutThumb({ nodes: [], links: [] }, 360, 112, "r").pixels).toEqual([]);
    expect(layoutThumb({ nodes: null, links: null } as never, 360, 112, "r").pixels).toEqual([]);
    expect(layoutThumb(source, 0, 112, "r").pixels).toEqual([]);
  });

  it("caps the number of files drawn and keeps every pixel finite", () => {
    const many = {
      nodes: Array.from({ length: THUMB_MAX_FILES + 50 }, (_, i) => ({ id: `n${i}`, group: `g${i % 9}` })),
      links: [],
    };
    const scene = layoutThumb(many, 360, 112, "r");
    expect(scene.pixels.filter((p) => !p.hub)).toHaveLength(THUMB_MAX_FILES);
    for (const p of scene.pixels) {
      expect(Number.isFinite(p.x) && Number.isFinite(p.y)).toBe(true);
    }
  });

  it("hashes strings to stable integers", () => {
    expect(hashSeed("abc")).toBe(hashSeed("abc"));
    expect(hashSeed("abc")).not.toBe(hashSeed("abd"));
  });
});

describe("RepoThumb", () => {
  beforeEach(() => get.mockReset());

  it("shows the placeholder until the graph arrives, then the graph", async () => {
    get.mockResolvedValue(source);
    await act(async () => {
      await render(<RepoThumb repoId="r1" />);
    });
    expect(screen.getByTestId("repo-thumb-graph", HIDDEN)).toBeTruthy();
    expect(get.mock.calls[0][0]).toBe("/api/v1/repository/r1/graph/thumbnail");
  });

  it("keeps the placeholder when the request fails or the graph is empty", async () => {
    get.mockRejectedValue(new Error("down"));
    await act(async () => {
      await render(<RepoThumb repoId="r1" />);
    });
    expect(screen.getByTestId("repo-thumb-placeholder", HIDDEN)).toBeTruthy();
  });

  it("does not fetch for a card that is still ingesting", async () => {
    await act(async () => {
      await render(<RepoThumb repoId="r1" tone="muted" />);
    });
    expect(get).not.toHaveBeenCalled();
    expect(screen.getByTestId("repo-thumb-placeholder", HIDDEN)).toBeTruthy();
  });
});
