import { act, render, screen } from "@testing-library/react-native";

import {
  buildConstellation,
  projectConstellation,
} from "@/lib/pixelConstellation";
import { PixelGraph } from "@/ui/PixelGraph";

let mockReduced = false;
jest.mock("@/hooks/useReducedMotion", () => ({
  useReducedMotion: () => mockReduced,
}));

describe("constellation", () => {
  it("builds a core, hubs and files, and is deterministic", () => {
    const scene = buildConstellation(7, 5, 10);
    expect(scene.nodes).toHaveLength(1 + 5 + 50);
    expect(scene.nodes.filter((n) => n.kind === 2)).toHaveLength(1);
    expect(scene.nodes.filter((n) => n.kind === 1)).toHaveLength(5);
    expect(buildConstellation(7, 5, 10)).toEqual(scene);
    expect(buildConstellation(8, 5, 10)).not.toEqual(scene);
  });

  it("copes with zero or negative counts", () => {
    expect(buildConstellation(1, 0, 5).nodes).toHaveLength(1);
    expect(buildConstellation(1, -2, -3).nodes).toHaveLength(1);
    expect(buildConstellation(1, 1, 0).nodes).toHaveLength(2);
  });

  it("projects every node to finite grid-aligned coordinates", () => {
    const scene = buildConstellation(3, 6, 8);
    const { pixels, edges } = projectConstellation(scene, 1.3, 360, 400, 4);
    expect(pixels).toHaveLength(scene.nodes.length);
    expect(edges).toHaveLength(scene.nodes.length - 1);
    for (const p of pixels) {
      expect(Number.isFinite(p.x) && Number.isFinite(p.y)).toBe(true);
      expect(p.x % 4).toBe(0);
      expect(p.opacity).toBeGreaterThan(0);
      expect(p.opacity).toBeLessThanOrEqual(1);
    }
  });

  it("changes with the angle and returns nothing for an empty box", () => {
    const scene = buildConstellation(3, 6, 8);
    expect(projectConstellation(scene, 0, 360, 400).pixels).not.toEqual(
      projectConstellation(scene, 1, 360, 400).pixels,
    );
    expect(projectConstellation(scene, 0, 0, 400)).toEqual({ pixels: [], edges: [] });
  });
});

describe("PixelGraph", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockReduced = false;
  });
  afterEach(() => jest.useRealTimers());

  it("renders without taking touches or screen-reader focus", async () => {
    await render(<PixelGraph width={300} height={300} />);
    const node = screen.getByTestId("pixel-graph", { includeHiddenElements: true });
    expect(node.props.pointerEvents).toBe("none");
  });

  it("animates by timer, and holds still under reduce motion", async () => {
    const spy = jest.spyOn(global, "setInterval");
    await render(<PixelGraph width={300} height={300} />);
    expect(spy).toHaveBeenCalled();
    await act(async () => {
      jest.advanceTimersByTime(300);
    });
    spy.mockClear();
    mockReduced = true;
    await render(<PixelGraph width={300} height={300} seed={9} />);
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});
